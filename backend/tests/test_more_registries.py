"""Slovak RPO, Russian EGRUL, Brazilian CNPJ (BrasilAPI), FINRA BrokerCheck, RECAP dockets,
and the identifiers they answer to. Answers mirror the real services (probed live)."""

import json

import httpx
import pytest
import respx

from app.connectors import more_registries as mr
from app.connectors.base import ConnectorError
from app.identifiers import detect
from app.models import CompanyStatus, Entity, EntityType, RelationType
from app.settings import Settings

LIVE = Settings(live_sources=True)


def _company(name, **kw):
    return Entity(id=f"x:{name}", type=EntityType.COMPANY, name=name, **kw)


def test_identifiers_cnpj_ogrn_inn():
    kinds = {i.kind for i in detect("33.000.167/0001-01")}
    assert "br_cnpj" in kinds  # also read as a SIRET: both registers are tried
    assert {i.kind for i in detect("1025501701686")} == {"ru_ogrn"}
    assert detect("INN 5504036333")[0].kind == "ru_inn"
    assert "br_cnpj" not in {i.kind for i in detect("33000167000102")}  # bad check digit


RPO_ENTITY = {
    "id": 346670,
    "identifiers": [{"value": "31385940", "validFrom": "1994-12-29"}],
    "fullNames": [
        {
            "value": "SLOVNAFT SERVIS spol. s r.o",
            "validFrom": "1994-12-29",
            "validTo": "2002-12-15",
        },
        {"value": "SENES, spol. s r.o.", "validFrom": "2002-12-16"},
    ],
    "addresses": [
        {
            "street": "Vlčie hrdlo",
            "buildingNumber": "1",
            "postalCodes": ["82410"],
            "municipality": {"value": "Bratislava"},
        }
    ],
    "legalForms": [
        {"value": {"value": "Spoločnosť s ručením obmedzeným"}, "validFrom": "1994-12-29"}
    ],
    "establishment": "1995-01-01",
    "statutoryBodies": [
        {
            "stakeholderType": {"value": "Konateľ"},
            "validFrom": "1996-04-25",
            "personName": {"formatedName": "Miroslav Kohút"},
        },
        {
            "stakeholderType": {"value": "Konateľ"},
            "validFrom": "1990-01-01",
            "validTo": "1996-01-01",
            "personName": {"formatedName": "Old Director"},
        },
    ],
    "stakeholders": [
        {
            "stakeholderType": {"value": "Spoločník"},
            "validFrom": "2022-06-21",
            "personName": {"formatedName": "Anna Vrtelová"},
        }
    ],
    "deposits": [{"personName": {"formatedName": "Anna Vrtelová"}, "amount": "995.82"}],
}


@respx.mock
def test_rpo_search_details_officers_and_partners():
    respx.get(url__startswith=f"{mr.RPO}/search").mock(
        return_value=httpx.Response(200, json={"results": [RPO_ENTITY]})
    )
    respx.get(url__startswith=f"{mr.RPO}/entity/346670").mock(
        return_value=httpx.Response(200, json=RPO_ENTITY)
    )
    conn = mr.RpoConnector(LIVE)
    [c] = conn.search_company("SENES spol. s r.o.")
    assert (c.registration_number, c.status, c.address) == (
        "31385940",
        CompanyStatus.ACTIVE,
        "Vlčie hrdlo 1, 82410 Bratislava",
    )
    assert c.aliases == ["SLOVNAFT SERVIS spol. s r.o"]
    links = conn.get_officers(c.id)
    assert [(lk.entity.name, lk.relationship.type) for lk in links] == [
        ("Miroslav Kohút", RelationType.OFFICER),
        ("Anna Vrtelová", RelationType.SHAREHOLDER),
    ]  # the former director is left out
    assert links[1].relationship.role == "Spoločník: deposit EUR 995.82"


@respx.mock
def test_egrul_legal_entities_only_with_director():
    post = respx.post(f"{mr.EGRUL}/").mock(
        return_value=httpx.Response(200, json={"t": "TOKEN", "captchaRequired": False})
    )
    respx.get(f"{mr.EGRUL}/search-result/TOKEN").mock(
        return_value=httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "c": 'ПАО "ГАЗПРОМ НЕФТЬ"',
                        "g": "ПРЕДСЕДАТЕЛЬ ПРАВЛЕНИЯ: Дюков Александр Валерьевич",
                        "i": "5504036333",
                        "k": "ul",
                        "n": 'ПУБЛИЧНОЕ АКЦИОНЕРНОЕ ОБЩЕСТВО "ГАЗПРОМ НЕФТЬ"',
                        "o": "1025501701686",
                        "r": "21.08.2002",
                        "rn": "Г.Санкт-Петербург",
                    },
                    {
                        "n": "ИП Иванов Иван",
                        "k": "fl",
                        "i": "770000000000",
                    },  # a private person: skipped
                ]
            },
        )
    )
    conn = mr.EgrulConnector(LIVE)
    found = conn.search_company("Gazprom Neft PJSC")
    assert "газпром" in dict(httpx.QueryParams(post.calls[0].request.content.decode()))["query"]
    assert len(found) == 1
    g = found[0]
    assert g.identifiers["INN"] == "5504036333" and g.registration_number == "1025501701686"
    assert g.incorporation_date.isoformat() == "2002-08-21" and g.jurisdiction == "RU"
    [director] = conn.get_officers(g.id)
    assert director.relationship.role == "Chairman of the management board (EGRUL)"
    assert director.entity.name == "Aleksandr Valer'evich Diukov".replace("'", "")


def test_latin_to_cyrillic_for_the_egrul_search():
    assert mr.to_cyrillic("Gazprom Neft PJSC") == "газпром нефт"
    assert mr.to_cyrillic("Rosneft Oil Company") == "роснефт оил"


@respx.mock
def test_brasilapi_company_and_partners_by_cnpj():
    respx.get(mr.BRASILAPI.format(cnpj="33000167000101")).mock(
        return_value=httpx.Response(
            200,
            json={
                "cnpj": "33000167000101",
                "razao_social": "PETROLEO BRASILEIRO S A PETROBRAS",
                "nome_fantasia": "PETROBRAS - EDISE",
                "natureza_juridica": "Sociedade de Economia Mista",
                "situacao_cadastral": 2,
                "data_inicio_atividade": "1966-09-28",
                "municipio": "RIO DE JANEIRO",
                "uf": "RJ",
                "logradouro": "REPUBLICA DO CHILE",
                "numero": "65",
                "qsa": [
                    {
                        "nome_socio": "ANGELICA GARCIA COBAS LAUREANO",
                        "qualificacao_socio": "Diretor",
                        "cnpj_cpf_do_socio": "***912137**",
                        "faixa_etaria": "Entre 71 a 80 anos",
                    },
                    {
                        "nome_socio": "UNIAO FEDERAL",
                        "qualificacao_socio": "Sócio",
                        "cnpj_cpf_do_socio": "00394460000141",
                    },
                ],
            },
        )
    )
    conn = mr.BrasilApiConnector(LIVE)
    [ident] = [i for i in detect("33.000.167/0001-01") if i.kind == "br_cnpj"]
    p = conn.get_by_identifier(ident)
    assert (
        p.name == "PETROLEO BRASILEIRO S A PETROBRAS"
        and p.registration_number == "33.000.167/0001-01"
    )
    assert p.status == CompanyStatus.ACTIVE and p.jurisdiction == "BR"
    links = conn.get_officers(p.id)
    assert [(lk.entity.type, lk.relationship.type, lk.relationship.role) for lk in links] == [
        (EntityType.PERSON, RelationType.OFFICER, "Director"),
        (EntityType.COMPANY, RelationType.SHAREHOLDER, "Partner"),
    ]


@respx.mock
def test_brokercheck_registration_and_disclosures():
    respx.get(mr.BROKERCHECK).mock(
        return_value=httpx.Response(
            200,
            json={
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "firm_source_id": "287900",
                                "firm_name": "ROBINHOOD SECURITIES, LLC",
                                "firm_scope": "ACTIVE",
                                "firm_bd_full_sec_number": "8-69916",
                            }
                        }
                    ]
                }
            },
        )
    )
    content = {
        "basicInformation": {
            "firmStatus": "Approved",
            "regulator": "SEC",
            "finraLastApprovalDate": "10/13/2017",
        },
        "disclosures": [
            {"disclosureType": "Regulatory Event", "disclosureCount": 2},
            {"disclosureType": "Arbitration", "disclosureCount": 4},
        ],
    }
    respx.get(f"{mr.BROKERCHECK}/287900").mock(
        return_value=httpx.Response(
            200, json={"hits": {"hits": [{"_source": {"content": json.dumps(content)}}]}}
        )
    )
    [doc] = mr.BrokerCheckConnector(LIVE).get_documents(
        _company("Robinhood Securities LLC", jurisdiction="US")
    )
    assert doc.flags == ["register_warning"] and doc.date.isoformat() == "2017-10-13"
    assert "Regulatory Event ×2, Arbitration ×4" in doc.summary
    assert (
        mr.BrokerCheckConnector(LIVE).get_documents(_company("Nestlé S.A.", jurisdiction="CH"))
        == []
    )


@respx.mock
def test_recap_dockets_keep_cases_where_the_company_is_a_party():
    respx.get(url__startswith=mr.RECAP).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "caseName": "Oscar v. Glencore Ltd",
                        "court": "District Court, Virgin Islands",
                        "docketNumber": "1:21-cv-00283",
                        "dateFiled": "2021-09-15",
                        "dateTerminated": "2022-04-14",
                        "docket_absolute_url": "/docket/60729331/oscar-v-glencore-ltd/",
                    },
                    {"caseName": "Smith v. Jones", "dateFiled": "2020-01-01"},
                ]
            },
        )
    )
    docs = mr.RecapDocketsConnector(LIVE).get_documents(_company("Glencore Ltd"))
    assert [d.title for d in docs] == ["Oscar v. Glencore Ltd"]
    assert docs[0].url == "https://www.courtlistener.com/docket/60729331/oscar-v-glencore-ltd/"
    assert "closed 2022-04-14" in docs[0].summary and docs[0].flags == ["court"]


@respx.mock
def test_connect_timeout_skips_the_source_for_the_rest_of_the_investigation():
    import pytest

    from app.connectors.base import ConnectorError

    route = respx.post(f"{mr.EGRUL}/").mock(side_effect=httpx.ConnectTimeout("timed out"))
    conn = mr.EgrulConnector(LIVE)
    with pytest.raises(ConnectorError, match="unreachable"):
        conn.search_company("Rosneft")
    with pytest.raises(ConnectorError, match="skipped for a few minutes"):
        conn.search_company("Lukoil")
    assert route.call_count == 1  # the second lookup does not wait for another timeout


@respx.mock
def test_egrul_waits_for_the_asynchronous_search_result(monkeypatch):
    monkeypatch.setattr(mr, "EGRUL_POLL_SECONDS", 0)
    respx.post(f"{mr.EGRUL}/").mock(return_value=httpx.Response(200, json={"t": "T2"}))
    row = {"c": 'ПАО "ГАЗПРОМ НЕФТЬ"', "k": "ul", "o": "1025501701686", "i": "5504036333"}
    result = respx.get(f"{mr.EGRUL}/search-result/T2").mock(
        side_effect=[
            httpx.Response(200, json={"status": "wait"}),
            httpx.Response(200, json={"rows": [row]}),
        ]
    )
    found = mr.EgrulConnector(LIVE).search_company("Gazprom Neft")
    assert result.call_count == 2 and found[0].registration_number == "1025501701686"


@respx.mock
def test_egrul_result_never_ready_is_reported(monkeypatch):
    monkeypatch.setattr(mr, "EGRUL_POLL_SECONDS", 0)
    respx.post(f"{mr.EGRUL}/").mock(return_value=httpx.Response(200, json={"t": "T3"}))
    respx.get(f"{mr.EGRUL}/search-result/T3").mock(
        return_value=httpx.Response(200, json={"status": "wait"})
    )
    with pytest.raises(ConnectorError, match="not ready"):
        mr.EgrulConnector(LIVE).search_company("Gazprom Neft")


@respx.mock
def test_egrul_tries_the_soft_sign_spelling(monkeypatch):
    """'Neft' is 'нефть' in Russian: the plain transliteration 'нефт' finds other companies."""
    monkeypatch.setattr(mr, "EGRUL_POLL_SECONDS", 0)

    def token(request):
        query = dict(httpx.QueryParams(request.content.decode()))["query"]
        return httpx.Response(200, json={"t": "SOFT" if query.endswith("нефть") else "HARD"})

    respx.post(f"{mr.EGRUL}/").mock(side_effect=token)
    respx.get(f"{mr.EGRUL}/search-result/HARD").mock(
        return_value=httpx.Response(200, json={"rows": [{"c": 'ООО "НЕФТ"', "k": "ul", "o": "1"}]})
    )
    respx.get(f"{mr.EGRUL}/search-result/SOFT").mock(
        return_value=httpx.Response(
            200, json={"rows": [{"c": 'ПАО "ГАЗПРОМ НЕФТЬ"', "k": "ul", "o": "1025501701686"}]}
        )
    )
    assert mr.cyrillic_variants("Gazprom Neft") == ["газпром нефт", "газпром нефть"]
    [found] = mr.EgrulConnector(LIVE).search_company("Gazprom Neft")
    assert found.registration_number == "1025501701686"


@respx.mock
def test_egrul_unexpected_answer_is_reported_not_silent():
    respx.post(f"{mr.EGRUL}/").mock(return_value=httpx.Response(200, json={"foo": 1}))
    with pytest.raises(ConnectorError, match="unexpected answer"):
        mr.EgrulConnector(LIVE).search_company("Gazprom Neft")
