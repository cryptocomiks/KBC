import httpx
import respx

from app.connectors.rpvs import API, RpvsConnector
from app.identifiers import Identifier
from app.settings import Settings

LIVE = Settings(live_sources=True)
PARTNER = {
    "Id": 33216,
    "CisloVlozky": 28699,
    "PartneriVerejnehoSektora": [
        {
            "Id": 137929,
            "ObchodneMeno": "Messer Slovnaft s. r. o.",
            "Ico": "31335853",
            "PlatnostOd": "2019-11-05T00:00:00+01:00",
            "PlatnostDo": None,
        }
    ],
    "KonecniUzivateliaVyhod": [
        {
            "Id": 137931,
            "Meno": "Stefan Alexander",
            "Priezvisko": "Messer",
            "DatumNarodenia": "1955-01-20T00:00:00+01:00",
            "JeVerejnyCinitel": False,
            "ObchodneMeno": None,
            "PlatnostOd": "2019-11-05T00:00:00+01:00",
            "PlatnostDo": "2024-08-26T23:59:59.9+02:00",
        },
        {
            "Id": 300001,
            "Meno": "Jana",
            "Priezvisko": "Nová",
            "DatumNarodenia": "1970-02-03T00:00:00+01:00",
            "JeVerejnyCinitel": True,
            "ObchodneMeno": None,
            "PlatnostOd": "2024-08-27T00:00:00+02:00",
            "PlatnostDo": None,
        },
    ],
}


@respx.mock
def test_search_details_and_beneficial_owners():
    respx.get(f"{API}/PartneriVerejnehoSektora").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "Id": 137929,
                        "ObchodneMeno": "Messer Slovnaft s. r. o.",
                        "Ico": "31335853",
                        "PlatnostOd": "2019-11-05T00:00:00+01:00",
                        "PlatnostDo": None,
                        "Partner": {"Id": 33216},
                    }
                ]
            },
        )
    )
    respx.get(f"{API}/Partneri(33216)").mock(return_value=httpx.Response(200, json=PARTNER))
    conn = RpvsConnector(LIVE)
    [company] = conn.search_company("Slovnaft")
    assert company.id == "rpvs:33216" and company.registration_number == "31335853"
    assert conn.get_by_identifier(Identifier("registration", "31335853", "IČO")).id == "rpvs:33216"
    assert conn.get_company_details("rpvs:33216").name == "Messer Slovnaft s. r. o."
    past, current = conn.get_shareholders("rpvs:33216")
    assert past.entity.name == "Stefan Alexander Messer" and past.entity.birth_date == "1955-01-20"
    assert str(past.relationship.end_date) == "2024-08-26"
    assert current.relationship.end_date is None and "public official" in current.relationship.role
    assert current.entity.extra["public_official"] is True
