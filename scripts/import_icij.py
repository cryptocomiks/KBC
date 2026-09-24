"""Build the local ICIJ Offshore Leaks SQLite database from the official bulk CSV.

    python scripts/import_icij.py                      # downloads the latest archive
    python scripts/import_icij.py --zip full-oldb.zip  # uses a file you downloaded

Source: https://offshoreleaks.icij.org/pages/database (ODbL licence, attribution
"International Consortium of Investigative Journalists"). The archive is a few
hundred MB once extracted; the resulting database is meant for local/Docker use.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sqlite3
import sys
import urllib.request
import zipfile

URL = "https://offshoreleaks-data.icij.org/offshoreleaks/csv/full-oldb.LATEST.zip"
NODE_FILES = {
    "nodes-entities.csv": "entity",
    "nodes-officers.csv": "officer",
    "nodes-intermediaries.csv": "intermediary",
}
csv.field_size_limit(10_000_000)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", help="path to an already downloaded full-oldb zip")
    ap.add_argument("--out", default=os.environ.get("ICIJ_DB_PATH", "data/icij_offshore_leaks.db"))
    args = ap.parse_args()

    path = args.zip
    if not path:
        path = "data/full-oldb.zip"
        os.makedirs("data", exist_ok=True)
        print(f"Downloading {URL} …", file=sys.stderr)
        urllib.request.urlretrieve(URL, path)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    tmp = args.out + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    db = sqlite3.connect(tmp)
    db.executescript(
        """
        CREATE TABLE nodes (node_id TEXT PRIMARY KEY, kind TEXT, name TEXT, source TEXT,
                            jurisdiction TEXT, countries TEXT);
        CREATE VIRTUAL TABLE nodes_fts USING fts5(name, content='nodes', content_rowid='rowid',
                                                  tokenize='unicode61 remove_diacritics 2');
        CREATE TABLE relationships (start_id TEXT, end_id TEXT, rel_type TEXT, link TEXT, source TEXT);
        """
    )
    with zipfile.ZipFile(path) as zf:
        members = {os.path.basename(n): n for n in zf.namelist()}
        for fname, kind in NODE_FILES.items():
            if fname not in members:
                print(f"warning: {fname} missing from archive", file=sys.stderr)
                continue
            with zf.open(members[fname]) as fh:
                reader = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"))
                rows = (
                    (r.get("node_id"), kind, r.get("name"), r.get("sourceID"),
                     r.get("jurisdiction_description") or r.get("jurisdiction"), r.get("countries"))
                    for r in reader if r.get("name")
                )
                db.executemany("INSERT OR IGNORE INTO nodes VALUES (?,?,?,?,?,?)", rows)
            print(f"imported {fname}", file=sys.stderr)
        if "relationships.csv" in members:
            with zf.open(members["relationships.csv"]) as fh:
                reader = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"))
                db.executemany(
                    "INSERT INTO relationships VALUES (?,?,?,?,?)",
                    ((r.get("node_id_start"), r.get("node_id_end"), r.get("rel_type"), r.get("link"),
                      r.get("sourceID")) for r in reader),
                )
    db.execute("INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')")
    db.execute("CREATE INDEX idx_rel_start ON relationships(start_id)")
    db.execute("CREATE INDEX idx_rel_end ON relationships(end_id)")
    db.commit()
    count = db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    db.close()
    os.replace(tmp, args.out)
    print(f"Done: {count:,} nodes -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
