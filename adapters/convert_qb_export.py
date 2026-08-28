"""
Convert a QuickBooks "Transaction List by Date" CSV export into the three
files the fixture-generation pipeline needs, split at a cutoff date:

  - history.csv        transactions BEFORE the cutoff, WITH their real
                        category -- feeds seed_test_client.py.
  - to_categorize.csv   transactions ON/AFTER the cutoff, category columns
                        stripped -- feeds build_fixture_drafts.py. These
                        must be transactions the test client has never seen
                        before, so the categorizer can't just look them up.
  - ground_truth.csv    the same on/after-cutoff transactions, WITH their
                        real category kept alongside qbTransactionId. Not
                        fed to the categorizer -- used afterward to fill in
                        expected_output in the draft fixtures build_fixture_drafts.py
                        produces, replacing the model's own guess with what
                        actually happened.

A raw QuickBooks export has no transaction ID column, so one is generated
per row (--id-prefix, defaulting to a slug of the company name on the
export's first line) and reused consistently across all three files so rows
join back up by qbTransactionId.

Rows with no Amount or no Split (category) are dropped -- QB exports
sometimes contain reporting-only Journal Entry rows with neither (e.g. an
insurance premium "reported by client from personal account" with no
dollar figure and no account assigned). Also flags -- but does not drop --
rows whose Split points at another account rather than a P&L category
(inter-account transfers, e.g. a Credit Card Payment row categorized as
"Credit Card BoA:...") so you can decide whether those belong in an eval
built to test expense categorization.

Usage:
    python adapters/convert_qb_export.py \\
        --csv "~/Downloads/Some Client_Transaction List by Date.csv" \\
        --cutoff-date 2025-11-01 \\
        --out-dir ~/some/private/directory
"""

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

# A Split like "Credit Card BoA:(5044) Business Adv Customized Cash Rewards -"
# points at another account (an inter-account transfer), not a P&L category --
# recognizable by the parenthesized account number, unlike a real category
# such as "Office expenses:Software & apps". Transaction type alone isn't a
# reliable signal: a "Credit Card Credit" row is usually a real refund against
# a normal category (e.g. "Supplies"), not a transfer.
TRANSFER_LIKE_SPLIT_PATTERN = re.compile(r"\(\d{3,}\)")


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "txn"


def _find_header_row(rows: list[list[str]]) -> int:
    for i, row in enumerate(rows):
        if row and row[0] == "Date":
            return i
    raise ValueError("couldn't find the 'Date' header row in this export")


def _parse_amount(raw: str) -> float:
    return float(raw.replace("$", "").replace(",", ""))


def _load_qb_export(path: Path) -> tuple[str, list[dict]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    company_name = rows[0][0] if rows and rows[0] else "unknown-company"
    header_idx = _find_header_row(rows)
    data_rows = rows[header_idx + 1 :]

    parsed = []
    skipped_incomplete = 0
    transfer_like = 0

    for row in data_rows:
        if not row or not row[0] or row[0] in ("TOTAL",) or row[0].startswith(" "):
            continue  # blank line, TOTAL row, or the export's trailing timestamp line

        date_str, txn_type, _num, _posting, name, memo, _account_name, split, amount_str = (
            row + [""] * 9
        )[:9]

        if not amount_str.strip() or not split.strip():
            skipped_incomplete += 1
            continue

        if TRANSFER_LIKE_SPLIT_PATTERN.search(split):
            transfer_like += 1

        parsed.append(
            {
                "date": datetime.strptime(date_str, "%m/%d/%Y"),
                "qbTransactionType": txn_type,
                "bankDetail": memo.strip() or name.strip(),
                "qbCategoryName": split.strip(),
                "amount": _parse_amount(amount_str),
            }
        )

    print(f"Parsed {len(parsed)} usable rows from {path.name}")
    if skipped_incomplete:
        print(f"  skipped {skipped_incomplete} row(s) with no Amount or no Split (category)")
    if transfer_like:
        print(
            f"  note: {transfer_like} row(s) have a Split that points at another account "
            "(looks like an inter-account transfer), not a P&L expense category. Not dropped -- "
            "decide whether these belong in the eval before running seed_test_client.py / "
            "build_fixture_drafts.py on the output."
        )

    return company_name, parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument(
        "--cutoff-date",
        required=True,
        help="ISO date (YYYY-MM-DD). Rows before this go to history.csv, "
        "rows on/after go to to_categorize.csv / ground_truth.csv.",
    )
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument(
        "--id-prefix",
        default=None,
        help="Defaults to a slug of the company name on the export's first line.",
    )
    args = parser.parse_args()

    cutoff = datetime.strptime(args.cutoff_date, "%Y-%m-%d")
    company_name, rows = _load_qb_export(args.csv)
    id_prefix = args.id_prefix or _slugify(company_name)

    history_rows, holdout_rows = [], []
    for i, row in enumerate(rows, start=1):
        row["qbTransactionId"] = f"{id_prefix}_{i:04d}"
        (holdout_rows if row["date"] >= cutoff else history_rows).append(row)

    print(
        f"\nSplit at {args.cutoff_date}: {len(history_rows)} history rows, "
        f"{len(holdout_rows)} holdout rows"
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)

    history_path = args.out_dir / "history.csv"
    with open(history_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "qbTransactionId",
                "date",
                "amount",
                "qbTransactionType",
                "bankDetail",
                "qbCategoryName",
                "qbCategoryId",
            ],
        )
        writer.writeheader()
        for row in history_rows:
            writer.writerow(
                {
                    "qbTransactionId": row["qbTransactionId"],
                    "date": row["date"].strftime("%Y-%m-%d"),
                    "amount": row["amount"],
                    "qbTransactionType": row["qbTransactionType"],
                    "bankDetail": row["bankDetail"],
                    "qbCategoryName": row["qbCategoryName"],
                    "qbCategoryId": "",
                }
            )

    to_categorize_path = args.out_dir / "to_categorize.csv"
    with open(to_categorize_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["qbTransactionId", "date", "amount", "qbTransactionType", "bankDetail"]
        )
        writer.writeheader()
        for row in holdout_rows:
            writer.writerow(
                {
                    "qbTransactionId": row["qbTransactionId"],
                    "date": row["date"].strftime("%Y-%m-%d"),
                    "amount": row["amount"],
                    "qbTransactionType": row["qbTransactionType"],
                    "bankDetail": row["bankDetail"],
                }
            )

    ground_truth_path = args.out_dir / "ground_truth.csv"
    with open(ground_truth_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["qbTransactionId", "qbCategoryName"])
        writer.writeheader()
        for row in holdout_rows:
            writer.writerow(
                {"qbTransactionId": row["qbTransactionId"], "qbCategoryName": row["qbCategoryName"]}
            )

    print(f"\nWrote:\n  {history_path}\n  {to_categorize_path}\n  {ground_truth_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
