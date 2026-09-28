# Matching validation report

Generated 2026-09-28T08:18:47+00:00 · engine 0.1.0 · test set v3 (96 labelled pairs)

Thresholds: possible match ≥ 70, strong match ≥ 85 (config/risk.yaml).

## Overall

| Measure | Value |
|---|---|
| Detection rate (same entity flagged) | **100.0 %** (55/55) |
| Strong detection (≥ 85) | 92.7 % |
| False-positive rate (different entity flagged) | **0.0 %** (0/41) |
| Accuracy | 100.0 % |

## By category

| Category | Expected | Pairs | Detection | False positives |
|---|---|---|---|---|
| Transliteration / middle names | match | 20 | 100.0 % | - |
| Diacritics & case | match | 5 | 100.0 % | - |
| Name order | match | 4 | 100.0 % | - |
| Same person, same date of birth | match | 3 | 100.0 % | - |
| Company legal forms & punctuation | match | 14 | 100.0 % | - |
| Typos | match | 4 | 100.0 % | - |
| Same registration number | match | 2 | 100.0 % | - |
| Namesakes, different date of birth | no match | 6 | - | 0.0 % |
| Very common names, no date of birth | no match | 6 | - | 0.0 % |
| Different people sharing a name part | no match | 9 | - | 0.0 % |
| Single word vs full name | no match | 3 | - | 0.0 % |
| Generic company words only | no match | 8 | - | 0.0 % |
| Same distinctive name, other generic words (review expected) | match | 1 | 100.0 % | - |
| Same name, different country | no match | 3 | - | 0.0 % |
| Person vs company | no match | 3 | - | 0.0 % |
| A distinctive word is missing | no match | 3 | - | 0.0 % |
| Same name + country (subsidiary, review expected) | match | 2 | 100.0 % | - |

## Errors

None.

## Method

Each pair of the test set (config/matching_testset.json) is scored by the production matcher and the alert triage, as in the product: a pair raises an alert when its score reaches the possible-match threshold and the triage does not set it aside as a probable namesake (different date of birth, nationality, country or name part). The test set mixes public figures and fictitious names; it is versioned with the code and extended whenever a real-world error is found. Regenerate with `python scripts/validation_report.py`.

## Limits

The pairs were written by the development team to cover known difficulties; a perfect score on them is a regression guard, not a guarantee on real data. The rates to rely on come from an independent sample of real alerts reviewed by analysts, to be added to this set before production use. The engine also depends on the data each list publishes (a missing date of birth or nationality limits what the triage can rule out).
