"""Temporary probe of candidate sources (removed after use)."""

import json
import re

import httpx

H = {"User-Agent": "KYC1CLICK-probe/1.0 (compliance research)", "Accept": "*/*"}
LW = "https://cms.lobbywatch.ch/de/data/interface/v1/json"


def keys(obj, depth=0, pre=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                print(f"{pre}{k}: {type(v).__name__}{'['+str(len(v))+']' if isinstance(v, list) else ''}")
                if depth < 2:
                    keys(v if isinstance(v, dict) else (v[0] if v else {}), depth + 1, pre + "  ")
            else:
                print(f"{pre}{k} = {str(v)[:70]!r}")


with httpx.Client(headers=H, timeout=60, follow_redirects=True) as c:
    for url in (f"{LW}/table/organisation/aggregated/id/8765", f"{LW}/table/parlamentarier/aggregated/id/166"):
        d = c.get(url).json()
        print("\n#####", url)
        keys(d.get("data"))
    d = c.get("https://www.lobbyregister.bundestag.de/sucheJson?q=Siemens").json()
    print("\n##### lobbyregister first result")
    keys(d["results"][0])
    for name, page, base, pats in (
        ("eba", "https://euclid.eba.europa.eu/register/pir/search", "https://euclid.eba.europa.eu/register/", [r"/register/api"]),
        ("comp", "https://competition-cases.ec.europa.eu/search", "https://competition-cases.ec.europa.eu/", [r"services", r"search", r"environment"]),
    ):
        html = c.get(page).text
        for js in re.findall(r'src="([^"]*main[^"]*\.js)"', html):
            src = c.get(base + js).text
            for pat in pats:
                for m in list(re.finditer(pat, src))[:12]:
                    print(f"\n{name} ctx[{pat}]:", src[max(0, m.start() - 160): m.end() + 160].replace("\n", " "))
    pkg = c.get("https://data.gov.au/data/api/3/action/package_show?id=asic-banned-disqualified-per").json()
    csv = next(r["url"] for r in pkg["result"]["resources"] if r["format"] == "CSV")
    txt = c.get(csv).text
    print("\n##### asic", csv, len(txt))
    print("\n".join(txt.splitlines()[:4]))
    soap = """<?xml version="1.0" encoding="utf-8"?><soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:uid="http://www.uid.admin.ch/xmlns/uid-wse"><soapenv:Body><uid:GetByUID><uid:uid><uidOrganisationIdCategorie xmlns="http://www.ech.ch/xmlns/eCH-0097-f/2">CHE</uidOrganisationIdCategorie><uidOrganisationId xmlns="http://www.ech.ch/xmlns/eCH-0097-f/2">116281710</uidOrganisationId></uid:uid></uid:GetByUID></soapenv:Body></soapenv:Envelope>"""
    r = c.post("https://www.uid-wse.admin.ch/V3.0/PublicServices.svc", content=soap.encode(),
               headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": "http://www.uid.admin.ch/xmlns/uid-wse/IPublicServices/GetByUID"})
    print("\n##### uid getbyuid", r.status_code)
    print(r.text[:6000])
