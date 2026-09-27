"""Regression guard on the labelled matching test set (config/matching_testset.json)."""

from app.validation import run_validation, to_markdown


def test_matching_validation_meets_the_published_rates():
    report = run_validation()
    o = report["overall"]
    assert o["pairs"] >= 90
    # published in docs/validation/matching_report.md: a change that lowers these must be justified
    assert o["detection_rate"] >= 98.0, report["errors"]
    assert o["false_positive_rate"] <= 5.0, report["errors"]
    md = to_markdown(report)
    assert "Detection rate" in md and "False-positive rate" in md


def test_every_category_is_reported():
    report = run_validation()
    cats = {c["category"] for c in report["categories"]}
    assert {
        "Transliteration / middle names",
        "Namesakes, different date of birth",
        "Generic company words only",
    } <= cats
