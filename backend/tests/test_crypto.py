"""Crypto wallets: address detection, public explorers (mocked), OFAC addresses, demo scenario."""

import httpx
import pytest
import respx

from app.connectors import official_sanctions as osl
from app.connectors.chains import BitcoinConnector, EthereumConnector, TronConnector
from app.connectors.crypto_util import detect_chain, normalize_address, wallet_id
from app.models import Entity, EntityType, ListType, RelationType
from app.schemas import InvestigationRequest
from app.service import KbcService
from app.settings import Settings

LIVE = Settings(live_sources=True)
BTC = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"
BTC_OTHER = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
ETH = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
ETH_OTHER = "0x" + "1" * 40
TRX = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
TRX_OTHER = "TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE"
DEMO_WALLET = "TNRthgateMaritimeDEMwa111111111111"


@pytest.mark.parametrize(
    "address,chain",
    [(BTC, "BTC"), (BTC_OTHER, "BTC"), (ETH, "ETH"), (TRX, "TRON"), ("Danone", None)],
)
def test_detect_chain(address, chain):
    assert detect_chain(address) == chain


def test_eth_addresses_are_case_insensitive():
    assert normalize_address(ETH) == ETH.lower()
    assert wallet_id("ETH", ETH) == wallet_id("ETH", ETH.lower())


@respx.mock
def test_bitcoin_wallet_and_flows():
    respx.get(f"https://mempool.space/api/address/{BTC}").mock(
        return_value=httpx.Response(
            200,
            json={
                "address": BTC,
                "chain_stats": {
                    "funded_txo_sum": 300_000_000,
                    "spent_txo_sum": 100_000_000,
                    "tx_count": 3,
                },
            },
        )
    )
    respx.get(f"https://mempool.space/api/address/{BTC}/txs").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "txid": "a",
                    "status": {"block_time": 1700000000},
                    "vin": [{"prevout": {"scriptpubkey_address": BTC_OTHER, "value": 250_000_000}}],
                    "vout": [
                        {"scriptpubkey_address": BTC, "value": 200_000_000},
                        {"scriptpubkey_address": BTC_OTHER, "value": 49_000_000},
                    ],
                },
                {
                    "txid": "b",
                    "status": {"block_time": 1710000000},
                    "vin": [{"prevout": {"scriptpubkey_address": BTC, "value": 200_000_000}}],
                    "vout": [
                        {"scriptpubkey_address": BTC_OTHER, "value": 100_000_000},
                        {"scriptpubkey_address": BTC, "value": 99_000_000},
                    ],
                },
            ],
        )
    )
    conn = BitcoinConnector(LIVE)
    wallet = conn.get_wallet(BTC)
    assert (
        wallet.type == EntityType.WALLET
        and wallet.chain == "BTC"
        and wallet.extra["balance"] == "2 BTC"
    )
    flows = {
        (link.relationship.source_id == wallet.id, link.relationship.amount)
        for link in conn.get_wallet_links(wallet)
    }
    assert (False, 2.0) in flows  # 2 BTC received from BTC_OTHER
    assert (True, 1.0) in flows  # 1 BTC sent (change output ignored)


@respx.mock
def test_ethereum_eth_and_token_flows():
    base = "https://eth.blockscout.com/api/v2/addresses"
    respx.get(f"{base}/{ETH}").mock(
        return_value=httpx.Response(
            200,
            json={"hash": ETH, "coin_balance": str(5 * 10**18), "is_contract": False, "name": None},
        )
    )
    respx.get(f"{base}/{ETH}/counters").mock(
        return_value=httpx.Response(200, json={"transactions_count": "2"})
    )
    respx.get(f"{base}/{ETH}/transactions").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "from": {"hash": ETH_OTHER},
                        "to": {"hash": ETH},
                        "value": str(10**18),
                        "status": "ok",
                        "timestamp": "2024-01-02T00:00:00Z",
                    }
                ]
            },
        )
    )
    respx.get(f"{base}/{ETH}/token-transfers").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "from": {"hash": ETH},
                        "to": {"hash": ETH_OTHER},
                        "total": {"value": "2500000000", "decimals": "6"},
                        "token": {"symbol": "USDT"},
                        "timestamp": "2024-02-01T00:00:00Z",
                    }
                ]
            },
        )
    )
    conn = EthereumConnector(LIVE)
    wallet = conn.get_wallet(ETH)
    assert wallet.extra["balance"] == "5 ETH" and wallet.id == wallet_id("ETH", ETH)
    links = {
        (link.relationship.currency, link.relationship.amount)
        for link in conn.get_wallet_links(wallet)
    }
    assert links == {("ETH", 1.0), ("USDT", 2500.0)}


@respx.mock
def test_tron_trc20_flows():
    respx.get(f"https://api.trongrid.io/v1/accounts/{TRX}").mock(
        return_value=httpx.Response(
            200, json={"data": [{"balance": 12_000_000, "create_time": 1600000000000}]}
        )
    )
    respx.get(f"https://api.trongrid.io/v1/accounts/{TRX}/transactions/trc20").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "from": TRX_OTHER,
                        "to": TRX,
                        "value": "1000000000",
                        "block_timestamp": 1700000000000,
                        "token_info": {"symbol": "USDT", "decimals": 6},
                    }
                ]
            },
        )
    )
    conn = TronConnector(LIVE)
    wallet = conn.get_wallet(TRX)
    assert wallet.extra["balance"] == "12 TRX"
    [link] = conn.get_wallet_links(wallet)
    assert link.relationship.type == RelationType.TRANSFER and link.relationship.amount == 1000.0
    assert link.relationship.target_id == wallet.id and link.entity.name == TRX_OTHER
    assert conn.get_wallet_links(wallet, include_transfers=False) == []


SDN = f"""500,"EXAMPLE EXCHANGE LLC","-0- ","CYBER2",-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,"Digital Currency Address - XBT {BTC}; Digital Currency Address - USDT {TRX}; Website example.com."
"""


@respx.mock
def test_ofac_crypto_addresses_are_indexed_and_linked(monkeypatch):
    monkeypatch.setattr(osl, "_INDEX", osl._Index())
    respx.get(osl.OFAC_SDN).mock(return_value=httpx.Response(200, text=SDN))
    respx.get(osl.OFAC_ALT).mock(return_value=httpx.Response(200, text=""))
    respx.get(osl.UN_XML).mock(return_value=httpx.Response(200, text="<CONSOLIDATED_LIST/>"))
    conn = osl.OfficialSanctionsConnector(LIVE)
    wallet = Entity(id=wallet_id("TRON", TRX), type=EntityType.WALLET, name=TRX, chain="TRON")
    [hit] = conn.screen(wallet)
    assert (
        hit.list_type == ListType.SANCTION
        and hit.score == 100
        and hit.details["listed_owner"] == "EXAMPLE EXCHANGE LLC"
    )
    [owner] = conn.get_wallet_links(wallet)
    assert (
        owner.relationship.type == RelationType.CONTROLS
        and owner.entity.name == "EXAMPLE EXCHANGE LLC"
    )
    # From the sanctioned owner, its other listed addresses are found.
    wallets = {link.entity.name for link in conn.get_wallet_links(owner.entity)}
    assert wallets == {BTC, TRX}


def test_demo_wallet_search_and_investigation():
    svc = KbcService()
    [cand] = svc.search(DEMO_WALLET).candidates
    assert cand.entity.type == EntityType.WALLET and cand.linked_companies == [
        "Northgate Maritime Holdings Ltd"
    ]
    inv = svc.investigate(
        InvestigationRequest(record_ids=cand.entity.record_ids, depth=2, max_nodes=60)
    )
    factors = {f.key: f for f in inv.risk.factors}
    assert (
        "sanctioned_counterparty" in factors
        and "1,250,000.00 USDT" in factors["sanctioned_counterparty"].evidence[0]
    )
    names = {e.name for e in inv.entities}
    assert {"Northgate Maritime Holdings Ltd", "Volkov Exchange OÜ"} <= names
    assert any(row["sanctioned_party"] for row in inv.tables["crypto"])
    # Counterparties reached through flows are not expanded further (one hop of flows).
    otc = next(e for e in inv.entities if e.name.startswith("TQtcDesk"))
    assert not any(
        r.source_id == otc.id and r.type == RelationType.TRANSFER for r in inv.relationships
    )
