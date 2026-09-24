import pytest

from app.matching.names import name_similarity, normalize_company, normalize_person


@pytest.mark.parametrize(
    "a,b",
    [
        ("Mohamed Qadrany", "Mohammed Qadrany"),
        ("Mohammed Qadrany", "Maxamed Qadraani"),
        ("Muhammad Qadrany", "Mohamed Kadrani"),
        ("Aleksandr Petrov", "Alexander Petrov"),
        ("Ruslan Terekhov", "Rouslan Terekhov"),
        ("Youssef Benali", "Yusuf Benali"),
    ],
)
def test_transliteration_variants_score_high(a, b):
    score, notes = name_similarity(a, b)
    assert score >= 90, (a, b, score, notes)


def test_variant_is_explained():
    _, notes = name_similarity("Mohamed Haddad", "Maxamed Haddad")
    assert any("transliteration" in n for n in notes)


def test_token_order_and_accents_are_ignored():
    assert name_similarity("Vukotić-Lazar Dragan", "Dragan Vukotic Lazar")[0] == 100


def test_different_surname_is_not_masked_by_common_first_name():
    close, _ = name_similarity("Mohammed Qadrany", "Mohammed Qadrany")
    other, _ = name_similarity("Mohammed Qadrany", "Mohammed Haddad")
    assert close == 100
    assert other < 75


def test_dissimilar_names():
    score, notes = name_similarity("Mohammed Qadrany", "Sofia Marchetti")
    assert score < 50
    assert notes == ["names are dissimilar"]


def test_company_legal_forms_removed():
    assert normalize_company("Meridian Capital Holdings S.à r.l.") == [
        "meridian",
        "capital",
        "holdings",
    ]
    assert name_similarity("Aurelia Trading Ltd", "AURELIA TRADING LIMITED", "company")[0] == 100


def test_person_noise_words_removed():
    assert normalize_person("Mr. Mohammed Al-Qadrany") == ["mohammed", "qadrany"]
