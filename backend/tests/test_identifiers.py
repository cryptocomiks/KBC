"""Search by company identifier: detection and exact lookup (no homonyms)."""

from app.identifiers import detect
from app.service import KbcService


def kinds(q):
    return [(i.kind, i.value) for i in detect(q)]


def test_detection():
    assert kinds("552 032 534") == [("siren", "552032534")]
    assert kinds("55203253400646") == [("siren", "552032534")]
    assert kinds("FR27552032534") == [("siren", "552032534")]
    assert kinds("CHE-105.909.036") == [("ch_uid", "CHE-105.909.036")]
    assert kinds("CHE105909036") == [("ch_uid", "CHE-105.909.036")]
    assert kinds("529900S21EQ1BO4ESM68") == [("lei", "529900S21EQ1BO4ESM68")]
    assert kinds("CIK 0001318605") == [("cik", "1318605")]
    assert kinds("SC123456") == [("uk_company", "SC123456")]
    assert kinds("Danone") == []


def test_exact_lookup_in_registries():
    res = KbcService().search("B198765")
    assert [c.entity.name for c in res.candidates] == ["Meridian Capital Holdings S.à r.l."]
    assert res.candidates[0].score == 100 and "exact identifier" in res.candidates[0].explanation[0]


def test_unknown_identifier_falls_back_to_names():
    res = KbcService().search("999999999")
    assert res.warnings and "No registry returned a company" in res.warnings[0]
