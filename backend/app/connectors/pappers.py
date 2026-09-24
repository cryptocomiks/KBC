"""Pappers (France) — companies, officers, beneficial owners, filed accounts.

API: https://www.pappers.fr/api/documentation (key: PAPPERS_API_KEY; each
call consumes credits). Richer than the public directory: declared
beneficial owners with ownership percentages, officers' nationality and
the closing date of each filed financial year.
"""

from __future__ import annotations

from typing import Any

from app.connectors.base import BaseConnector
from app.connectors.util import flexible_date, nationality_iso, parse_date, person_name
from app.matching.names import name_similarity
from app.models import CompanyStatus, Entity, EntityType, LinkedEntity, Relationship, RelationType

API = "https://api.pappers.fr/v2"
UI = "https://www.pappers.fr/entreprise/{siren}"
PERSON_MATCH_MIN = 85


class PappersConnector(BaseConnector):
    name = "pappers"
    label = "Pappers (FR companies, officers, beneficial owners)"
    kind = "registry"
    key_setting = "pappers_api_key"
    jurisdictions = {"FR"}
    homepage = "https://www.pappers.fr"

    def _get(self, path: str, **params: Any) -> Any:
        return self.http_get_json(f"{API}{path}", params={"api_token": self.api_key, **params})

    def _profile(self, siren: str) -> dict[str, Any] | None:
        return self._get("/entreprise", siren=siren)

    # ---------------------------------------------------------- builders
    def _company(self, c: dict[str, Any]) -> Entity:
        siren = str(c.get("siren", ""))
        rid = self.record_id(siren)
        siege = c.get("siege") or {}
        finances = sorted(c.get("finances") or [], key=lambda f: f.get("annee") or 0, reverse=True)
        extra: dict[str, Any] = {}
        if c.get("capital") is not None:
            extra["share_capital"] = f"{c['capital']:,} {c.get('devise_capital') or 'EUR'}"
        if finances:
            f0 = finances[0]
            if f0.get("chiffre_affaires") is not None:
                extra["revenue_eur"] = f"{f0['chiffre_affaires']:,}"
            if f0.get("resultat") is not None:
                extra["net_income_eur"] = f"{f0['resultat']:,}"
        elif "finances" not in c:
            extra["accounts_unknown"] = True  # search result: accounts not included
        closing = finances[0].get("date_de_cloture_exercice") if finances else None
        address = ", ".join(
            p
            for p in (
                siege.get("adresse_ligne_1"),
                siege.get("adresse_ligne_2"),
                f"{siege.get('code_postal') or ''} {siege.get('ville') or ''}".strip(),
            )
            if p
        )
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=c.get("denomination") or c.get("nom_entreprise") or siren,
            aliases=[a for a in [c.get("nom_entreprise")] if a and a != c.get("denomination")],
            jurisdiction="FR",
            registration_number=siren,
            legal_form=c.get("forme_juridique"),
            status=CompanyStatus.DISSOLVED if c.get("entreprise_cessee") else CompanyStatus.ACTIVE,
            incorporation_date=parse_date(c.get("date_creation")),
            dissolution_date=parse_date(c.get("date_cessation")),
            last_accounts_date=parse_date(flexible_date(closing)) if closing else None,
            activity=" — ".join(p for p in (c.get("code_naf"), c.get("libelle_code_naf")) if p)
            or None,
            address=address or None,
            identifiers={"SIREN": siren},
            sources=[self.provenance(rid, UI.format(siren=siren))],
            extra=extra,
        )

    def _person(self, d: dict[str, Any], siren: str | None = None) -> Entity:
        nom = (d.get("nom") or "").upper()
        prenom = (d.get("prenom_usuel") or d.get("prenom") or "").upper()
        dob = flexible_date(
            d.get("date_de_naissance")
            or d.get("date_de_naissance_formate")
            or d.get("date_de_naissance_formatee")
        )
        rid = self.record_id(f"p:{nom}|{prenom}|{dob or ''}")
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.PERSON,
            name=person_name(prenom, nom) or d.get("nom_complet", ""),
            birth_date=dob,
            nationalities=nationality_iso(d.get("nationalite")),
            sources=[self.provenance(rid, UI.format(siren=siren) if siren else None)],
        )

    # --------------------------------------------------------- interface
    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        data = self._get("/recherche", q=name, par_page=10) or {}
        return [self._company(r) for r in data.get("resultats", [])]

    def get_company_details(self, company_id: str) -> Entity | None:
        siren = self.native_id(company_id)
        if siren.startswith("p:"):
            return None
        c = self._profile(siren)
        return self._company(c) if c else None

    def get_officers(self, company_id: str) -> list[LinkedEntity]:
        siren = self.native_id(company_id)
        c = self._profile(siren) or {}
        out = []
        for i, r in enumerate(c.get("representants") or []):
            if r.get("personne_morale"):
                if not r.get("siren"):
                    continue
                rid = self.record_id(str(r["siren"]))
                other = Entity(
                    id=rid,
                    record_ids=[rid],
                    type=EntityType.COMPANY,
                    name=r.get("denomination") or r.get("nom_complet") or str(r["siren"]),
                    jurisdiction="FR",
                    registration_number=str(r["siren"]),
                    sources=[self.provenance(rid, UI.format(siren=r["siren"]))],
                )
            else:
                other = self._person(r, siren)
            rel = Relationship(
                id=f"{self.name}:off:{siren}:{i}",
                type=RelationType.OFFICER,
                source_id=other.id,
                target_id=self.record_id(siren),
                role=r.get("qualite"),
                start_date=parse_date(flexible_date(r.get("date_prise_de_poste"))),
                end_date=None
                if r.get("actuel", True)
                else parse_date(flexible_date(r.get("date_fin_de_poste"))),
                sources=[
                    self.provenance(self.record_id(siren), UI.format(siren=siren) + "#dirigeants")
                ],
            )
            out.append(LinkedEntity(relationship=rel, entity=other))
        return out

    def get_shareholders(self, company_id: str) -> list[LinkedEntity]:
        """Declared beneficial owners (RBE) — shareholders are not exposed by Pappers."""
        siren = self.native_id(company_id)
        c = self._profile(siren) or {}
        out = []
        for i, b in enumerate(c.get("beneficiaires_effectifs") or []):
            other = self._person(b, siren)
            parts = b.get("pourcentage_parts")
            votes = b.get("pourcentage_votes")
            role = (
                "Declared beneficial owner"
                + (f" — {parts}% shares" if parts is not None else "")
                + (f", {votes}% votes" if votes is not None else "")
            )
            rel = Relationship(
                id=f"{self.name}:ubo:{siren}:{i}",
                type=RelationType.BENEFICIAL_OWNER,
                source_id=other.id,
                target_id=self.record_id(siren),
                role=role,
                share_pct=float(parts) if parts is not None else None,
                sources=[
                    self.provenance(
                        self.record_id(siren), UI.format(siren=siren) + "#beneficiaires"
                    )
                ],
            )
            out.append(LinkedEntity(relationship=rel, entity=other))
        return out

    def _dirigeants(self, name: str) -> list[dict[str, Any]]:
        data = self._get("/recherche-dirigeants", q=name, par_page=20) or {}
        return data.get("resultats", [])

    def search_person(self, name: str, **filters: Any) -> list[Entity]:
        out: dict[str, Entity] = {}
        for d in self._dirigeants(name):
            person = self._person(d)
            if name_similarity(name, person.name)[0] >= PERSON_MATCH_MIN:
                out.setdefault(person.id, person)
        return list(out.values())

    def get_person_details(self, person_id: str) -> Entity | None:
        native = self.native_id(person_id)
        if not native.startswith("p:"):
            return None
        nom, prenom, dob = (native[2:].split("|") + ["", "", ""])[:3]
        rid = self.record_id(native)
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.PERSON,
            name=person_name(prenom, nom),
            birth_date=dob or None,
            sources=[self.provenance(rid, None)],
        )

    def get_person_roles(self, person_id: str) -> list[LinkedEntity]:
        native = self.native_id(person_id)
        if not native.startswith("p:"):
            return []
        nom, prenom, _ = (native[2:].split("|") + ["", "", ""])[:3]
        out = []
        for d in self._dirigeants(f"{prenom} {nom}"):
            if self._person(d).id != self.record_id(native):
                continue
            for j, e in enumerate(d.get("entreprises") or []):
                if not e.get("siren"):
                    continue
                company = self._company({**e, "siren": e["siren"]})
                rel = Relationship(
                    id=f"{self.name}:role:{native}:{j}",
                    type=RelationType.OFFICER,
                    source_id=self.record_id(native),
                    target_id=company.id,
                    role=e.get("qualite") or (e.get("qualites") or [None])[0],
                    sources=[self.provenance(company.id, UI.format(siren=e["siren"]))],
                )
                out.append(LinkedEntity(relationship=rel, entity=company))
        return out
