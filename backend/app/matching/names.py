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
}
_LEGAL_FORM_PATTERNS = [r"\bs a r l\b", r"\bs a s\b", r"\bs a\b", r"\bs e n c\b"]

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
    # Unmatched tokens on the longer side (e.g. a middle name) cost a little.
    return score * (0.93 ** len(remaining))


def name_similarity(a: str, b: str, kind: str = "person") -> tuple[float, list[str]]:
    """Return a 0-100 similarity score and the reasons behind it."""
    norm = normalize_company if kind == "company" else normalize_person
    ta, tb = norm(a), norm(b)
    if not ta or not tb:
        return 0.0, ["empty name after normalisation"]

    notes: list[str] = []
    if _join(ta) == _join(tb):
        exact = ascii_fold(a).strip() == ascii_fold(b).strip()
        return 100.0, ["exact name match" if exact else "same name after normalisation"]

    s_plain = min(fuzz.token_sort_ratio(_join(ta), _join(tb)), _aligned(ta, tb) + 5)

    ca, cb = [canonical(t) for t in ta], [canonical(t) for t in tb]
    s_canon = _aligned(ca, cb)
    variant_pairs = sorted(
        {f"{x} ≈ {y}" for x in ta for y in tb if x != y and canonical(x) == canonical(y)}
    )

    pa, pb = [phonetic(t) for t in ca], [phonetic(t) for t in cb]
    s_phon = _aligned(pa, pb) * 0.97  # slightly less trusted than spelling

    best = max(s_plain, s_canon, s_phon)
    if best < 60:
        return round(best, 1), ["names are dissimilar"]
    if best == s_plain:
        notes.append(f"fuzzy spelling similarity {s_plain:.0f}%")
    if variant_pairs and s_canon >= s_plain:
        notes.append("known transliteration variant: " + ", ".join(variant_pairs))
    if best == s_phon and s_phon > max(s_plain, s_canon):
        notes.append("phonetic/romanisation match (e.g. q/k, ou/u, y/i, double letters)")
    if len(ta) != len(tb):
        notes.append("token count differs (middle name or missing token)")
    return round(min(best, 99.0), 1), notes
