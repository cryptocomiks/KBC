"""KYC / AML-CFT questionnaire (vigilance level) and bulk import of client lists."""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import bulk_import
from app import store as store_mod
from app.main import app
from app.questionnaire import assess, clean, suggest
from app.settings import get_settings

client = TestClient(app)
PW = {"X-KBC-Password": "s3cret"}


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_PASSWORD", "s3cret")
    monkeypatch.setenv("CRON_SECRET", "cron-token")
    monkeypatch.setenv("STORE_PATH", str(tmp_path / "store.db"))
    monkeypatch.delenv("VERCEL", raising=False)
    get_settings.cache_clear()
    store_mod.reset_store()
    yield
    store_mod.reset_store()
    get_settings.cache_clear()


LOW = {
    "relationship": "one_off",
    "sector": "low",
    "structure": "simple",
    "ubo": "verified",
    "pep": "no",
    "countries": ["FR"],
    "channel": "face_to_face",
    "volume": "lt_150k",
    "cash": "none",
    "funds": "documented",
    "behaviour": "consistent",
}


# ------------------------------------------------------------ questionnaire
def test_low_risk_answers_give_simplified_vigilance():
    a = assess(LOW, {"risk_level": "low", "snapshot": {"factors": []}})
    assert a["level"] == "simplified"
    assert a["complete"] and a["review_months"] == 36


def test_ordinary_client_is_standard():
    a = assess({**LOW, "sector": "standard", "relationship": "ongoing"}, {"risk_level": "low"})
    assert a["level"] == "standard"


def test_pep_forces_enhanced_with_its_measures():
    a = assess({**LOW, "pep": "yes"}, {"risk_level": "low"})
    assert a["level"] == "enhanced"
    assert "politically exposed person" in a["triggers"]
    assert any("PEP" in m for m in a["measures"])
    assert a["review_months"] == 12


def test_fatf_blacklisted_country_forces_enhanced():
    a = assess({**LOW, "countries": ["FR", "KP"]}, {"risk_level": "low"})
    assert a["level"] == "enhanced"
    assert "high-risk third country" in a["triggers"]


def test_high_screening_and_sanctions_feed_the_level():
    case = {"risk_level": "high", "risk_score": 72, "snapshot": {"factors": ["sanctions_match"]}}
    a = assess(LOW, case)
    assert a["level"] == "enhanced"
    assert "sanctions match in the screening" in a["triggers"]
    assert any(r["item"] == "Automatic screening" for r in a["reasons"])


def test_points_add_up_to_enhanced():
    answers = {
        **LOW,
        "sector": "cash",
        "structure": "complex",
        "volume": "gt_10m",
        "funds": "partial",
    }
    assert assess(answers, {"risk_level": "low"})["level"] == "enhanced"


def test_pep_answer_inconsistent_with_screening_is_reported():
    a = assess(LOW, {"risk_level": "medium", "snapshot": {"factors": ["pep_match"]}})
    assert any(r["item"] == "Inconsistency" for r in a["reasons"])
    assert a["level"] != "simplified"


def test_missing_answers_are_listed_and_clean_drops_junk():
    assert assess({"pep": "no"}, {})["missing"]
    cleaned = clean({"pep": "maybe", "cash": "none", "countries": ["fr", "x", "CHE"], "hack": 1})
    assert cleaned == {"cash": "none", "countries": ["CH", "FR"]}


def test_suggestions_come_from_the_screening():
    s = suggest(
        {"countries": ["FR", "LU"], "snapshot": {"factors": ["pep_match", "long_ownership_chain"]}}
    )
    assert s == {"countries": ["FR", "LU"], "pep": "yes", "structure": "complex"}


def test_questionnaire_saved_on_a_case_and_printed_in_the_pdf():
    case = client.post(
        "/api/cases", json={"record_ids": ["demo_fr_registry:900100101"], "depth": 1}, headers=PW
    ).json()
    view = client.get(f"/api/cases/{case['id']}", headers=PW).json()
    assert view["questionnaire"]["assessment"] is None
    assert view["questionnaire"]["form"] and "countries" in view["questionnaire"]["suggested"]
    resp = client.put(
        f"/api/cases/{case['id']}/questionnaire",
        json={"answers": {**LOW, "pep": "yes"}, "author": "A. Analyst"},
        headers=PW,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["assessment"]["level"] == "enhanced"
    view = client.get(f"/api/cases/{case['id']}", headers=PW).json()
    assert view["questionnaire"]["answers"]["pep"] == "yes"
    pdf = client.post(
        "/api/reports/pdf",
        json={
            "record_ids": case["record_ids"],
            "depth": 1,
            "case_id": case["id"],
            "template": "kyc",
        },
        headers=PW,
    )
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert (
        client.put(f"/api/cases/{case['id']}/questionnaire", json={"answers": {}}).status_code
        == 401
    )


# ------------------------------------------------------------------ parsing
def _xlsx(rows):
    shared = sorted({c for r in rows for c in r if not c.isdigit()})
    idx = {s: i for i, s in enumerate(shared)}

    def cell(ref, v):
        if v.isdigit():
            return f'<c r="{ref}"><v>{v}</v></c>'
        return f'<c r="{ref}" t="s"><v>{idx[v]}</v></c>'

    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    sheet = "".join(
        f'<row r="{i + 1}">'
        + "".join(cell(f"{chr(65 + j)}{i + 1}", v) for j, v in enumerate(r) if v)
        + "</row>"
        for i, r in enumerate(rows)
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "xl/sharedStrings.xml",
            f"<sst {ns}>" + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>",
        )
        z.writestr(
            "xl/worksheets/sheet1.xml",
            f"<worksheet {ns}><sheetData>{sheet}</sheetData></worksheet>",
        )
    return buf.getvalue()


def test_parse_csv_with_french_headers_and_semicolons():
    data = "Raison sociale;SIREN;Pays;Code client\nQadrany Investissements;900100101;France;C-01\n;;;\nSCI Meridian;;FR;C-02\nSCI Meridian;;FR;C-03\n"
    rows, warnings = bulk_import.parse("clients.csv", data.encode("cp1252"))
    assert [r["query"] for r in rows] == ["900100101", "SCI Meridian"]
    assert rows[0]["country"] == "FR" and rows[0]["reference"] == "C-01"
    assert any("duplicate" in w for w in warnings)


def test_parse_csv_without_header_uses_first_column():
    rows, _ = bulk_import.parse("list.csv", b"Glencore plc\nNestle SA\n")
    assert [r["query"] for r in rows] == ["Glencore plc", "Nestle SA"]


def test_parse_xlsx():
    rows, _ = bulk_import.parse(
        "clients.xlsx", _xlsx([["Name", "LEI"], ["Acme SA", ""], ["", "529900T8BM49AURSDO55"]])
    )
    assert [r["query"] for r in rows] == ["Acme SA", "529900T8BM49AURSDO55"]


def test_parse_rejects_bad_files():
    with pytest.raises(bulk_import.ImportError_):
        bulk_import.parse("a.xls", b"...")
    with pytest.raises(bulk_import.ImportError_):
        bulk_import.parse("a.csv", b"\n\n")
    with pytest.raises(bulk_import.ImportError_):
        bulk_import.parse("a.xlsx", b"not a zip")


# ------------------------------------------------------------ import queue
def _upload(text: str, **form):
    return client.post(
        "/api/cases/import",
        files={"file": ("clients.csv", text.encode(), "text/csv")},
        data={"depth": "1", **form},
        headers=PW,
    )


def test_import_creates_pending_cases_and_processes_them_step_by_step():
    resp = _upload("name;siren\n;900100101\nZzzz Nothing Matches Qqq;\nMeridian;\n")
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 3 and resp.json()["remaining"] == 3

    board = client.get("/api/cases", headers=PW).json()
    assert board["imports"]["remaining"] == 3
    pending = next(c for c in board["cases"] if c["import_state"] == "pending")
    view = client.get(f"/api/cases/{pending['id']}", headers=PW).json()
    assert view["investigation"] is None
    assert client.post(f"/api/cases/{pending['id']}/refresh", headers=PW).status_code == 409

    states = []
    for _ in range(10):
        out = client.post("/api/cases/import/next", headers=PW).json()
        if out["step"] is None:
            break
        states.append(out["step"]["state"])
    assert "done" in states and "not_found" in states
    assert "ambiguous" in states  # "Meridian": two companies of that name, the analyst picks
    cases = {c["subject_name"]: c for c in client.get("/api/cases", headers=PW).json()["cases"]}
    done = cases["Qadrany Investissements SAS"]
    assert done["import_state"] == "" and done["risk_level"]
    assert done["import_info"]["reference"] == ""

    # Monitoring never touches cases still in the import queue.
    ambiguous_or_missing = [
        c for c in cases.values() if c["import_state"] in ("ambiguous", "not_found")
    ]
    assert ambiguous_or_missing


def test_analyst_resolves_an_ambiguous_line():
    _upload("name\nZzzz Nothing Matches Qqq\n")
    client.post("/api/cases/import/next", headers=PW)
    case = client.get("/api/cases", headers=PW).json()["cases"][0]
    assert case["import_state"] == "not_found"
    resp = client.post(
        f"/api/cases/{case['id']}/resolve",
        json={"record_ids": ["demo_fr_registry:900100202"]},
        headers=PW,
    )
    assert resp.json()["import_state"] == "resolved"
    out = client.post(f"/api/cases/import/next?case_id={case['id']}", headers=PW).json()
    assert out["step"]["state"] == "done" and out["remaining"] == 0
    assert client.get(f"/api/cases/{case['id']}", headers=PW).json()["investigation"]


def test_import_queue_accepts_the_cron_secret_and_needs_a_password_otherwise():
    assert client.post("/api/cases/import/next").status_code == 401
    ok = client.post("/api/cases/import/next", headers={"Authorization": "Bearer cron-token"})
    assert ok.status_code == 200 and ok.json()["step"] is None
    assert _upload("x").status_code == 200
    bad = client.post(
        "/api/cases/import",
        files={"file": ("x.xls", b"..", "application/vnd.ms-excel")},
        headers=PW,
    )
    assert bad.status_code == 422


def test_existing_database_gets_the_new_columns(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    old_schema = store_mod.SCHEMA[0].split(",\n        questionnaire")[0] + "\n    )"
    conn.execute(old_schema)
    conn.execute(
        "INSERT INTO cases (id, title, subject_name, subject_type, record_ids, depth, max_nodes, "
        "created_at, updated_at) VALUES ('old1', 'Old', 'Old SA', 'company', '[]', 2, 60, 'x', 'x')"
    )
    conn.commit()
    conn.close()
    store = store_mod.Store(None, str(path))
    case = store.get_case("old1")
    assert case["questionnaire"] == {} and case["import_state"] == ""
