"""Regenerate the matching validation report (docs/validation/matching_report.{md,json})."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.validation import run_validation, to_markdown  # noqa: E402

OUT = ROOT / "docs" / "validation"


def main() -> None:
    report = run_validation()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "matching_report.md").write_text(to_markdown(report), encoding="utf-8")
    (OUT / "matching_report.json").write_text(
        json.dumps({k: v for k, v in report.items() if k != "pairs"}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    o = report["overall"]
    print(
        f"{o['pairs']} pairs · detection {o['detection_rate']} % · "
        f"false positives {o['false_positive_rate']} % · errors {len(report['errors'])}"
    )


if __name__ == "__main__":
    main()
