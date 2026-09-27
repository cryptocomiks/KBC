"""Name normalisation, transliteration handling and fuzzy similarity.

Three complementary views of a name are compared:

1. the *normalised* form (ASCII-folded, lower case, punctuation and legal
   forms removed, tokens sorted);
2. the *canonical* form, where each token is mapped to a canonical spelling
   when it belongs to a known transliteration family
   (Mohamed / Mohammed / Muhammad / Maxamed -> "muhammad");
3. a *phonetic skeleton* collapsing systematic romanisation differences
   (q/k, kh/h, ou/u, y/i, double letters...).

The best score wins, but each rule that contributed is reported so the
analyst understands *why* two names were considered close.
"""

from __future__ import annotations

import re
from functools import lru_cache

from rapidfuzz import fuzz
from unidecode import unidecode

# Families of transliteration variants. Each family maps to its first element.
# Deliberately editable: add families for the populations you screen.
VARIANT_FAMILIES: list[list[str]] = [
    [
        "muhammad",
        "mohamed",
        "mohammed",
        "mohammad",
        "mohamad",
        "muhammed",
        "muhamed",
        "mohammd",
        "mouhamed",
        "mouhammad",
        "mahomed",
        "maxamed",
        "mehmet",
        "mehmed",
    ],
    ["ahmad", "ahmed", "ahmet", "axmed", "achmed"],
    ["abdallah", "abdullah", "abdulla", "abdellah", "abdalla", "cabdullahi", "abdullahi"],
    ["hussein", "husain", "hussain", "hosein", "hossein", "husayn", "xuseen", "houssein"],
    ["yusuf", "youssef", "yousef", "yusef", "youcef", "joseph", "iosif", "yosef"],
    ["mustafa", "moustafa", "mostafa", "mustapha", "mostefa"],
    ["aleksandr", "alexander", "alexandre", "aleksander", "alexandr", "oleksandr"],
    ["sergei", "sergey", "serguei", "sergiy", "serhiy"],
    ["yuri", "yury", "iouri", "yuriy", "juri"],
    ["dmitri", "dmitry", "dmitriy", "dimitri"],
    ["mikhail", "michail", "mikhael", "mykhailo"],
    ["vladimir", "wladimir", "volodymyr"],
    ["tatiana", "tatyana", "tatjana"],
    ["olga", "olha"],
    ["pyotr", "petr", "piotr", "pyotor"],
    ["andrei", "andrey", "andriy", "andrej"],
    ["nikolai", "nikolay", "mykola", "nicolai"],
    ["zhang", "chang"],
    ["xi", "hsi"],
]

_CANONICAL: dict[str, str] = {v: fam[0] for fam in VARIANT_FAMILIES for v in fam}

# Words that carry no identifying information.
_PERSON_NOISE = {
    "mr",
    "mrs",
    "ms",
    "dr",
    "sir",
    "madame",
    "monsieur",
    "mme",
    "m",
    "sheikh",
    "al",
    "el",
    "bin",
    "ben",
    "ibn",
    "von",
    "van",
    "de",
    "der",
    "da",
    "di",
}

# Legal forms, removed when comparing company names.
_LEGAL_FORMS = {
    "sa",
    "sas",
    "sasu",
    "sarl",
    "eurl",
    "sci",
    "snc",
    "sca",
    "scs",
    "gie",
    "selarl",
    "s a r l",
    "ltd",
    "limited",
    "llc",
    "llp",
    "lp",
    "plc",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "gmbh",
    "ag",
    "kg",
    "bv",
    "nv",
    "spa",
    "srl",
    "sl",
    "oy",
    "ab",
    "as",
    "aps",
    "sàrl",
    "se",
    "fze",
    "fzco",
    "fzc",
    "pte",
    "pty",
    # Russian / CIS legal forms (Latin and transliterated)
    "pjsc", "ojsc", "cjsc", "jsc", "pao", "oao", "zao", "ooo", "ao", "tov", "too",
    # Brazilian and Portuguese / Spanish forms
    "ltda", "eireli", "sa de cv",
}  # fmt: skip
# Words shared by thousands of unrelated companies: a match on them alone proves nothing.
GENERIC_COMPANY_WORDS = {
    "holding", "holdings", "group", "groupe", "gruppe", "international", "intl", "global",
    "capital", "trading", "trade", "invest", "investment", "investments", "investissement",
    "investissements", "participations", "partners", "partner", "services", "service",
    "management", "consulting", "conseil", "development", "developpement", "enterprises",
    "enterprise", "entreprise", "industries", "industrie", "industry", "finance", "financial",
    "solutions", "technologies", "technology", "tech", "ventures", "assets", "asset",
    "resources", "properties", "property", "immobilier", "immobiliere", "real", "estate",
    "import", "export", "logistics", "logistique", "energy", "general", "commercial",
    "worldwide", "europe", "european", "euro", "asia", "pacific", "america", "american",
    "africa", "middle", "east", "west", "north", "south", "overseas", "trust", "fund", "funds",
    "securities", "advisors", "advisory", "associates", "and", "of", "the", "et", "des", "du",
    "la", "le", "les", "de", "und", "fur", "new", "first", "united", "royal", "national",
    # country and region adjectives: "Swiss Invest" and "Swiss Holding" share nothing
    "swiss", "suisse", "schweiz", "schweizer", "svizzera", "helvetia", "helvetic", "french",
    "france", "german", "germany", "deutsche", "deutschland", "british", "britannia", "uk",
    "us", "usa", "asian", "african", "nordic", "scandinavian", "atlantic", "alpine", "alpen",
    "central", "eastern", "western", "northern", "southern", "orient", "oriental", "gulf",
    "continental", "universal", "prime", "premier", "luxembourg", "monaco", "dubai",
}  # fmt: skip
# Very frequent given names and surnames: a name made only of these needs a date of birth.
COMMON_NAMES = {
    "john", "james", "david", "michael", "robert", "william", "richard", "thomas", "mark",
    "paul", "peter", "maria", "anna", "jean", "pierre", "michel", "philippe", "alain",
    "marie", "hans", "klaus", "ali", "hassan", "muhammad", "ahmad", "abdallah", "hussein",
    "yusuf", "mustafa", "omar", "ibrahim", "aleksandr", "sergei", "dmitri", "vladimir",
    "andrei", "nikolai", "wei", "li", "wang", "zhang", "liu", "chen", "yang", "huang", "zhao",
    "wu", "zhou", "xu", "sun", "nguyen", "tran", "le", "pham", "kim", "lee", "park", "choi",
    "singh", "kumar", "sharma", "patel", "khan", "shah", "smith", "johnson", "williams",
    "brown", "jones", "miller", "davis", "wilson", "taylor", "garcia", "rodriguez",
    "martinez", "hernandez", "lopez", "gonzalez", "perez", "sanchez", "ivanov", "smirnov",
    "kuznetsov", "popov", "petrov", "muller", "mueller", "schmidt", "schneider", "fischer",
    "weber", "meyer", "wagner", "martin", "bernard", "dubois", "durand", "moreau", "petit",
    "rossi", "russo", "ferrari", "silva", "santos", "oliveira", "pereira", "costa",
    "rodrigues", "fernandes", "yilmaz", "kaya", "demir",
}  # fmt: skip
_LEGAL_FORM_PATTERNS = [
    r"\bs a r l\b", r"\bs a s\b", r"\bs a\b", r"\bs e n c\b",
    # dotted legal forms: "N.V.", "B.V.", "S.p.A.", "S.r.l.", "A.G.", "L.L.C.", "P.L.C."
    r"\bn v\b", r"\bb v\b", r"\bs p a\b", r"\bs r l\b", r"\ba g\b", r"\bl l c\b",
    r"\bp l c\b", r"\bl t d\b", r"\bg m b h\b", r"\bs l\b", r"\bs e\b",
    # Russian legal forms written out (transliterated from the register)
    r"\bpublichnoe aktsionernoe obshchestvo\b", r"\bnepublichnoe aktsionernoe obshchestvo\b",
    r"\baktsionernoe obshchestvo\b", r"\bobshchestvo s ogranichennoi otvetstvennostiu\b",
    r"\bpublic joint stock company\b", r"\bjoint stock company\b",
]  # fmt: skip

_PHONETIC_RULES: list[tuple[str, str]] = [
    (r"sch", "sh"),
    (r"tch", "ch"),
    (r"tsch", "ch"),
    (r"dj", "j"),
    (r"dzh", "j"),
    (r"zh", "j"),
    (r"kh", "h"),
    (r"gh", "g"),
    (r"ph", "f"),
    (r"th", "t"),
    (r"ck", "k"),
    (r"q", "k"),
    (r"c(?=[aou])", "k"),
    (r"w", "v"),
    (r"ou", "u"),
    (r"oo", "u"),
    (r"ee", "i"),
    (r"ie", "i"),
    (r"y", "i"),
    (r"ey$", "i"),
    (r"(.)\1+", r"\1"),
]


def ascii_fold(text: str) -> str:
    return unidecode(text or "").lower()


def tokenize(text: str) -> list[str]:
    text = ascii_fold(text)
    text = re.sub(r"[-_/'’.,()&]+", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", "", text)
    return [t for t in text.split() if t]


def normalize_person(name: str) -> list[str]:
    return [t for t in tokenize(name) if t not in _PERSON_NOISE]


def normalize_company(name: str) -> list[str]:
    text = " ".join(tokenize(name))  # "S.à r.l." -> "s a r l"
    for pat in _LEGAL_FORM_PATTERNS:
        text = re.sub(pat, " ", text)
    return [t for t in text.split() if t not in _LEGAL_FORMS]


@lru_cache(maxsize=4096)
def phonetic(token: str) -> str:
    out = token
    for pattern, repl in _PHONETIC_RULES:
        out = re.sub(pattern, repl, out)
    return out


def canonical(token: str) -> str:
    return _CANONICAL.get(token, token)


def _join(tokens: list[str]) -> str:
    return " ".join(sorted(tokens))


def _aligned(ta: list[str], tb: list[str]) -> float:
    """Token-by-token alignment: every token of the shorter name must find a
    close counterpart. Blending mean and min prevents a shared first name
    from masking a different surname (Mohammed Qadrany vs Mohammed Qadri)."""
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    remaining = list(long_)
    scores = []
    for tok in short:
        best_tok, best = max(((o, fuzz.ratio(tok, o)) for o in remaining), key=lambda x: x[1])
        remaining.remove(best_tok)
        scores.append(best)
    score = 0.5 * (sum(scores) / len(scores)) + 0.5 * min(scores)
    # Unmatched tokens on the longer side cost a little for one (a middle name), then more:
    # "Ali Hassan" is not established by "Ali Hassan Salameh Al-Tikriti".
    extra = len(remaining)
    return score * (0.93 if extra else 1.0) * (0.85 ** max(0, extra - 1))


def name_similarity(a: str, b: str, kind: str = "person") -> tuple[float, list[str]]:
    """Return a 0-100 similarity score and the reasons behind it."""
    norm = normalize_company if kind == "company" else normalize_person
    ta, tb = norm(a), norm(b)
    if not ta or not tb:
        return 0.0, ["empty name after normalisation"]

    notes: list[str] = []
    guard = _guard(ta, tb, kind)
    if _join(ta) == _join(tb):
        exact = ascii_fold(a).strip() == ascii_fold(b).strip()
        notes = ["exact name match" if exact else "same name after normalisation"]
        if guard and guard[1].startswith("generic name"):
            return guard[0], [*notes, guard[1]]
        if kind == "person" and all(canonical(t) in COMMON_NAMES for t in ta):
            notes.append("very common name: a date of birth is needed to confirm")
        return 100.0, notes

    s_plain = min(fuzz.token_sort_ratio(_join(ta), _join(tb)), _aligned(ta, tb) + 5)

    ca, cb = [canonical(t) for t in ta], [canonical(t) for t in tb]
    s_canon = _aligned(ca, cb)
    variant_pairs = sorted(
        {f"{x} ≈ {y}" for x in ta for y in tb if x != y and canonical(x) == canonical(y)}
    )

    pa, pb = [phonetic(t) for t in ca], [phonetic(t) for t in cb]
    s_phon = _aligned(pa, pb) * 0.97  # slightly less trusted than spelling

    best = max(s_plain, s_canon, s_phon)
    s_dist = 0.0
    if kind == "company" and guard is None:
        # Generic words neither make nor break a match: "Meridian" and "Meridian Capital
        # Holdings" share their distinctive part, which is worth a possible match.
        da = [t for t in ta if t not in GENERIC_COMPANY_WORDS]
        db = [t for t in tb if t not in GENERIC_COMPANY_WORDS]
        if da and db and (len(da) != len(ta) or len(db) != len(tb)):
            s_dist = _aligned(da, db) * 0.84
            best = max(best, s_dist)
    if best < 60:
        return round(best, 1), ["names are dissimilar"]
    if s_dist and best == s_dist:
        notes.append("same distinctive name, different generic words (holding, capital...)")
    elif best == s_plain:
        notes.append(f"fuzzy spelling similarity {s_plain:.0f}%")
    if variant_pairs and s_canon >= s_plain:
        notes.append("known transliteration variant: " + ", ".join(variant_pairs))
    if best == s_phon and s_phon > max(s_plain, s_canon):
        notes.append("phonetic/romanisation match (e.g. q/k, ou/u, y/i, double letters)")
    if len(ta) != len(tb):
        notes.append("token count differs (middle name or missing token)")
    if kind == "person" and all(canonical(t) in COMMON_NAMES for t in ta + tb):
        notes.append("very common name: a date of birth is needed to confirm")
    if guard and best > guard[0]:
        best = guard[0]
        notes.append(guard[1])
    return round(min(best, 99.0), 1), notes


def _guard(ta: list[str], tb: list[str], kind: str) -> tuple[float, str] | None:
    """Caps for matches that rest on too little: (max score, reason), or None."""
    if kind == "company":
        da = [t for t in ta if t not in GENERIC_COMPANY_WORDS]
        db = [t for t in tb if t not in GENERIC_COMPANY_WORDS]
        if not da and not db:
            if sorted(ta) == sorted(tb):
                return 84.0, "generic name (only common words): needs an identifier to confirm"
            return 60.0, "different generic names (only common words, not the same ones)"
        if not da or not db:
            return 68.0, "one name has only generic words: the distinctive part is missing"
        ca, cb = [canonical(t) for t in da], [canonical(t) for t in db]
        if (
            max(_aligned(da, db), _aligned([phonetic(t) for t in ca], [phonetic(t) for t in cb]))
            < 75
        ):
            shared = sorted(set(ta) & set(tb) & GENERIC_COMPANY_WORDS)
            return 65.0, "only generic words in common" + (
                f" ({', '.join(shared)})" if shared else ""
            )
        return None
    if min(len(ta), len(tb)) == 1 and max(len(ta), len(tb)) > 1:
        return 68.0, "single-word name against a full name: not enough to identify a person"
    weak = _weakest_part(ta, tb)
    if weak and weak[0] < 80:
        return 66.0, f"a name part differs ({weak[1]} ≠ {weak[2]}): probably another person"
    return None


def _romanised(x: str) -> str:
    """Key absorbing Arabic / Persian romanisation variants: q, g, gh, k -> k; dh -> d;
    double letters collapsed (Gaddafi, Qadhafi, Kadhafi -> kadafi)."""
    s = re.sub(r"gh|q|g", "k", x).replace("dh", "d")
    return re.sub(r"(.)\1+", r"\1", s)


def _part_similarity(x: str, y: str) -> float:
    """Similarity of two name parts, allowing for transliteration and romanisation variants."""
    if canonical(x) == canonical(y) or phonetic(canonical(x)) == phonetic(canonical(y)):
        return 100.0
    if _romanised(canonical(x)) == _romanised(canonical(y)):
        return 100.0
    return max(fuzz.ratio(x, y), fuzz.ratio(canonical(x), canonical(y)))


def _weakest_part(ta: list[str], tb: list[str]) -> tuple[float, str, str] | None:
    """The least similar part of the shorter name, matched against the best part of the other
    name (e.g. "putin" ≈ "potanin" 67 %): two different surnames with the same first name are
    two people, however similar the full strings look."""
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(short) < 2:
        return None
    # compound parts written in one or two words: "Abdulrahman" = "Abdul Rahman"
    long_ = [*long_, *(a + b for a, b in zip(long_, long_[1:], strict=False))]
    worst: tuple[float, str, str] | None = None
    for x in short:
        best = max(long_, key=lambda y: _part_similarity(x, y))
        sim = _part_similarity(x, best)
        if worst is None or sim < worst[0]:
            worst = (sim, x, best)
    return worst
