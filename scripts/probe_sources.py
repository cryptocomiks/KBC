"""Temporary probe of African open sources (removed after use)."""

import httpx

H = {"User-Agent": "Mozilla/5.0 KYC1CLICK-probe/1.0 (compliance research)", "Accept": "application/json, text/html;q=0.9, */*;q=0.8"}
GETS = [
    ("NG CAC public search", "https://searchapp.cac.gov.ng/searchapp/api/public-search/company-business-name-it?searchTerm=Dangote"),
    ("NG CAC public search 2", "https://searchapp.cac.gov.ng/searchapp/api/public-search/company-business-name?searchTerm=Dangote"),
    ("NG CAC post", None),
    ("TN RNE", "https://www.registre-entreprises.tn/rne-api/public/registres/pm?denomination=Poulina&page=0&size=5"),
    ("TN RNE 2", "https://www.registre-entreprises.tn/rne-public/"),
    ("MU CBRD", "https://onlinesearch.mns.mu/"),
    ("RW RDB", "https://org.rdb.rw/api/search?query=MTN"),
    ("ZA CIPC bizportal", "https://bizportal.gov.za/api/enterprises/search?name=Sasol"),
    ("BW CIPA", "https://www.cipa.co.bw/ng-cipa-master/api/public/search?name=Debswana"),
    ("KenyaLaw peachjam", "https://new.kenyalaw.org/search/api/documents/?search=Safaricom&page_size=3"),
    ("SAFLII peachjam", "https://www.saflii.org/cgi-bin/sinosrch-adw.cgi?query=Steinhoff&results=5"),
    ("ULII peachjam", "https://ulii.org/search/api/documents/?search=Stanbic&page_size=3"),
    ("ZambiaLII", "https://zambialii.org/search/api/documents/?search=Zambeef&page_size=3"),
    ("GhaLII", "https://ghalii.org/search/api/documents/?search=Ashanti&page_size=3"),
    ("NigeriaLII", "https://nigerialii.org/search/api/documents/?search=Dangote&page_size=3"),
    ("AfricanLII", "https://africanlii.org/search/api/documents/?search=Glencore&page_size=3"),
    ("TanzLII", "https://tanzlii.org/search/api/documents/?search=Barrick&page_size=3"),
    ("NamibLII", "https://namiblii.org/search/api/documents/?search=Fishrot&page_size=3"),
    ("MalawiLII", "https://malawilii.org/search/api/documents/?search=Illovo&page_size=3"),
    ("ZimLII", "https://zimlii.org/search/api/documents/?search=Econet&page_size=3"),
    ("OS za_fic", "https://data.opensanctions.org/datasets/latest/za_fic_sanctions/index.json"),
    ("OS ng_nsl", "https://data.opensanctions.org/datasets/latest/ng_nsl_sanctions/index.json"),
    ("OS catalog africa", "https://data.opensanctions.org/datasets/latest/index.json"),
    ("Ghana ORC", "https://orc.gov.gh/"),
    ("Morocco OMPIC", "https://www.directinfo.ma/"),
    ("OpenOwnership", "https://register.openownership.org/"),
    ("BO data NG", "https://bods-data.openownership.org/"),
    ("Kenya Gazette", "https://new.kenyalaw.org/search/api/documents/?search=Safaricom&nature=Gazette&page_size=3"),
]

with httpx.Client(headers=H, timeout=40, follow_redirects=True) as c:
    for name, url in GETS:
        try:
            if url is None:
                r = c.post("https://searchapp.cac.gov.ng/searchapp/api/public-search/company-business-name-it", json={"searchTerm": "Dangote"})
            else:
                r = c.get(url)
            body = r.text
            if name == "OS catalog africa" and r.status_code == 200:
                ds = [d for d in r.json().get("datasets", []) if any(k in (d.get("name") or "") for k in ("za_", "ng_", "ke_", "gh_", "eg_", "ma_", "tn_", "dz_", "ci_", "sn_", "cm_", "ug_", "tz_", "rw_", "zw_", "zm_", "bw_", "na_", "mu_", "et_", "afdb", "african", "au_"))]
                body = "\n".join(f"{d['name']} | {d.get('title')} | {d.get('entity_count', d.get('target_count'))}" for d in ds)
                print(f"\n### {name}: {r.status_code}\n{body}")
                continue
            print(f"\n### {name}: {r.status_code} {r.headers.get('content-type','')} {len(r.content)}B final={r.url}")
            print(body[:600].replace("\n", " "))
        except Exception as e:  # noqa: BLE001
            print(f"\n### {name}: ERROR {type(e).__name__}: {e}")
