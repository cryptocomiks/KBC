"""Temporary probe: response structures (removed after use)."""

import json
import time

import httpx

H = {"User-Agent": "KYC1CLICK-probe/1.0 compliance-research contact@example.org", "Accept": "application/json, */*;q=0.8"}


def keys(obj, depth=0, pre=""):
    if isinstance(obj, dict):
        for k, v in list(obj.items())[:40]:
            if isinstance(v, (dict, list)):
                print(f"{pre}{k}: {type(v).__name__}{'['+str(len(v))+']' if isinstance(v, list) else ''}")
                if depth < 2:
                    keys(v if isinstance(v, dict) else (v[0] if v else {}), depth + 1, pre + "  ")
            else:
                print(f"{pre}{k} = {str(v)[:80]!r}")


with httpx.Client(headers=H, timeout=60, follow_redirects=True) as c:
    print("##### RPO detail")
    r = c.get("https://api.statistics.sk/rpo/v1/search?fullName=Slovnaft&onlyActive=true").json()
    first = r["results"][0]
    keys(first)
    rid = first["id"]
    d = c.get(f"https://api.statistics.sk/rpo/v1/entity/{rid}?showHistoricalData=false&showOrganizationUnits=false")
    print("\n##### RPO entity", d.status_code)
    try:
        keys(d.json())
    except Exception:
        print(d.text[:500])
    print("\n##### EGRUL")
    t = c.post("https://egrul.nalog.ru/", data={"query": "Газпром нефть", "region": "", "PreventChromeAutocomplete": ""}).json()["t"]
    for _ in range(5):
        res = c.get(f"https://egrul.nalog.ru/search-result/{t}")
        if res.status_code == 200 and res.json().get("rows"):
            break
        time.sleep(1.5)
    print(res.status_code)
    data = res.json()
    keys(data)
    print(json.dumps(data.get("rows", [])[:2], ensure_ascii=False)[:1500])
    print("\n##### BrokerCheck firm detail")
    bc = c.get("https://api.brokercheck.finra.org/search/firm?query=Robinhood%20Securities&hl=true&nrows=3&start=0&r=25&wt=json").json()
    keys(bc["hits"]["hits"][0]["_source"])
    fid = bc["hits"]["hits"][0]["_source"]["firm_source_id"]
    det = c.get(f"https://api.brokercheck.finra.org/search/firm/{fid}?hl=true&nrows=12&query=&r=25&sort=bc_lastname_sort+asc,bc_firstname_sort+asc,bc_middlename_sort+asc,score+desc&wt=json")
    print("detail", det.status_code, det.text[:1500])
    print("\n##### RECAP docket")
    rc = c.get("https://www.courtlistener.com/api/rest/v4/search/?q=caseName%3A%22Glencore%22&type=r").json()
    keys(rc["results"][0])
    print("\n##### BrasilAPI")
    keys(c.get("https://brasilapi.com.br/api/cnpj/v1/33000167000101").json())
