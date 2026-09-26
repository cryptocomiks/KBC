"""Bulk import of a client list (CSV or Excel) into cases.

Each row becomes a case waiting to be analysed. The rows are then processed
one step at a time (find the company, then investigate it), so that every call
stays within the host's time limit: the import screen drives the queue while
it is open, and the daily monitoring job finishes what is left.

Recognised columns (any order, French or English headers): name / company /
raison sociale, identifier (SIREN, SIRET, LEI, UID, company number…), country,
reference. Without a recognised header, the first column is the query.
The file is read in memory and never stored.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from typing import Any
from xml.etree import ElementTree

MAX_ROWS = 500
MAX_BYTES = 4 * 1024 * 1024

HEADERS = {
    "name": {
        "name", "nom", "company", "company name", "societe", "entreprise", "raison sociale",
        "denomination", "client", "legal name", "entity", "entite", "firma",
    },
    "identifier": {
        "identifier", "identifiant", "id", "siren", "siret", "lei", "uid", "ide",
        "company number", "registration number", "numero", "n siren", "numero siren",
        "numero rcs", "rcs", "registre", "tva", "vat", "vat number", "crn", "cik",
        "numero d'identification",
    },
    "country": {"country", "pays", "jurisdiction", "juridiction", "country code", "code pays"},
    "reference": {
        "reference", "ref", "client id", "client reference", "reference client", "code client",
        "dossier", "file", "internal id",
    },
}  # fmt: skip
COUNTRY_NAMES = {
    "france": "FR", "suisse": "CH", "switzerland": "CH", "luxembourg": "LU",
    "belgique": "BE", "belgium": "BE", "royaume-uni": "GB", "united kingdom": "GB",
    "uk": "GB", "allemagne": "DE", "germany": "DE", "espagne": "ES", "spain": "ES",
    "italie": "IT", "italy": "IT", "pays-bas": "NL", "netherlands": "NL", "monaco": "MC",
    "etats-unis": "US", "united states": "US", "usa": "US", "irlande": "IE", "ireland": "IE",
}  # fmt: skip


class ImportError_(ValueError):
    """The file cannot be read as a client list."""


def _key(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower()).strip()


def _country(value: str) -> str | None:
    v = (value or "").strip()
    if not v:
        return None
    if re.fullmatch(r"[A-Za-z]{2}", v):
        return v.upper().replace("UK", "GB")
    return COUNTRY_NAMES.get(_key(v))


# ------------------------------------------------------------------ readers
def _read_csv(data: bytes) -> list[list[str]]:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref or "A")
    n = 0
    for ch in letters.group(0) if letters else "A":
        n = n * 26 + ord(ch) - 64
    return n - 1


def _read_xlsx(data: bytes) -> list[list[str]]:
    """First worksheet of an .xlsx file (Office Open XML), without external dependency."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ImportError_("Not a valid Excel (.xlsx) file.") from exc
    names = set(z.namelist())
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        root = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
    sheet = "xl/worksheets/sheet1.xml"
    if "xl/workbook.xml" in names and "xl/_rels/workbook.xml.rels" in names:
        wb = ElementTree.fromstring(z.read("xl/workbook.xml"))
        first = wb.find("m:sheets/m:sheet", _NS)
        rels = ElementTree.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        if first is not None:
            rid = first.get(_REL)
            for rel in rels:
                if rel.get("Id") == rid:
                    target = rel.get("Target", "").lstrip("/")
                    sheet = target if target.startswith("xl/") else f"xl/{target}"
    if sheet not in names:
        raise ImportError_("The Excel file has no worksheet.")
    root = ElementTree.fromstring(z.read(sheet))
    rows: list[list[str]] = []
    for row in root.iter(f"{{{_NS['m']}}}row"):
        values: dict[int, str] = {}
        for c in row.findall("m:c", _NS):
            kind = c.get("t")
            v = c.find("m:v", _NS)
            if kind == "s" and v is not None:
                text = shared[int(v.text or 0)]
            elif kind == "inlineStr":
                text = "".join(t.text or "" for t in c.iter(f"{{{_NS['m']}}}t"))
            else:
                text = v.text if v is not None and v.text else ""
                if re.fullmatch(r"\d+\.0", text):
                    text = text[:-2]  # identifiers typed as numbers
            values[_col_index(c.get("r", ""))] = text
        if values:
            rows.append([values.get(i, "") for i in range(max(values) + 1)])
    return rows


# ------------------------------------------------------------------- parse
def parse(filename: str, data: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    """Rows of the client list: {name, identifier, country, reference, query}."""
    if len(data) > MAX_BYTES:
        raise ImportError_("File too large (4 MB maximum).")
    lower = (filename or "").lower()
    if lower.endswith((".xlsx", ".xlsm")):
        table = _read_xlsx(data)
    elif lower.endswith(".xls"):
        raise ImportError_("Old Excel format (.xls): save the file as .xlsx or .csv.")
    else:
        table = _read_csv(data)
    table = [[str(c).strip() for c in row] for row in table if any(str(c).strip() for c in row)]
    if not table:
        raise ImportError_("The file is empty.")

    header = [_key(c) for c in table[0]]
    columns: dict[str, int] = {}
    for field, labels in HEADERS.items():
        for i, h in enumerate(header):
            if h in labels and i not in columns.values():
                columns[field] = i
                break
    has_header = bool(columns)
    body = table[1:] if has_header else table
    if not has_header:
        columns = {"name": 0}

    def cell(raw: list[str], field: str) -> str:
        i = columns.get(field)
        return raw[i].strip() if i is not None and i < len(raw) else ""

    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n, raw in enumerate(body, start=2 if has_header else 1):
        name, ident = cell(raw, "name"), cell(raw, "identifier")
        if not name and not ident:
            continue
        query = ident or name
        key = _key(query)
        if key in seen:
            warnings.append(f"Line {n}: duplicate of an earlier line, skipped ({query}).")
            continue
        seen.add(key)
        rows.append(
            {
                "line": n,
                "name": name,
                "identifier": ident,
                "country": _country(cell(raw, "country")),
                "reference": cell(raw, "reference")[:60],
                "query": query[:200],
            }
        )
        if len(rows) >= MAX_ROWS:
            warnings.append(f"Only the first {MAX_ROWS} clients were imported.")
            break
    if not rows:
        raise ImportError_("No client found in the file (expected a name or an identifier column).")
    return rows, warnings
