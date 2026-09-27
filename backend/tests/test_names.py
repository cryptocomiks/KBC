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


# ------------------------------------------------ false-positive guards (generic words etc.)
def test_generic_company_words_do_not_make_a_match():
    from app.matching.names import name_similarity

    assert name_similarity("Meridian Capital Holdings", "Atlas Capital Holdings", "company")[0] < 60
    score, notes = name_similarity("Global Trading", "Meridian Global Trading", "company")
    assert score <= 68 and any("distinctive part is missing" in n for n in notes)
    score, notes = name_similarity("Global Trading Ltd", "Global Trading LLC", "company")
    assert score == 84 and any("generic name" in n for n in notes)  # possible, never strong
    # ...nor break one: the distinctive part is shared
    score, _ = name_similarity("Meridian", "Meridian Capital Holdings S.à r.l.", "company")
    assert 80 <= score < 85
    assert name_similarity("Medium Rare NV", "Medium Rare N.V.", "company")[0] == 100


def test_person_guards():
    from app.matching.names import name_similarity

    score, notes = name_similarity("Ali", "Ali Hassan", "person")
    assert score <= 68 and any("single-word name" in n for n in notes)
    score, _ = name_similarity("Ali Hassan", "Ali Hassan Salameh Tikriti", "person")
    assert score < 85  # two missing name parts: at most a possible match
    _, notes = name_similarity("John Smith", "John Smith", "person")
    assert any("very common name" in n for n in notes)
    assert name_similarity("Mohammed Qadrany", "Mohamed Qadrany", "person")[0] >= 95


def test_matcher_type_mismatch_and_common_name():
    from app.matching.matcher import match_entities
    from app.models import Entity, EntityType

    person = Entity(id="p", type=EntityType.PERSON, name="Victor Martin")
    company = Entity(id="c", type=EntityType.COMPANY, name="Victor Martin")
    assert match_entities(person, company).score <= 50
    smith = Entity(id="a", type=EntityType.PERSON, name="John Smith")
    listed = Entity(id="b", type=EntityType.PERSON, name="John Smith")
    assert match_entities(smith, listed).score == 95  # common name, no date of birth: -5
    dated = Entity(id="d", type=EntityType.PERSON, name="John Smith", birth_date="1970-01-01")
    same = Entity(id="e", type=EntityType.PERSON, name="John Smith", birth_date="1970-01-01")
    assert match_entities(dated, same).score == 100
