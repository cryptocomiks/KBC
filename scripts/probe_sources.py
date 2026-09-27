"""Temporary probe: run the official EU, UK and Swiss sanctions loaders on the real files."""

import re
import resource
import sys
import time

sys.path.insert(0, "backend")
import httpx  # noqa: E402

from app.connectors import official_sanctions as osl  # noqa: E402
from app.models import Entity, EntityType  # noqa: E402

H = {"User-Agent": "KYC1CLICK-probe/1.0"}
raw = osl._download_bytes(osl.CH_XML, 120).decode("utf-8", "replace")
i = raw.find("<target ")
print("CH first target:", raw[i : i + 1500])
print("CH nationality tags:", sorted(set(re.findall(r"<(nationality[^>]{0,120})>", raw)))[:10])
print("CH tags:", sorted(set(re.findall(r"<([a-z-]+)[ >/]", raw)))[:120])
print("targets:", raw.count("<target "), "de-listed mods:", raw.count('modification-type="de-listed"'))
del raw

for loader in (osl._load_eu, osl._load_uk, osl._load_ch):
    idx = osl._Index()
    t = time.time()
    try:
        loader(idx, 120)
    except Exception as exc:  # noqa: BLE001
        print(loader.__name__, "ERROR", type(exc).__name__, exc)
        continue
    kinds = {}
    for e in idx.entries:
        kinds[e.type.value] = kinds.get(e.type.value, 0) + 1
    print(loader.__name__, len(idx.entries), kinds, f"{time.time() - t:.1f}s",
          "maxrss MB", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024)
    for q, typ in (("Vladimir Putin", EntityType.PERSON), ("Alexander Lukashenko", EntityType.PERSON),
                   ("Sergei Lavrov", EntityType.PERSON), ("Rosneft", EntityType.COMPANY),
                   ("Wagner Group", EntityType.COMPANY)):
        c = idx.candidates(Entity(id="q", type=typ, name=q))
        from app.matching.matcher import match_entities
        best = sorted(((match_entities(Entity(id="q", type=typ, name=q), e.entity).score, e) for e in c), key=lambda x: -x[0])[:1]
        for sc, e in best:
            en = e.entity
            print(f"   {q!r} -> {en.name!r} {sc} dob={en.birth_date} nat={en.nationalities} prog={e.program!r} url={e.url[:80]} aliases={en.aliases[:3]}")
