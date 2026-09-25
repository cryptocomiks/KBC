import httpx
import respx

from app.connectors.regulators import ESMA, REGAFI, RegulatorsConnector
from app.models import Entity, EntityType
from app.settings import Settings

LIVE = Settings(live_sources=True)


def company(name, **kw):
    return Entity(id=f"x:{name}", type=EntityType.COMPANY, name=name, **kw)


@respx.mock
def test_esma_and_regafi_authorisations():
    respx.get(ESMA).mock(
        return_value=httpx.Response(
            200,
            json={
                "response": {
                    "docs": [
                        {
                            "ae_entityName": "Revolut Securities Europe UAB",
                            "ae_entityTypeLabel": "Investment firm",
                            "ae_competentAuthority": "Bank of Lithuania (LSC)",
                            "ae_status": "Active",
                            "ae_authorisationNotificationDate": "2021-11-22T00:00:00Z",
                            "ae_homeMemberState": "LITHUANIA",
                            "ae_lei": "9845001DE7E84FF54124",
                        },
                        {"ae_entityName": "Revolutionary Capital SA", "ae_status": "Active"},
                    ]
                }
            },
        )
    )
    respx.get(REGAFI.format(ds="prd-banque-entites")).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "denomination": "Revolut Securities Europe UAB",
                        "type_entite": "Succursale passeport",
                        "categorie": ["Entreprise d'investissement"],
                        "siren": "917420077",
                        "approval_withdrawal_process": "True",
                    }
                ]
            },
        )
    )
    respx.get(REGAFI.format(ds="prd-assurance-entites")).mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    docs = RegulatorsConnector(LIVE).get_documents(company("Revolut Securities Europe UAB"))
    esma, regafi = docs
    assert (
        esma.title == "Investment firm — Bank of Lithuania (LSC) (active)"
        and "regulated" in esma.flags
    )
    assert str(esma.date) == "2021-11-22" and "LEI 9845001DE7E84FF54124" in esma.summary
    assert "authorisation_withdrawn" in regafi.flags and "ACPR" in regafi.title


def test_persons_are_never_queried():
    with respx.mock(assert_all_called=False) as router:
        route = router.get(url__startswith="https://")
        person = Entity(id="p", type=EntityType.PERSON, name="Jane Doe")
        assert RegulatorsConnector(LIVE).get_documents(person) == []
        assert not route.called
