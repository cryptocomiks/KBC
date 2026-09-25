"""One-off probe of financial regulators' registers (removed once the connectors are written)."""

import re

import httpx

UA = {"User-Agent": "KBC Corporate Mapping research-contact@kbc-mapping.org", "Accept": "application/json, text/html, */*"}
c = httpx.Client(headers=UA, timeout=40, follow_redirects=True)


def show(label, method, url, n=1800, **kw):
    print(f"\n===== {label}\n{method} {url} {kw.get('params') or ''}")
    try:
        r = c.request(method, url, **kw)
        t = re.sub(r"\s+", " ", r.text)
        print(f"status {r.status_code} · {r.headers.get('content-type')} · {len(r.content)} bytes")
        print(t[:n])
    except Exception as e:  # noqa: BLE001
        print("ERROR", repr(e))


# ESMA registers (Solr): MiFID firms, UCITS / AIF managers, MiCA crypto-asset service providers
for core in ("esma_registers_mifid_entities", "esma_registers_upreg", "esma_registers_casp", "esma_registers_mica_casp"):
    show(f"ESMA {core}", "GET", f"https://registers.esma.europa.eu/solr/{core}/select", params={"q": "*Binance*", "rows": 2, "wt": "json"})
show("ESMA mifid by name", "GET", "https://registers.esma.europa.eu/solr/esma_registers_mifid_entities/select", params={"q": 'ae_entityName:"UBS"', "rows": 2, "wt": "json"})
show("ESMA interim MiCA CSV page", "GET", "https://www.esma.europa.eu/esmas-activities/digital-finance-and-innovation/markets-crypto-assets-regulation-mica", n=1200)
# EBA payment / e-money institutions register (EUCLID)
show("EBA EUCLID search", "GET", "https://euclid.eba.europa.eu/register/api/search/entities", params={"t": "Revolut"})
show("EBA register page", "GET", "https://euclid.eba.europa.eu/register/pir/search", n=800)
# FINMA
show("FINMA authorised list page", "GET", "https://www.finma.ch/en/finma-public/authorised-institutions-individuals-and-products/", n=1500)
show("FINMA api search", "GET", "https://www.finma.ch/en/api/search/getresult", params={"query": "UBS", "Order": 4})
# CSSF Luxembourg
show("CSSF entities api", "GET", "https://edesk.apps.cssf.lu/search-entities/api/v1/entities", params={"name": "Amazon", "page": 0, "size": 3})
show("CSSF search page", "GET", "https://edesk.apps.cssf.lu/search-entities/search", params={"lng": "en", "q": "Amazon"}, n=1200)
# France: REGAFI (banks, payment institutions) and AMF GECO (asset managers, funds)
show("REGAFI search", "GET", "https://www.regafi.fr/spip.php", params={"page": "results", "type": "simple", "denomination": "Revolut", "lang": "en"}, n=1500)
show("AMF GECO api", "GET", "https://geco.amf-france.org/Bio/rech_opcvm.aspx", n=600)
show("ORIAS api", "GET", "https://www.orias.fr/search", n=600)
# UK FCA register (keyless public pages?)
show("FCA register search", "GET", "https://register.fca.org.uk/services/V0.1/Search", params={"q": "Revolut", "type": "firm"})
show("FCA register public page", "GET", "https://register.fca.org.uk/s/search", params={"q": "Revolut", "type": "Companies"}, n=600)
