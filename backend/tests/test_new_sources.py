"""Latvian register, Polish KRS, GLEIF securities (ISINs), Israel crypto wallets, compact lists."""

import httpx
import respx

from app.connectors.europe_registries import KrsConnector, LatviaRegisterConnector
from app.connectors.gleif import GleifConnector
from app.connectors.official_sanctions import (
    IL_CRYPTO,
    ListedEntry,
    OfficialSanctionsConnector,
    _Index,
    _load_il_crypto,
)
from app.identifiers import Identifier
from app.models import Entity, EntityType, ListType
from app.settings import Settings

LIVE = Settings(live_sources=True)


@respx.mock
def test_latvia_search_and_identifier():
    row = {
        "regcode": 40003032065,
        "name": 'Akciju sabiedrība "Air Baltic Corporation"',
        "type_text": "Akciju sabiedrība",
        "regtype_text": "Komercreģistrs",
        "registered": "1995-08-28T00:00:00",
        "terminated": None,
        "address": "Lidosta Rīga, Mārupes nov.",
    }
    respx.get(url__startswith="https://data.gov.lv/dati/api/3/action/datastore_search").mock(
        return_value=httpx.Response(200, json={"result": {"records": [row]}})
    )
    conn = LatviaRegisterConnector(LIVE)
    [c] = conn.search_company("Air Baltic")
    assert c.registration_number == "40003032065" and c.jurisdiction == "LV"
    assert str(c.incorporation_date) == "1995-08-28"
    assert conn.get_by_identifier(Identifier("registration", "40003032065", "n")).name == c.name
    assert conn.get_by_identifier(Identifier("registration", "123", "n")) is None


@respx.mock
def test_krs_extract_by_number():
    odpis = {
        "odpis": {
            "naglowekA": {"dataRejestracjiWKRS": "11.06.2001", "dataOstatniegoWpisu": "27.08.2026"},
            "dane": {
                "dzial1": {
                    "danePodmiotu": {
                        "nazwa": "POLSKIE KOLEJE PAŃSTWOWE SPÓŁKA AKCYJNA",
                        "formaPrawna": "SPÓŁKA AKCYJNA",
                        "identyfikatory": {"nip": "5250000251", "regon": "00012680100000"},
                    },
                    "siedzibaIAdres": {
                        "adres": {
                            "ulica": "UL. SZCZĘŚLIWICKA",
                            "nrDomu": "62",
                            "kodPocztowy": "00-973",
                            "miejscowosc": "WARSZAWA",
                            "kraj": "POLSKA",
                        }
                    },
                }
            },
        }
    }
    respx.get(url__startswith="https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/0000019193").mock(
        return_value=httpx.Response(200, json=odpis)
    )
    c = KrsConnector(LIVE).get_by_identifier(Identifier("registration", "19193", "n"))
    assert c.name.startswith("POLSKIE KOLEJE") and c.identifiers["NIP"] == "5250000251"
    assert str(c.incorporation_date) == "2001-06-11" and "WARSZAWA" in c.address


@respx.mock
def test_gleif_lists_issued_securities():
    lei = "2138002658CPO9NBH955"
    respx.get(f"https://api.gleif.org/api/v1/lei-records/{lei}/isins").mock(
        return_value=httpx.Response(
            200,
            json={
                "meta": {"pagination": {"total": 2}},
                "data": [
                    {"attributes": {"isin": "JE00B4T3BW64"}},
                    {"attributes": {"isin": "US37827X1000"}},
                ],
            },
        )
    )
    e = Entity(id="g", type=EntityType.COMPANY, name="Glencore plc", identifiers={"LEI": lei})
    docs = GleifConnector(LIVE).get_documents(e)
    sec = next(d for d in docs if d.kind == "securities")
    assert (
        "2 ISIN" in sec.title and "JE00B4T3BW64" in sec.summary and "securities_issuer" in sec.flags
    )


@respx.mock
def test_israel_crypto_wallets_are_screened():
    csv_text = (
        '"id","schema","name","aliases","birth_date","countries","addresses","identifiers","sanctions","phones","emails","program_ids","dataset","first_seen","last_seen","last_change"\n'
        '"il-1","CryptoWallet","TWaertrZdpRJSbLv2G638UL5HCK6sKcZYy","","","","","","2025-10-23","","","","x","","",""\n'
        '"il-2","CryptoWallet","Cryptocurrency wallet","","","","","112604404","","","","","x","","",""\n'
    )
    respx.get(IL_CRYPTO).mock(return_value=httpx.Response(200, text=csv_text))
    respx.get(url__startswith="https://data.opensanctions.org/").mock(
        return_value=httpx.Response(404)
    )
    index = _Index()
    _load_il_crypto(index, 10)
    assert len(index.wallets) == 1 and not index.by_key
    conn = OfficialSanctionsConnector(LIVE)
    conn._index = lambda: index  # type: ignore[method-assign]
    wallet = Entity(
        id="w", type=EntityType.WALLET, name="TWaertrZdpRJSbLv2G638UL5HCK6sKcZYy", chain="TRON"
    )
    [hit] = conn.screen(wallet)
    assert hit.score == 100 and "Israel" in hit.dataset


def test_listed_entries_are_compact_but_complete():
    e = Entity(
        id="x:1",
        type=EntityType.PERSON,
        name="Jane Doe",
        aliases=["J. Doe"],
        birth_date="1970",
        nationalities=["FR"],
    )
    entry = ListedEntry(
        entity=e, dataset="PEP: France", url="u", details={"a": None}, list_type=ListType.PEP
    )
    assert entry.type == EntityType.PERSON and entry.names == ("Jane Doe", "J. Doe")
    rebuilt = entry.entity
    assert rebuilt.name == "Jane Doe" and rebuilt.nationalities == ["FR"] and entry.details == {}
    assert not hasattr(entry, "__dict__")
