from app.matching.matcher import match_entities, match_name
from app.models import Entity, EntityType


def person(name, dob=None, nat=()):
    return Entity(
        id=name, type=EntityType.PERSON, name=name, birth_date=dob, nationalities=list(nat)
    )


def company(name, reg=None, jur=None):
    return Entity(
        id=name, type=EntityType.COMPANY, name=name, registration_number=reg, jurisdiction=jur
    )


def test_same_dob_increases_confidence():
    base = match_entities(person("Mohamed Qadrany"), person("Mohammed Qadrany")).score
    with_dob = match_entities(
        person("Mohamed Qadrany", "1966-05-02"), person("Mohammed Qadrany", "1966-05-02")
    )
    assert with_dob.score >= base
    assert with_dob.signals["dob"] == "match"


def test_dob_conflict_penalises_homonyms():
    res = match_entities(
        person("Mohammed Qadrany", "1966-05-02", ["FR"]),
        person("Mohamed Kadrani", "1984-11", ["FR"]),
    )
    assert res.signals["dob"] == "conflict"
    assert res.score < 75
    assert any("date of birth conflict" in e for e in res.explanation)


def test_partial_dob_is_compatible():
    res = match_entities(person("A B", "1966-05-02"), person("A B", "1966-05"))
    assert res.signals["dob"] == "partial"


def test_registration_number_is_decisive():
    res = match_entities(
        company("Qadrany Investissements SAS", "900100101", "FR"),
        company("QADRANY INV.", "900 100 101", "FR"),
    )
    assert res.score == 100
    assert "registration number" in res.explanation[0]


def test_jurisdiction_conflict_penalised():
    same = match_entities(
        company("Acme Holdings", jur="LU"), company("Acme Holdings", jur="LU")
    ).score
    diff = match_entities(
        company("Acme Holdings", jur="LU"), company("Acme Holdings", jur="CY")
    ).score
    assert diff < same


def test_match_name_uses_aliases():
    ent = person("Ruslan Terekhov")
    ent.aliases = ["Руслан Терехов"]
    assert match_name("Руслан Терехов", ent).score >= 95
