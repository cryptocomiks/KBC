"""French public company directory — API "Recherche d'entreprises" (data.gouv.fr).

Free, no API key: https://recherche-entreprises.api.gouv.fr/docs/
Provides legal units (SIREN), registered office, status, officers
("dirigeants", incl. partial date of birth and nationality) and published
financial years. Shareholders and beneficial owners are NOT published by
this API (see the Pappers connector for beneficial owners).
"""

from __future__ import annotations

from typing import Any

from app.connectors.base import BaseConnector
from app.connectors.util import nationality_iso, parse_date, person_name
from app.matching.names import name_similarity
from app.models import CompanyStatus, Entity, EntityType, LinkedEntity, Relationship, RelationType

API = "https://recherche-entreprises.api.gouv.fr/search"
UI = "https://annuaire-entreprises.data.gouv.fr/entreprise/{siren}"
PERSON_MATCH_MIN = 85

# INSEE "catégorie juridique" codes -> readable legal form (most frequent ones)
LEGAL_FORMS = {
    "1000": "Entrepreneur individuel",
    "5202": "SNC",
    "5308": "SCA",
    "5306": "SCS",
    "5410": "SARL nationale",
    "5498": "EURL",
    "5499": "SARL",
    "5505": "SA à conseil d'administration",
    "5510": "SA à conseil d'administration",
    "5599": "SA à conseil d'administration",
    "5699": "SA à directoire",
    "5710": "SAS",
    "5720": "SASU",
    "6540": "SCI",
    "6599": "Société civile",
    "9220": "Association déclarée",
}
# Statutory auditors are not control relationships: skipped to reduce noise.
SKIPPED_ROLES = ("commissaire aux comptes",)


class AnnuaireEntreprisesConnector(BaseConnector):
    name = "annuaire_fr"
    label = "Annuaire des Entreprises — data.gouv.fr (FR)"
    kind = "registry"
    jurisdictions = {"FR"}
    homepage = "https://annuaire-entreprises.data.gouv.fr"

    # ----------------------------------------------------------- helpers
    def _search(self, **params: Any) -> list[dict[str, Any]]:
        data = self.http_get_json(API, params={"per_page": 10, "page": 1, **params})
        return (data or {}).get("results", [])

    def _company(self, r: dict[str, Any]) -> Entity:
        siren = r["siren"]
        rid = self.record_id(siren)
        siege = r.get("siege") or {}
        closed = r.get("etat_administratif") == "C"
        finances = r.get("finances") or {}
        years = sorted((y for y in finances if str(y).isdigit()), reverse=True)
        extra: dict[str, Any] = {}
        if years:
            last = finances[years[0]] or {}
            extra["latest_financial_year"] = years[0]
            if last.get("ca") is not None:
                extra["revenue_eur"] = f"{last['ca']:,}"
            if last.get("resultat_net") is not None:
                extra["net_income_eur"] = f"{last['resultat_net']:,}"
            extra["financials"] = [
                {
                    "year": y,
                    "revenue": f"{(finances[y] or {})['ca']:,}"
                    if (finances[y] or {}).get("ca") is not None
                    else None,
                    "net_income": f"{(finances[y] or {})['resultat_net']:,}"
                    if (finances[y] or {}).get("resultat_net") is not None
                    else None,
                    "currency": "EUR",
                    "source": "Filed accounts (INPI, via Annuaire des Entreprises)",
                }
                for y in years[:5]
            ]
        else:
            # Many small French companies legally opt out of publishing accounts:
            # absence here is not evidence of non-filing.
            extra["accounts_unknown"] = True
        if r.get("tranche_effectif_salarie"):
            extra["headcount_band"] = r["tranche_effectif_salarie"]
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=r.get("nom_raison_sociale") or r.get("nom_complet") or siren,
            aliases=[
                a
                for a in {r.get("nom_complet"), r.get("sigle")}
                if a and a != r.get("nom_raison_sociale")
            ],
            jurisdiction="FR",
            registration_number=siren,
            legal_form=LEGAL_FORMS.get(str(r.get("nature_juridique")), r.get("nature_juridique")),
            status=CompanyStatus.DISSOLVED if closed else CompanyStatus.ACTIVE,
            incorporation_date=parse_date(r.get("date_creation")),
            dissolution_date=parse_date(r.get("date_fermeture")) if closed else None,
            last_accounts_date=parse_date(f"{years[0]}-12-31") if years else None,
            activity=r.get("activite_principale") or siege.get("activite_principale"),
            address=siege.get("adresse") or siege.get("geo_adresse"),
            identifiers={"SIREN": siren},
            sources=[self.provenance(rid, UI.format(siren=siren))],
            extra=extra,
        )

    @staticmethod
    def _person_key(d: dict[str, Any]) -> str:
        return "|".join(
            [
                (d.get("nom") or "").upper(),
                (d.get("prenoms") or "").upper(),
                d.get("date_de_naissance") or d.get("annee_de_naissance") or "",
            ]
        )

    def _person(self, d: dict[str, Any], siren: str | None = None) -> Entity:
        rid = self.record_id(f"p:{self._person_key(d)}")
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.PERSON,
            name=person_name(d.get("prenoms"), d.get("nom")),
            birth_date=d.get("date_de_naissance") or d.get("annee_de_naissance"),
            nationalities=nationality_iso(d.get("nationalite")),
            sources=[self.provenance(rid, UI.format(siren=siren) if siren else None)],
        )

    def _officer_links(self, r: dict[str, Any]) -> list[LinkedEntity]:
        company = self._company(r)
        out = []
        for i, d in enumerate(r.get("dirigeants") or []):
            role = d.get("qualite") or ""
            if any(s in role.lower() for s in SKIPPED_ROLES):
                continue
            if d.get("type_dirigeant") == "personne morale":
                if not d.get("siren"):
                    continue
                rid = self.record_id(d["siren"])
                other = Entity(
                    id=rid,
                    record_ids=[rid],
                    type=EntityType.COMPANY,
                    name=d.get("denomination") or d["siren"],
                    jurisdiction="FR",
                    registration_number=d["siren"],
                    sources=[self.provenance(rid, UI.format(siren=d["siren"]))],
                )
            else:
                other = self._person(d, r["siren"])
            rel = Relationship(
                id=f"{self.name}:off:{r['siren']}:{i}",
                type=RelationType.OFFICER,
                source_id=other.id,
                target_id=company.id,
                role=role or None,
                sources=[self.provenance(company.id, UI.format(siren=r["siren"]) + "#dirigeants")],
            )
            out.append(LinkedEntity(relationship=rel, entity=other))
        return out

    # --------------------------------------------------------- interface
    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        return [self._company(r) for r in self._search(q=name)]

    def get_by_identifier(self, ident: Any) -> Entity | None:
        return (
            self.get_company_details(self.record_id(ident.value)) if ident.kind == "siren" else None
        )

    def get_company_details(self, company_id: str) -> Entity | None:
        siren = self.native_id(company_id)
        if siren.startswith("p:"):
            return None
        hits = [r for r in self._search(q=siren) if r.get("siren") == siren]
        return self._company(hits[0]) if hits else None

    def get_officers(self, company_id: str) -> list[LinkedEntity]:
        siren = self.native_id(company_id)
        hits = [r for r in self._search(q=siren) if r.get("siren") == siren]
        return self._officer_links(hits[0]) if hits else []

    def search_person(self, name: str, **filters: Any) -> list[Entity]:
        people: dict[str, Entity] = {}
        for r in self._search(q=name, type_personne="dirigeant"):
            for d in r.get("dirigeants") or []:
                if d.get("type_dirigeant") == "personne morale":
                    continue
                full = person_name(d.get("prenoms"), d.get("nom"))
                if name_similarity(name, full)[0] < PERSON_MATCH_MIN:
                    continue
                person = self._person(d, r["siren"])
                people.setdefault(person.id, person)
        return list(people.values())

    def get_person_details(self, person_id: str) -> Entity | None:
        key = self.native_id(person_id)
        if not key.startswith("p:"):
            return None
        nom, prenoms, dob = (key[2:].split("|") + ["", "", ""])[:3]
        rid = self.record_id(key)
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.PERSON,
            name=person_name(prenoms, nom),
            birth_date=dob or None,
            sources=[self.provenance(rid, None)],
        )

    def get_person_roles(self, person_id: str) -> list[LinkedEntity]:
        key = self.native_id(person_id)
        if not key.startswith("p:"):
            return []
        nom, prenoms, _dob = (key[2:].split("|") + ["", "", ""])[:3]
        params: dict[str, Any] = {
            "q": f"{prenoms} {nom}".strip(),
            "type_personne": "dirigeant",
            "nom_personne": nom,
        }
        if prenoms:
            params["prenoms_personne"] = prenoms.split()[0]
        out = []
        for r in self._search(**params):
            company = self._company(r)
            for link in self._officer_links(r):
                if link.entity.id != self.record_id(key):
                    continue
                rel = link.relationship
                out.append(LinkedEntity(relationship=rel, entity=company))
        return out
