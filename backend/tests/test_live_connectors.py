"""Real connectors, tested against mocked HTTP responses shaped like each API's documentation."""

import json
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from app.connectors.aleph import AlephConnector
from app.connectors.annuaire_fr import AnnuaireEntreprisesConnector
from app.connectors.companies_house import CompaniesHouseConnector
from app.connectors.icij import IcijReconcileConnector
from app.connectors.opencorporates import OpenCorporatesConnector
from app.connectors.opensanctions import OpenSanctionsConnector
from app.connectors.pappers import PappersConnector
from app.models import CompanyStatus, Entity, EntityType, ListType, RelationType
from app.settings import Settings

ICIJ_SCHEMA = "https://offshoreleaks.icij.org/schema/oldb"

KEYS = Settings(
    demo_mode=False,
    live_sources=True,
    pappers_api_key="pk",
    companies_house_api_key="ck",
    opencorporates_api_token="ok",
    opensanctions_api_key="sk",
    aleph_api_key="ak",
)


def person(name, dob=None, nat=()):
    return Entity(
        id=f"x:{name}", type=EntityType.PERSON, name=name, birth_date=dob, nationalities=list(nat)
    )


# ------------------------------------------------------------------ status
def test_missing_key_disables_connector_with_clear_message():
    conn = PappersConnector(Settings(live_sources=True, pappers_api_key=""))
    enabled, message = conn.status()
    assert not enabled and "PAPPERS_API_KEY" in message


def test_keyless_connectors_enabled_by_default():
    s = Settings(live_sources=True)
    assert AnnuaireEntreprisesConnector(s).enabled and IcijReconcileConnector(s).enabled
    assert not AnnuaireEntreprisesConnector(Settings(live_sources=False)).enabled


# ------------------------------------------------------ Annuaire (data.gouv)
ANNUAIRE = {
    "results": [
        {
            "siren": "552100554",
            "nom_complet": "ACME HOLDING (ACME)",
            "nom_raison_sociale": "ACME HOLDING",
            "sigle": "ACME",
            "nature_juridique": "5710",
            "date_creation": "2010-03-01",
            "etat_administratif": "A",
            "activite_principale": "64.20Z",
            "siege": {"adresse": "1 RUE DE LA PAIX 75002 PARIS"},
            "finances": {"2023": {"ca": 1200000, "resultat_net": 50000}},
            "dirigeants": [
                {
                    "nom": "DUPONT",
                    "prenoms": "JEAN MARC",
                    "date_de_naissance": "1970-04",
                    "qualite": "Président",
                    "nationalite": "Française",
                    "type_dirigeant": "personne physique",
                },
                {
                    "siren": "999888777",
                    "denomination": "AUDIT CONSEIL",
                    "qualite": "Commissaire aux comptes titulaire",
                    "type_dirigeant": "personne morale",
                },
            ],
        }
    ],
}


@respx.mock
def test_annuaire_company_officers_and_person_roles():
    respx.get("https://recherche-entreprises.api.gouv.fr/search").mock(
        return_value=httpx.Response(200, json=ANNUAIRE)
    )
    conn = AnnuaireEntreprisesConnector(KEYS)
    [company] = conn.search_company("acme")
    assert company.name == "ACME HOLDING" and company.legal_form == "SAS"
    assert company.registration_number == "552100554" and company.last_accounts_date.year == 2023
    assert (
        company.sources[0].url == "https://annuaire-entreprises.data.gouv.fr/entreprise/552100554"
    )

    officers = conn.get_officers(company.id)
    assert [o.entity.name for o in officers] == ["Jean Marc Dupont"]  # statutory auditor skipped
    assert officers[0].entity.birth_date == "1970-04" and officers[0].entity.nationalities == ["FR"]

    [p] = conn.search_person("Jean Marc Dupont")
    roles = conn.get_person_roles(p.id)
    assert [(r.entity.name, r.relationship.role) for r in roles] == [("ACME HOLDING", "Président")]


# --------------------------------------------------------------- Pappers
PAPPERS_PROFILE = {
    "siren": "552100554",
    "denomination": "ACME HOLDING",
    "forme_juridique": "SAS, société par actions simplifiée",
    "date_creation": "2010-03-01",
    "entreprise_cessee": False,
    "capital": 10000,
    "siege": {"adresse_ligne_1": "1 RUE DE LA PAIX", "code_postal": "75002", "ville": "PARIS"},
    "finances": [
        {
            "annee": 2023,
            "date_de_cloture_exercice": "2023-12-31",
            "chiffre_affaires": 1200000,
            "resultat": 50000,
        }
    ],
    "representants": [
        {
            "nom": "DUPONT",
            "prenom": "Jean",
            "qualite": "Président",
            "personne_morale": False,
            "date_de_naissance_formate": "04/1970",
            "nationalite": "Française",
            "actuel": True,
            "date_prise_de_poste": "2010-03-01",
        }
    ],
    "beneficiaires_effectifs": [
        {
            "nom": "DUPONT",
            "prenom": "Jean",
            "date_de_naissance_formate": "04/1970",
            "nationalite": "Française",
            "pourcentage_parts": 60,
            "pourcentage_votes": 60,
        }
    ],
}


@respx.mock
def test_pappers_beneficial_owners_and_accounts():
    route = respx.get("https://api.pappers.fr/v2/entreprise").mock(
        return_value=httpx.Response(200, json=PAPPERS_PROFILE)
    )
    conn = PappersConnector(KEYS)
    company = conn.get_company_details("pappers:552100554")
    assert company.last_accounts_date.isoformat() == "2023-12-31"
    assert route.calls[0].request.url.params["api_token"] == "pk"

    [ubo] = conn.get_shareholders("pappers:552100554")
    assert (
        ubo.relationship.type == RelationType.BENEFICIAL_OWNER and ubo.relationship.share_pct == 60
    )
    assert ubo.entity.birth_date == "1970-04"
    [officer] = conn.get_officers("pappers:552100554")
    assert officer.entity.id == ubo.entity.id  # same person key -> merged downstream


# ------------------------------------------------------- Companies House
CH_COMPANY = {
    "company_name": "ACME TRADING LIMITED",
    "company_number": "01234567",
    "company_status": "active",
    "date_of_creation": "2024-11-02",
    "type": "ltd",
    "registered_office_address": {
        "address_line_1": "1 High Street",
        "locality": "London",
        "postal_code": "EC1A 1AA",
    },
    "accounts": {"overdue": True},
}
CH_OFFICERS = {
    "items": [
        {
            "name": "SMITH, John Paul",
            "officer_role": "director",
            "appointed_on": "2024-11-02",
            "date_of_birth": {"month": 3, "year": 1975},
            "nationality": "British",
            "links": {"officer": {"appointments": "/officers/abc123/appointments"}},
        }
    ]
}
CH_PSC = {
    "items": [
        {
            "name": "Mr John Paul Smith",
            "kind": "individual-person-with-significant-control",
            "natures_of_control": [
                "ownership-of-shares-50-to-75-percent",
                "voting-rights-50-to-75-percent",
            ],
            "date_of_birth": {"month": 3, "year": 1975},
            "nationality": "British",
        }
    ]
}
CH_APPTS = {
    "name": "SMITH, John Paul",
    "date_of_birth": {"month": 3, "year": 1975},
    "items": [
        {
            "appointed_to": {
                "company_number": "01234567",
                "company_name": "ACME TRADING LIMITED",
                "company_status": "active",
            },
            "officer_role": "director",
            "appointed_on": "2024-11-02",
        },
        {
            "appointed_to": {
                "company_number": "07654321",
                "company_name": "OLD CO LTD",
                "company_status": "dissolved",
            },
            "officer_role": "secretary",
            "appointed_on": "2001-01-01",
            "resigned_on": "2005-01-01",
        },
    ],
}


@respx.mock
def test_companies_house_officers_psc_and_appointments():
    base = "https://api.company-information.service.gov.uk"
    respx.get(f"{base}/company/01234567").mock(return_value=httpx.Response(200, json=CH_COMPANY))
    respx.get(f"{base}/company/01234567/officers").mock(
        return_value=httpx.Response(200, json=CH_OFFICERS)
    )
    respx.get(f"{base}/company/01234567/persons-with-significant-control").mock(
        return_value=httpx.Response(200, json=CH_PSC)
    )
    respx.get(f"{base}/officers/abc123/appointments").mock(
        return_value=httpx.Response(200, json=CH_APPTS)
    )
    conn = CompaniesHouseConnector(KEYS)

    company = conn.get_company_details("companies_house:01234567")
    assert company.extra["accounts_overdue"] and company.jurisdiction == "GB"
    [officer] = conn.get_officers(company.id)
    assert officer.entity.name == "John Paul Smith" and officer.entity.birth_date == "1975-03"
    assert officer.entity.id == "companies_house:officer:abc123"
    [psc] = conn.get_shareholders(company.id)
    assert (
        psc.relationship.share_pct == 50.0
        and "ownership of shares 50 to 75 percent" in psc.relationship.role
    )

    roles = conn.get_person_roles(officer.entity.id)
    assert {r.entity.name for r in roles} == {"ACME TRADING LIMITED", "OLD CO LTD"}
    assert [r.relationship.end_date.year for r in roles if r.relationship.end_date] == [2005]
    auth = respx.calls[0].request.headers["Authorization"]
    assert auth.startswith("Basic ")


@respx.mock
def test_invalid_key_gives_readable_error():
    respx.get("https://api.company-information.service.gov.uk/company/1").mock(
        return_value=httpx.Response(401)
    )
    from app.connectors.base import ConnectorError

    with pytest.raises(ConnectorError, match="check the API key"):
        CompaniesHouseConnector(KEYS).get_company_details("companies_house:1")


# -------------------------------------------------------- OpenCorporates
@respx.mock
def test_opencorporates_company_and_officers():
    respx.get("https://api.opencorporates.com/v0.4/companies/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": {
                    "companies": [
                        {
                            "company": {
                                "name": "ACME OFFSHORE LTD",
                                "company_number": "1874412",
                                "jurisdiction_code": "vg",
                                "incorporation_date": "2012-09-17",
                                "current_status": "Active",
                                "opencorporates_url": "https://opencorporates.com/companies/vg/1874412",
                            }
                        }
                    ]
                }
            },
        )
    )
    respx.get("https://api.opencorporates.com/v0.4/companies/vg/1874412").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": {
                    "company": {
                        "name": "ACME OFFSHORE LTD",
                        "company_number": "1874412",
                        "jurisdiction_code": "vg",
                        "officers": [
                            {
                                "officer": {
                                    "id": 1,
                                    "name": "JANE DOE",
                                    "position": "director",
                                    "start_date": "2012-09-17",
                                }
                            }
                        ],
                    }
                }
            },
        )
    )
    conn = OpenCorporatesConnector(KEYS)
    [c] = conn.search_company("acme offshore")
    assert (
        c.jurisdiction == "VG"
        and c.id == "opencorporates:vg/1874412"
        and c.extra["accounts_unknown"]
    )
    [o] = conn.get_officers(c.id)
    assert o.entity.name == "JANE DOE" and o.relationship.role == "director"


# ----------------------------------------------------------- OpenSanctions
@respx.mock
def test_opensanctions_match_is_rescored_and_classified():
    route = respx.post("https://api.opensanctions.org/match/default").mock(
        return_value=httpx.Response(
            200,
            json={
                "responses": {
                    "q0": {
                        "results": [
                            {
                                "id": "Q123",
                                "caption": "Ivan Petrov",
                                "schema": "Person",
                                "score": 0.97,
                                "datasets": ["eu_fsf"],
                                "properties": {
                                    "name": ["Ivan Petrov", "Иван Петров"],
                                    "birthDate": ["1960-01-01"],
                                    "nationality": ["ru"],
                                    "topics": ["sanction"],
                                    "program": ["EU Regulation 269/2014"],
                                },
                            },
                            {
                                "id": "Q999",
                                "caption": "Ivan Petroff",
                                "schema": "Person",
                                "score": 0.7,
                                "datasets": ["peps"],
                                "properties": {
                                    "name": ["Ivan Petroff"],
                                    "birthDate": ["1990-05-05"],
                                    "topics": ["role.pep"],
                                },
                            },
                        ]
                    }
                }
            },
        )
    )
    hits = OpenSanctionsConnector(KEYS).screen_many([person("Ivan Petrov", "1960-01-01", ["RU"])])
    body = json.loads(route.calls[0].request.content)
    assert body["queries"]["q0"]["properties"]["birthDate"] == ["1960-01-01"]
    assert route.calls[0].request.headers["Authorization"] == "ApiKey sk"
    by_id = {h.provenance.record_id: h for h in hits}
    assert (
        by_id["opensanctions:Q123"].list_type == ListType.SANCTION
        and by_id["opensanctions:Q123"].score >= 95
    )
    assert (
        by_id["opensanctions:Q123"].provenance.url == "https://www.opensanctions.org/entities/Q123/"
    )
    # The PEP namesake has a conflicting date of birth: kept only as a low-confidence hit.
    assert "opensanctions:Q999" not in by_id or by_id["opensanctions:Q999"].score < 70


# ------------------------------------------------------------------- ICIJ
@respx.mock
def test_icij_reconcile_batches_and_attributes_the_leak():
    def reply(request):
        queries = json.loads(parse_qs(request.content.decode())["queries"][0])
        slug = request.url.path.rsplit("/", 1)[-1]
        result = {}
        for key, q in queries.items():
            found = []
            if slug == "panama-papers" and q["query"] == "Acme Offshore Ltd":
                # Shape copied from a real response of the ICIJ reconciliation API.
                entity_type = [{"id": f"{ICIJ_SCHEMA}/entity", "name": "Entity"}]
                found = [
                    {
                        "id": "10001",
                        "name": "ACME OFFSHORE LIMITED",
                        "score": 99,
                        "match": False,
                        "description": "Entity node extracted from the Panama Papers data.",
                        "types": entity_type,
                    },
                    {
                        "id": "10002",
                        "name": "ACME OFFSHORE GUATEMALA",
                        "score": 70,
                        "types": entity_type,
                    },
                    {
                        "id": "10003",
                        "name": "Acme Offshore Ltd",
                        "score": 99,
                        "types": [{"id": f"{ICIJ_SCHEMA}/address", "name": "Address"}],
                    },
                ]
            result[key] = {"result": found}
        return httpx.Response(200, json=result)

    route = respx.post(url__regex=r"https://offshoreleaks\.icij\.org/api/v1/reconcile/.*").mock(
        side_effect=reply
    )
    company = Entity(id="x:acme", type=EntityType.COMPANY, name="Acme Offshore Ltd")
    hits = IcijReconcileConnector(KEYS).screen_many([company, person("Nobody Here")])
    assert route.call_count == 5  # one batched request per investigation
    by_node = {h.provenance.url.rsplit("/", 1)[-1]: h for h in hits}
    assert set(by_node) == {"10001", "10002"}  # the Address node is filtered out by type
    hit = by_node["10001"]
    assert hit.dataset.startswith("Panama Papers") and hit.list_type == ListType.LEAK
    assert hit.details["node_type"] == "entity" and hit.score >= 85
    assert any("name-only" in e for e in hit.explanation)
    assert (
        by_node["10002"].score < 85
    )  # extra word: related but distinct node, kept as possible match


# ------------------------------------------------------------------ Aleph
@respx.mock
def test_aleph_skips_sanctions_and_labels_collections():
    respx.get("https://aleph.occrp.org/api/2/entities").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "a1",
                        "schema": "Person",
                        "properties": {"name": ["Ivan Petrov"]},
                        "collection": {"label": "Pandora Papers", "category": "leak"},
                        "links": {"ui": "https://aleph.occrp.org/entities/a1"},
                    },
                    {
                        "id": "a2",
                        "schema": "Person",
                        "properties": {"name": ["Ivan Petrov"]},
                        "collection": {"label": "EU sanctions", "category": "sanctions"},
                    },
                ]
            },
        )
    )
    [hit] = AlephConnector(KEYS).screen(person("Ivan Petrov"))
    assert hit.list_type == ListType.LEAK and hit.dataset.startswith("Pandora Papers")


# ------------------------------------------------------ realm separation
def test_demo_and_real_entities_never_merge():
    from app.graph.resolver import EntityResolver

    r = EntityResolver()
    a, _ = r.add(
        Entity(
            id="demo:1",
            type=EntityType.COMPANY,
            name="Acme",
            registration_number="1",
            jurisdiction="FR",
            demo=True,
        )
    )
    b, created = r.add(
        Entity(
            id="real:1",
            type=EntityType.COMPANY,
            name="Acme",
            registration_number="1",
            jurisdiction="FR",
        )
    )
    assert created and a != b


def test_status_mapping_companies_house_dissolved():
    e = CompaniesHouseConnector(KEYS)._company_from_profile(
        {"company_number": "1", "company_status": "dissolved"}
    )
    assert e.status == CompanyStatus.DISSOLVED
