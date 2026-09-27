"""Temporary probe (removed after use)."""
import sys
sys.path.insert(0, "backend")
import httpx

H = {"User-Agent": "KYC1Click/0.3 (+https://github.com/cryptocomiks/KBC)", "Accept": "application/json"}
with httpx.Client(headers=H, timeout=40, follow_redirects=True) as c:
    for u in ("https://cms.lobbywatch.ch/de/data/interface/v1/json/table/parlamentarier/flat/list/Pfister",
              "https://cms.lobbywatch.ch/de/data/interface/v1/json/table/organisation/flat/list/RUAG%20International%20Holding"):
        r = c.get(u)
        print("LW", r.status_code, r.headers.get("content-type"), r.text[:300])
    s = c.get("https://api.statistics.sk/rpo/v1/search", params={"fullName": "Slovnaft", "onlyActive": "false"}).json()
    for res in s["results"][:4]:
        fid = res["id"]
        d = c.get(f"https://api.statistics.sk/rpo/v1/entity/{fid}", params={"showHistoricalData": "false", "showOrganizationUnits": "false"})
        j = d.json() if d.status_code == 200 else {}
        print("RPO", fid, d.status_code, [n.get("value") for n in res.get("fullNames", [])][-1:], "term", res.get("termination"),
              "SB", [(b.get("personName", {}).get("formatedName"), b.get("validTo")) for b in j.get("statutoryBodies", [])][:3],
              "keys", list(j)[:25])
