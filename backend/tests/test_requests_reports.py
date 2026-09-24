"""Documents to request (derived from findings) and report templates."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
BODY = {"record_ids": ["demo_intl_registry:lu/B198765"], "depth": 2, "max_nodes": 60}


@pytest.fixture(scope="module")
def inv():
    resp = client.post("/api/investigations", json=BODY)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_requests_follow_the_red_flags(inv):
    docs = {r["document"]: r for r in inv["requests"]}
    assert docs["Certified register extract (less than 3 months old)"]["priority"] == "required"
    assert any(
        d.startswith("Passport copy of Ruslan Terekhov") for d in docs
    )  # sanctions hit to confirm
    assert any("Source of wealth" in d for d in docs)  # PEP in the network
    assert any("group structure chart" in d.lower() for d in docs)  # circular ownership
    assert any("Northgate Maritime Holdings" in d for d in docs)  # offshore entity in the chain
    required = [r["priority"] for r in inv["requests"]]
    assert required == sorted(required, key=lambda p: p != "required")  # required first


@pytest.mark.parametrize("template", ["kyc", "edd", "review", "full"])
def test_report_templates(template):
    resp = client.post("/api/reports/pdf", json={**BODY, "template": template})
    assert resp.status_code == 200 and resp.content.startswith(b"%PDF")
    prefix = {"kyc": "kyc_", "edd": "edd_", "review": "periodic_review_", "full": "due_diligence_"}[
        template
    ]
    assert prefix in resp.headers["content-disposition"]


def test_unknown_template_rejected():
    assert client.post("/api/reports/pdf", json={**BODY, "template": "other"}).status_code == 422


@pytest.mark.parametrize("fiu", ["tracfin", "mros", "lu_crf"])
def test_sar_draft(fiu):
    resp = client.post("/api/reports/sar", json={**BODY, "fiu": fiu})
    assert resp.status_code == 200 and resp.content.startswith(b"%PDF")
    assert f"DRAFT_SAR_{fiu}_" in resp.headers["content-disposition"]
