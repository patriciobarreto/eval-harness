"""
Convert a QuickBooks chart-of-accounts export ("Account name, Account type,
Detail type" CSV) into the categories.json build_fixture_drafts.py expects:
a JSON list of {"id": int, "name": str, "classification": str}.

The export has no numeric account ID and no "Classification" column --
QBO derives Classification (Asset / Liability / Equity / Revenue / Expense)
from Account type. ACCOUNT_TYPE_CLASSIFICATION below is that standard
mapping. `id` is a synthetic, stable index assigned in the source file's
original row order (before any --exclude-classification filtering), so
category IDs don't shift around if you re-run with a different exclusion
set later.

Usage:
    python adapters/convert_chart_of_accounts.py \\
        --csv "~/Downloads/Some Client.csv" \\
        --out ~/some/private/directory/categories.json \\
        --exclude-classification Asset
"""

import argparse
import csv
import json
import sys
from pathlib import Path

ACCOUNT_TYPE_CLASSIFICATION = {
    "Bank": "Asset",
    "Accounts receivable (A/R)": "Asset",
    "Other Current Assets": "Asset",
    "Fixed Assets": "Asset",
    "Accounts payable (A/P)": "Liability",
    "Credit Card": "Liability",
    "Other Current Liabilities": "Liability",
    "Long Term Liabilities": "Liability",
    "Equity": "Equity",
    "Income": "Revenue",
    "Cost of Goods Sold": "Expense",
    "Expenses": "Expense",
    "Other Income": "Revenue",
    "Other Expense": "Expense",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--exclude-classification",
        action="append",
        default=[],
        help="Repeatable. e.g. --exclude-classification Asset --exclude-classification Liability",
    )
    args = parser.parse_args()

    excluded = set(args.exclude_classification)

    with open(args.csv, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    categories = []
    unmapped_types = set()
    for i, row in enumerate(rows, start=1):
        account_type = row["Account type"].strip()
        classification = ACCOUNT_TYPE_CLASSIFICATION.get(account_type)
        if classification is None:
            unmapped_types.add(account_type)
            continue
        categories.append(
            {"id": i, "name": row["Account name"].strip(), "classification": classification}
        )

    if unmapped_types:
        print(
            f"Error: unrecognized Account type(s), not in ACCOUNT_TYPE_CLASSIFICATION: "
            f"{sorted(unmapped_types)}. Add them to the mapping and rerun rather than "
            "guessing a classification.",
            file=sys.stderr,
        )
        sys.exit(1)

    kept = [c for c in categories if c["classification"] not in excluded]
    dropped = len(categories) - len(kept)

    print(f"Loaded {len(categories)} accounts from {args.csv.name}")
    if excluded:
        print(f"Excluded {dropped} account(s) with classification in {sorted(excluded)}")
    print(f"Writing {len(kept)} categories")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(kept, indent=2) + "\n")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
