"""Legal basis of the red flags and justification texts."""

import app.risk.engine as engine
from app.legal import _data, justification, refs_for


def _labels():
    return next(v for v in vars(engine).values() if isinstance(v, dict) and "ubo_discrepancy" in v)


def test_every_risk_factor_and_statement_rule_has_a_legal_basis():
    signals = _data()["signals"]
    rules = {
        "structuring",
        "split_payments",
        "cash",
        "round_amounts",
        "pass_through",
        "high_risk_geography",
        "crypto",
        "activity_spike",
        "profile_mismatch",
        "funnel",
        "counterparty_screening",
    }
    assert set(_labels()) | rules <= set(signals)
    refs = _data()["refs"]
    for name, sig in signals.items():
        assert sig["refs"] and all(r in refs for r in sig["refs"]), name
        assert "{evidence}" in sig["en"] and "{evidence}" in sig["fr"], name


def test_justification_fills_the_evidence_and_cites_the_texts():
    fr = justification("pep_match", "Jane Doe, Minister of Finance", "fr")
    assert fr.startswith("Personne politiquement exposée (Jane Doe, Minister of Finance)")
    assert "Base légale : LBA art. 2a" in fr and "FATF R.12" in fr
    en = justification("sanctions_ownership", "X 60 %", "en")
    assert "OFAC 50 % rule" in en
    assert [r["jurisdiction"] for r in refs_for("structuring")][:2] == ["CH", "CH"]


def test_investigation_carries_the_legal_items(registry):
    from app.schemas import InvestigationRequest
    from app.service import KbcService

    svc = KbcService()
    c = svc.search("Northgate Maritime", "any").candidates[0]
    inv = svc.investigate(
        InvestigationRequest(record_ids=c.entity.record_ids, depth=2, max_nodes=60)
    )
    keys = {i["key"] for i in inv.legal}
    assert "sanctions_ownership" in keys and all(
        i["refs"] and i["en"] and i["fr"] for i in inv.legal
    )
