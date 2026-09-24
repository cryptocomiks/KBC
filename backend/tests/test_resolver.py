from app.graph.resolver import EntityResolver, address_entity
from app.models import Entity, EntityType, Provenance


def rec(rid, name, **kw):
    return Entity(
        id=rid,
        record_ids=[rid],
        type=kw.pop("type", EntityType.PERSON),
        name=name,
        sources=[
            Provenance(source=rid.split(":")[0], source_label=rid.split(":")[0], record_id=rid)
        ],
        **kw,
    )


def test_persons_merged_with_compatible_dob_and_provenance_kept():
    r = EntityResolver()
    a, _ = r.add(rec("src1:1", "Mohammed Qadrany", birth_date="1966-05-02", nationalities=["FR"]))
    b, created = r.add(rec("src2:9", "Mohamed Qadrani", birth_date="1966-05", nationalities=["FR"]))
    assert a == b and not created
    ent = r.entities[a]
    assert ent.record_ids == ["src1:1", "src2:9"]
    assert {p.source for p in ent.sources} == {"src1", "src2"}
    assert "Mohamed Qadrani" in ent.aliases
    assert ent.birth_date == "1966-05-02"  # most precise value kept
    assert r.merges and r.merges[0]["merged_record"] == "src2:9"


def test_homonyms_are_not_merged():
    r = EntityResolver()
    r.add(rec("s:1", "Mohammed Qadrany", birth_date="1966-05-02"))
    _, created = r.add(rec("s:2", "Mohamed Kadrani", birth_date="1984-11"))
    assert created


def test_persons_without_dob_never_merged_on_name_alone():
    r = EntityResolver()
    r.add(rec("s:1", "Jean Martin"))
    _, created = r.add(rec("t:1", "Jean Martin"))
    assert created


def test_companies_merged_on_registration_number():
    r = EntityResolver()
    a, _ = r.add(
        rec(
            "fr:1",
            "Qadrany Investissements SAS",
            type=EntityType.COMPANY,
            registration_number="900100101",
            jurisdiction="FR",
        )
    )
    b, _ = r.add(
        rec(
            "oc:1",
            "QADRANY INVESTISSEMENTS",
            type=EntityType.COMPANY,
            registration_number="900 100 101",
            jurisdiction="FR",
            legal_form="SAS",
        )
    )
    assert a == b
    assert r.entities[a].legal_form == "SAS"  # missing attribute filled from the other source


def test_addresses_merged_despite_formatting():
    r = EntityResolver()
    a, _ = r.add(address_entity("22 rue Hélène-Vasseur, 75008 Paris, France"))
    b, _ = r.add(address_entity("22 RUE HELENE VASSEUR 75008 PARIS"))
    assert a == b
