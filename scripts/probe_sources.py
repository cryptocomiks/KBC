"""One-off look at candidate leak / investigative datasets: availability and format."""

import csv
import io

import httpx

UA = {
    "User-Agent": "Mozilla/5.0 (compatible; KBC-corporate-mapping/0.1; +https://github.com/cryptocomiks/KBC)"
}
c = httpx.Client(timeout=60, follow_redirects=True, headers=UA)
OS = "https://data.opensanctions.org/datasets/latest/{d}/targets.simple.csv"

for d in (
    "ru_acf_bribetakers",
    "ua_war_sanctions",
    "ru_navalny35",
    "icij_offshoreleaks",
    "ext_cy_companies",
    "gb_coh_disqualified",
    "us_ofac_cons",
    "ua_nabc_sanctions",
    "ru_rupep",
    "occrp_russian_asset_tracker",
    "ext_ru_egrul",
    "everypolitician",
    "wd_oligarchs",
    "ann_graph_topics",
    "ext_gleif",
):
    try:
        r = c.get(OS.format(d=d))
        rows = list(csv.DictReader(io.StringIO(r.text))) if r.status_code == 200 else []
        print(f"\n== {d}: {r.status_code} rows={len(rows)}")
        for row in rows[:2]:
            print(
                {
                    k: row[k][:80]
                    for k in ("schema", "name", "countries", "sanctions", "dataset")
                    if k in row
                }
            )
    except Exception as e:  # noqa: BLE001
        print(f"\n== {d}: ERROR {e}")

for label, url in (
    ("opensanctions index", "https://data.opensanctions.org/datasets/latest/index.json"),
    ("occrp rat", "https://www.occrp.org/en/russianassettracker"),
    ("aleph collections", "https://aleph.occrp.org/api/2/collections?limit=5"),
    ("ddosecrets", "https://data.ddosecrets.com/"),
    ("offshore alert", "https://www.offshorealert.com/"),
):
    try:
        r = c.get(url)
        print(f"\n== {label}: {r.status_code} {r.headers.get('content-type')} len={len(r.content)}")
        if "index.json" in url and r.status_code == 200:
            data = r.json()
            names = [
                (x.get("name"), x.get("title"), x.get("target_count") or x.get("entity_count"))
                for x in data.get("datasets", [])
            ]
            keep = [
                n
                for n in names
                if any(
                    k in (n[0] or "")
                    for k in (
                        "leak",
                        "acf",
                        "war",
                        "navalny",
                        "occrp",
                        "icij",
                        "asset",
                        "oligarch",
                        "bribe",
                        "rupep",
                        "disqual",
                        "debar",
                        "crime",
                        "fraud",
                        "interpol",
                        "fbi",
                        "wanted",
                        "courts",
                        "panama",
                    )
                )
            ]
            for n in keep[:80]:
                print("  ", n)
        else:
            print(r.text[:400].replace("\n", " "))
    except Exception as e:  # noqa: BLE001
        print(f"\n== {label}: ERROR {e}")
