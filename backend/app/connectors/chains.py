"""Public blockchain explorers (no API key): Bitcoin, Ethereum, TRON.

* Bitcoin — mempool.space REST API (address stats + recent transactions)
* Ethereum — Blockscout API v2 (ETH transfers + ERC-20 token transfers)
* TRON — TronGrid API (TRC-20 transfers, i.e. mostly USDT)

Each wallet's recent activity is aggregated per counterparty (one edge per
counterparty and currency, with total amount and number of transactions):
one hop of flows, as used for sanctions-exposure screening. Only the most
recent transactions returned by the free APIs are analysed — this is a
screening aid, not a full blockchain forensic trace.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any

from app.connectors.base import BaseConnector
from app.connectors.crypto_util import detect_chain, normalize_address, wallet_id
from app.models import Entity, EntityType, LinkedEntity, Relationship, RelationType

MAX_COUNTERPARTIES = 15


def _day(ts: float | int | str | None) -> date | None:
    if ts in (None, ""):
        return None
    try:
        if isinstance(ts, str):
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
        ts = float(ts)
        if ts > 1e12:  # milliseconds
            ts /= 1000
        return datetime.fromtimestamp(ts, UTC).date()
    except (ValueError, OSError):
        return None


class _Flow:
    def __init__(self) -> None:
        self.amount = 0.0
        self.count = 0
        self.first: date | None = None
        self.last: date | None = None

    def add(self, amount: float, day: date | None) -> None:
        self.amount += amount
        self.count += 1
        if day:
            self.first = min(self.first or day, day)
            self.last = max(self.last or day, day)


class ChainConnector(BaseConnector):
    kind = "chain"
    chain: str
    explorer: str  # URL template with {address}

    def handles(self, entity: Entity) -> bool:
        return entity.type == EntityType.WALLET and entity.chain == self.chain

    def wallet_entity(self, address: str, **extra: Any) -> Entity:
        # Same id whatever the source (explorer, sanctions list, demo): wallet:<chain>:<address>
        rid = wallet_id(self.chain, address)
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.WALLET,
            name=address,
            chain=self.chain,
            identifiers={f"{self.chain} address": address},
            sources=[self.provenance(rid, self.explorer.format(address=address))],
            extra={k: v for k, v in extra.items() if v not in (None, "")},
        )

    def _links(
        self, entity: Entity, flows: dict[tuple[str, str, str], _Flow]
    ) -> list[LinkedEntity]:
        """flows: (direction 'in'/'out', counterparty address, currency) -> _Flow."""
        ranked = sorted(flows.items(), key=lambda kv: (-kv[1].count, -kv[1].amount))[
            :MAX_COUNTERPARTIES
        ]
        me = wallet_id(self.chain, entity.name)
        out = []
        for (direction, other_addr, currency), flow in ranked:
            other = self.wallet_entity(other_addr)
            src, tgt = (other.id, me) if direction == "in" else (me, other.id)
            rel = Relationship(
                id=f"{self.name}:flow:{src}>{tgt}:{currency}",
                type=RelationType.TRANSFER,
                source_id=src,
                target_id=tgt,
                role=f"{flow.count} transfer(s)",
                amount=round(flow.amount, 8),
                currency=currency,
                tx_count=flow.count,
                start_date=flow.first,
                end_date=None,
                sources=[self.provenance(me, self.explorer.format(address=entity.name))],
            )
            rel.role = f"{flow.count} tx · {rel.amount:g} {currency}" + (
                f" · last {flow.last}" if flow.last else ""
            )
            out.append(LinkedEntity(relationship=rel, entity=other))
        return out


class BitcoinConnector(ChainConnector):
    name = "chain_btc"
    label = "Bitcoin — mempool.space explorer"
    chain = "BTC"
    homepage = "https://mempool.space"
    explorer = "https://mempool.space/address/{address}"
    api = "https://mempool.space/api"

    def get_wallet(self, address: str) -> Entity | None:
        if detect_chain(address) != "BTC":
            return None
        data = self.http_get_json(f"{self.api}/address/{address}")
        if not data:
            return None
        cs = data.get("chain_stats") or {}
        balance = (cs.get("funded_txo_sum", 0) - cs.get("spent_txo_sum", 0)) / 1e8
        return self.wallet_entity(
            address,
            balance=f"{balance:g} BTC",
            tx_count=cs.get("tx_count"),
            total_received=f"{cs.get('funded_txo_sum', 0) / 1e8:g} BTC",
        )

    def get_wallet_links(
        self, entity: Entity, include_transfers: bool = True
    ) -> list[LinkedEntity]:
        if not (self.handles(entity) and include_transfers):
            return []
        address = entity.name
        txs = self.http_get_json(f"{self.api}/address/{address}/txs") or []
        flows: dict[tuple[str, str, str], _Flow] = defaultdict(_Flow)
        for tx in txs:
            day = _day((tx.get("status") or {}).get("block_time"))
            inputs = [(v.get("prevout") or {}) for v in tx.get("vin", [])]
            spent = any(i.get("scriptpubkey_address") == address for i in inputs)
            if spent:
                for o in tx.get("vout", []):
                    to = o.get("scriptpubkey_address")
                    if to and to != address:
                        flows[("out", to, "BTC")].add(o.get("value", 0) / 1e8, day)
            else:
                received = sum(
                    o.get("value", 0)
                    for o in tx.get("vout", [])
                    if o.get("scriptpubkey_address") == address
                )
                total_in = sum(i.get("value", 0) for i in inputs) or 1
                for i in inputs:
                    frm = i.get("scriptpubkey_address")
                    if frm and frm != address:
                        flows[("in", frm, "BTC")].add(
                            received * i.get("value", 0) / total_in / 1e8, day
                        )
        return self._links(entity, flows)


class EthereumConnector(ChainConnector):
    name = "chain_eth"
    label = "Ethereum — Blockscout explorer (ETH + ERC-20)"
    chain = "ETH"
    homepage = "https://eth.blockscout.com"
    explorer = "https://eth.blockscout.com/address/{address}"
    api = "https://eth.blockscout.com/api/v2"

    def get_wallet(self, address: str) -> Entity | None:
        if detect_chain(address) != "ETH":
            return None
        data = self.http_get_json(f"{self.api}/addresses/{address}")
        if not data:
            return None
        counters = self.http_get_json(f"{self.api}/addresses/{address}/counters") or {}
        balance = int(data.get("coin_balance") or 0) / 1e18
        tags = [
            t.get("display_name") or t.get("label")
            for t in (data.get("public_tags") or [])
            if isinstance(t, dict)
        ]
        return self.wallet_entity(
            data.get("hash") or address,
            balance=f"{balance:.6g} ETH",
            tx_count=counters.get("transactions_count"),
            token_transfers=counters.get("token_transfers_count"),
            contract="yes" if data.get("is_contract") else None,
            label=data.get("name") or ", ".join(t for t in tags if t) or None,
        )

    def get_wallet_links(
        self, entity: Entity, include_transfers: bool = True
    ) -> list[LinkedEntity]:
        if not (self.handles(entity) and include_transfers):
            return []
        me = normalize_address(entity.name, "ETH")
        flows: dict[tuple[str, str, str], _Flow] = defaultdict(_Flow)

        def account(item: dict[str, Any], side: str) -> str:
            return (item.get(side) or {}).get("hash") or ""

        txs = self.http_get_json(f"{self.api}/addresses/{entity.name}/transactions") or {}
        for t in txs.get("items", []):
            value = int(t.get("value") or 0) / 1e18
            if value <= 0 or t.get("status") not in (None, "ok"):
                continue
            frm, to = account(t, "from"), account(t, "to")
            other, direction = (to, "out") if frm.lower() == me else (frm, "in")
            if other:
                flows[(direction, other, "ETH")].add(value, _day(t.get("timestamp")))
        tokens = (
            self.http_get_json(
                f"{self.api}/addresses/{entity.name}/token-transfers", params={"type": "ERC-20"}
            )
            or {}
        )
        for t in tokens.get("items", []):
            total, token = t.get("total") or {}, t.get("token") or {}
            decimals = int(total.get("decimals") or token.get("decimals") or 18)
            value = int(total.get("value") or 0) / 10**decimals
            frm, to = account(t, "from"), account(t, "to")
            other, direction = (to, "out") if frm.lower() == me else (frm, "in")
            if other and value > 0:
                flows[(direction, other, token.get("symbol") or "ERC20")].add(
                    value, _day(t.get("timestamp"))
                )
        return self._links(entity, flows)


class TronConnector(ChainConnector):
    name = "chain_tron"
    label = "TRON — TronGrid (TRC-20 / USDT transfers)"
    chain = "TRON"
    homepage = "https://tronscan.org"
    explorer = "https://tronscan.org/#/address/{address}"
    api = "https://api.trongrid.io/v1"

    def get_wallet(self, address: str) -> Entity | None:
        if detect_chain(address) != "TRON":
            return None
        data = (self.http_get_json(f"{self.api}/accounts/{address}") or {}).get("data") or []
        if not data:
            return self.wallet_entity(address, note="account not activated / no activity")
        acct = data[0]
        return self.wallet_entity(
            address,
            balance=f"{(acct.get('balance') or 0) / 1e6:g} TRX",
            created=str(_day(acct.get("create_time")) or ""),
            last_activity=str(_day(acct.get("latest_opration_time")) or ""),
        )

    def get_wallet_links(
        self, entity: Entity, include_transfers: bool = True
    ) -> list[LinkedEntity]:
        if not (self.handles(entity) and include_transfers):
            return []
        data = (
            self.http_get_json(
                f"{self.api}/accounts/{entity.name}/transactions/trc20",
                params={"limit": 50, "only_confirmed": "true"},
            )
            or {}
        )
        flows: dict[tuple[str, str, str], _Flow] = defaultdict(_Flow)
        for t in data.get("data", []):
            info = t.get("token_info") or {}
            value = int(t.get("value") or 0) / 10 ** int(info.get("decimals") or 6)
            frm, to = t.get("from") or "", t.get("to") or ""
            other, direction = (to, "out") if frm == entity.name else (frm, "in")
            if other and value > 0:
                flows[(direction, other, info.get("symbol") or "TRC20")].add(
                    value, _day(t.get("block_timestamp"))
                )
        return self._links(entity, flows)


CHAIN_CONNECTORS: list[type[BaseConnector]] = [BitcoinConnector, EthereumConnector, TronConnector]
