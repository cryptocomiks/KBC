"""Temporary probe of further free sources (removed after use)."""

import httpx

H = {"User-Agent": "KYC1CLICK-probe/1.0 compliance-research contact@example.org", "Accept": "application/json, */*;q=0.8"}
GETS = [
    ("US DOJ press releases", "https://www.justice.gov/api/v1/press_releases.json?keyword=Glencore&pagesize=3&sort=date&direction=DESC"),
    ("US DOJ search 2", "https://www.justice.gov/api/v1/press_releases.json?parameters[keyword]=Glencore&pagesize=3"),
    ("BR BrasilAPI CNPJ", "https://brasilapi.com.br/api/cnpj/v1/33000167000101"),
    ("BR minhareceita", "https://minhareceita.org/33000167000101"),
    ("SK RPO search", "https://api.statistics.sk/rpo/v1/search?fullName=Slovnaft"),
    ("SK RPO search2", "https://api.statistics.sk/rpo/v1/search?fullName=Slovnaft&onlyActive=true"),
    ("RU EGRUL", None),
    ("FINRA BrokerCheck firm", "https://api.brokercheck.finra.org/search/firm?query=Robinhood&hl=true&nrows=3&start=0&r=25&wt=json"),
    ("SEC EDGAR full text", "https://efts.sec.gov/LATEST/search-index?q=%22Wirecard%22&dateRange=custom&forms=8-K"),
    ("SEC EFTS", "https://efts.sec.gov/LATEST/search-index?q=%22Wirecard%22"),
    ("LT JAR bulk", "https://www.registrucentras.lt/aduomenys/?byla=JAR_IREGISTRUOTI.csv"),
    ("UK FCA warning list", "https://www.fca.org.uk/scamsmart/warning-list"),
    ("IOSCO I-SCAN", "https://www.iosco.org/i-scan/?subsection=i-scan"),
    ("DK CVR open", "http://distribution.virk.dk/cvr-permanent/virksomhed/_search"),
    ("NO Brreg roles", "https://data.brreg.no/enhetsregisteret/api/enheter/923609016/roller"),
    ("GE NAPR", "https://enreg.reestri.gov.ge/main.php?m=new_index"),
    ("EU sanctions map", "https://www.sanctionsmap.eu/api/v1/regime"),
    ("Interpol yellow", "https://ws-public.interpol.int/notices/v1/red?name=Smith&resultPerPage=2"),
    ("OFSI", "https://ofsistorage.blob.core.windows.net/publishlive/2022format/ConList.json"),
    ("CH SECO", "https://www.sesam.search.admin.ch/sesam-search-web/pages/downloadXmlGesamtliste.xhtml?lang=en&action=downloadXmlGesamtlisteAction"),
    ("US OpenFEC demo", "https://api.open.fec.gov/v1/names/candidates/?q=trump&api_key=DEMO_KEY"),
    ("World Bank projects contracts", "https://search.worldbank.org/api/v2/contractdata?format=json&supplier_name=Glencore&rows=3"),
    ("UN Global Market", "https://www.ungm.org/Public/Notice"),
    ("OCDS open contracting", "https://data.open-contracting.org/"),
    ("CourtListener RECAP dockets", "https://www.courtlistener.com/api/rest/v4/search/?q=%22Glencore%22&type=r"),
    ("EU Financial Transparency", "https://ec.europa.eu/budget/financial-transparency-system/api/"),
    ("EU FTS search", "https://ec.europa.eu/budget/financial-transparency-system/analysis.html"),
]

with httpx.Client(headers=H, timeout=40, follow_redirects=True) as c:
    for name, url in GETS:
        try:
            if url is None:
                r = c.post("https://egrul.nalog.ru/", data={"query": "Газпром", "region": "", "PreventChromeAutocomplete": ""})
            else:
                r = c.get(url)
            print(f"\n### {name}: {r.status_code} {r.headers.get('content-type','')} {len(r.content)}B final={r.url}")
            print(r.text[:500].replace("\n", " "))
        except Exception as e:  # noqa: BLE001
            print(f"\n### {name}: ERROR {type(e).__name__}: {e}")
