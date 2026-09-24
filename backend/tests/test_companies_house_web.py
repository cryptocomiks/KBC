import httpx
import respx

from app.connectors.companies_house_web import CompaniesHouseWebConnector
from app.models import EntityType
from app.settings import Settings

UI = "https://find-and-update.company-information.service.gov.uk"
LIVE = Settings(live_sources=True, companies_house_api_key="")

OFFICERS_HTML = """<html><body><div class="appointments-list">
<div class="appointment-1"><h2><span id="officer-name-1"> <a class="govuk-link" href="/officers/AAA111/appointments">TAYLOR, Christopher Jon</a> </span></h2>
<dl><dt>Role <span id="officer-status-tag-1">Active</span></dt><dd id="officer-role-1" class="data"> Secretary </dd></dl>
<dl><dt>Appointed on</dt><dd id="officer-appointed-on-1" class="data"> 14 April 2025 </dd></dl></div>
<div class="appointment-2"><h2><span id="officer-name-2"> <a class="govuk-link" href="/officers/BBB222/appointments">BETHELL, Melissa</a> </span></h2>
<dd id="officer-role-2" class="data"> Director </dd>
<dd id="officer-date-of-birth-2" class="data"> September 1974 </dd>
<dd id="officer-appointed-on-2" class="data"> 24 September 2018 </dd>
<dd id="officer-resigned-on-2" class="data"> 1 March 2024 </dd>
<dd id="officer-nationality-2" class="data"> British </dd></div>
<div class="appointment-3"><h2><span id="officer-name-3"> <a class="govuk-link" href="/officers/CCC333/appointments">OFFSHORE NOMINEES LIMITED</a> </span></h2>
<dd id="officer-role-3" class="data"> Corporate Director </dd></div>
</div></body></html>"""

APPOINTMENTS_HTML = """<html><head><title>Alisher Burkhanovich USMANOV personal appointments - Find and update company information - GOV.UK</title></head><body>
<dd id="officer-date-of-birth-value" class="data">September 1953</dd>
<div class="appointment-1"><h2 class="heading-medium" id="company-name-1"> <a href="/company/01816510">GNE GROUP LIMITED (01816510)</a> </h2>
<dd class="data" id="company-status-value-1"> Dissolved </dd>
<dd id="appointment-type-value1" class="data"> Director </dd>
<dd id="appointed-value1" class="data"> 31 January 2003 </dd>
<dd id="resigned-value-1" class="data"> 31 March 2006 </dd>
<dd id="nationality-value1" class="data"> Russian </dd></div>
</body></html>"""


@respx.mock
def test_search_json_and_overseas_entity():
    respx.get(f"{UI}/search/companies").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "title": "KEYA II LIMITED",
                        "company_number": "OE000001",
                        "company_type": "registered-overseas-entity",
                        "company_status": "registered",
                        "date_of_creation": "2022-08-03",
                        "external_registration_number": "132015",
                        "address_snippet": "Liberation House, Castle Street, St Helier, Jersey, JE1 2LH",
                        "links": {"self": "/company/OE000001"},
                    }
                ]
            },
        )
    )
    conn = CompaniesHouseWebConnector(LIVE)
    [oe] = conn.search_company("KEYA II")
    assert oe.extra["uk_overseas_entity"] and oe.jurisdiction is None
    assert oe.identifiers["Home registration number"] == "132015"
    docs = conn.get_documents(conn.get_company_details(oe.id))
    assert any("uk_property" in d.flags for d in docs)


@respx.mock
def test_officers_page_parsed():
    respx.get(f"{UI}/company/00445790/officers").mock(
        return_value=httpx.Response(200, text=OFFICERS_HTML)
    )
    links = CompaniesHouseWebConnector(LIVE).get_officers("companies_house_web:00445790")
    by_name = {link.entity.name: link for link in links}
    assert set(by_name) == {
        "Christopher Jon Taylor",
        "Melissa Bethell",
        "OFFSHORE NOMINEES LIMITED",
    }
    m = by_name["Melissa Bethell"]
    assert m.entity.birth_date == "1974-09" and m.entity.nationalities == ["GB"]
    assert m.relationship.role == "Director" and str(m.relationship.end_date) == "2024-03-01"
    assert str(by_name["Christopher Jon Taylor"].relationship.start_date) == "2025-04-14"
    assert by_name["OFFSHORE NOMINEES LIMITED"].entity.type == EntityType.COMPANY


@respx.mock
def test_officer_search_and_appointments():
    respx.get(f"{UI}/search/officers").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "title": "Alisher Burkhanovich USMANOV",
                        "date_of_birth": "September 1953",
                        "links": {"self": "/officers/SxlI/appointments"},
                        "address_snippet": "Moscow, Russia",
                    }
                ]
            },
        )
    )
    respx.get(f"{UI}/officers/SxlI/appointments").mock(
        return_value=httpx.Response(200, text=APPOINTMENTS_HTML)
    )
    conn = CompaniesHouseWebConnector(LIVE)
    [p] = conn.search_person("Alisher Usmanov")
    assert p.birth_date == "1953-09" and p.id == "companies_house_web:officer:SxlI"
    detail = conn.get_person_details(p.id)
    assert detail.name.lower() == "alisher burkhanovich usmanov" and detail.nationalities == ["RU"]
    [role] = conn.get_person_roles(p.id)
    assert role.entity.name == "GNE GROUP LIMITED" and role.entity.status.value == "dissolved"
    assert (
        str(role.relationship.start_date) == "2003-01-31"
        and str(role.relationship.end_date) == "2006-03-31"
    )


def test_switches_off_when_the_api_key_is_set():
    conn = CompaniesHouseWebConnector(Settings(live_sources=True, companies_house_api_key="k"))
    assert conn.enabled is False


PSC_HTML = """<div class="appointments-list">
<div class="appointment-1"><h2><span id="psc-statement-label-1"> Statement </span></h2><dd id="psc-statement-1" class="data"> All beneficial owners have been identified </dd></div>
<div class="appointment-2"><h2 class="heading-medium"> <span id="psc-name-2"> <span><b>David Jeremie Pralong</b></span> </span> <span id="psc-status-tag-2" class="status-tag">Active</span> </h2>
<dd id="psc-notified-on-2" class="data"> 4 July 2022 </dd><dd id="psc-date-of-birth-2" class="data"> June 1982 </dd><dd id="psc-nationality-2" class="data"> Swiss </dd>
<dd id="psc-noc-2-ownership-of-shares-more-than-25-percent-registered-overseas-entity" class="data"> Ownership of shares - More than 25% </dd>
<dd id="psc-noc-2-right-to-appoint-and-remove-directors-registered-overseas-entity" class="data"> Right to appoint or remove directors </dd></div>
<div class="appointment-3"><h2> <span id="psc-name-3"> <span><b>Monzo Bank Holding Group Limited</b></span> </span> </h2>
<dd id="psc-notified-on-3" class="data"> 12 September 2023 </dd><dd id="psc-ceased-on-3" class="data"> 11 February 2025 </dd>
<dd id="psc-legal-form-3" class="data"> Private Limited Company </dd><dd id="psc-registration-number-3" class="data"> 14785367 </dd>
<dd id="psc-country-registered-3" class="data"> England And Wales </dd>
<dd id="psc-noc-3-ownership-of-shares-75-to-100-percent" class="data"> Ownership of shares – 75% or more </dd></div>
</div>"""


@respx.mock
def test_psc_page_parsed_with_overseas_beneficial_owners():
    respx.get(f"{UI}/company/OE000001/persons-with-significant-control").mock(
        return_value=httpx.Response(200, text=PSC_HTML)
    )
    person, company = CompaniesHouseWebConnector(LIVE).get_shareholders(
        "companies_house_web:OE000001"
    )
    assert person.entity.name == "David Jeremie Pralong" and person.entity.nationalities == ["CH"]
    assert person.entity.birth_date == "1982-06" and person.relationship.share_pct == 25.0
    assert person.relationship.role.startswith("Registrable beneficial owner")
    assert (
        company.entity.type == EntityType.COMPANY
        and company.entity.id == "companies_house_web:14785367"
    )
    assert (
        company.relationship.share_pct == 75.0
        and str(company.relationship.end_date) == "2025-02-11"
    )
