"""Client documents: rule-based extraction (Kbis / UBO declaration) and comparison with registries."""

import io

from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.doc_reader import extract
from app.main import app

client = TestClient(app)

KBIS = """Greffe du Tribunal de Commerce de Paris
Extrait Kbis
IDENTIFICATION DE LA PERSONNE MORALE
Immatriculation au RCS, numéro 900 100 101 R.C.S. Paris
Dénomination : QADRANY INVESTISSEMENTS
Forme juridique : Société par actions simplifiée
Adresse du siège : 12 avenue Hoche 75008 Paris
GESTION, DIRECTION, ADMINISTRATION, CONTRÔLE, ASSOCIÉS OU MEMBRES
Président
Nom, prénoms : QADRANY Mohammed
Date et lieu de naissance : 02/05/1966 à Casablanca (Maroc)
Directeur général
Nom, prénoms : MARCHETTI Sofia
Date et lieu de naissance : 01/09/1971 à Milan (Italie)
"""

RBE = """Déclaration des bénéficiaires effectifs
Société : MERIDIAN CAPITAL HOLDINGS SARL
Bénéficiaire effectif n°1
Nom, prénoms : QADRANY Mohammed
Date de naissance : 02/05/1966
Détention indirecte de 30 % du capital
Bénéficiaire effectif n°2
Nom, prénoms : MARCHETTI Sofia
Date de naissance : 01/09/1971
Détention indirecte de 20 % du capital
"""


def _pdf(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in text.splitlines():
        c.drawString(40, y, line)
        y -= 16
    c.save()
    return buf.getvalue()


def test_kbis_extraction():
    ex = extract(KBIS)
    assert ex.kind == "kbis"
    assert (
        ex.company.name == "QADRANY INVESTISSEMENTS"
        and ex.company.registration_number == "900100101"
    )
    assert ex.company.address.startswith("12 avenue Hoche")
    roles = {(p.name, p.role) for p in ex.officers}
    assert ("QADRANY Mohammed", "President") in roles and ("MARCHETTI Sofia", "CEO") in roles


def test_ubo_declaration_extraction():
    ex = extract(RBE)
    assert ex.kind == "ubo"
    assert [(p.name, p.pct) for p in ex.owners] == [
        ("QADRANY Mohammed", 30.0),
        ("MARCHETTI Sofia", 20.0),
    ]


def test_pdf_upload_is_read_and_not_stored():
    resp = client.post(
        "/api/documents/extract", files={"file": ("kbis.pdf", _pdf(KBIS), "application/pdf")}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pages"] == 1 and body["company"]["registration_number"] == "900100101"
    assert len(body["officers"]) == 2


def test_scanned_document_is_reported():
    ex = extract("   ")
    assert ex.warnings and "scan" in ex.warnings[0]


def test_comparison_flags_undeclared_owner_and_percent_gap():
    ex = extract(RBE)
    resp = client.post(
        "/api/documents/compare",
        json={
            "record_ids": ["demo_intl_registry:lu/B198765"],
            "depth": 2,
            "max_nodes": 60,
            "company": ex.company.model_dump(),
            "owners": [o.model_dump() for o in ex.owners] + [{"name": "Jean Inconnu", "pct": 50}],
        },
    )
    assert resp.status_code == 200, resp.text
    rows = {(r["name"], r["status"]) for r in resp.json()["rows"]}
    assert ("Ruslan Terekhov", "missing_in_document") in rows  # 34 % computed, not declared
    assert ("Jean Inconnu", "missing_in_registry") in rows
    assert ("MARCHETTI Sofia", "match") in rows  # 20 % declared, 20.4 % computed
    assert ("QADRANY Mohammed", "match") in rows  # 30 % vs 30.6 %
