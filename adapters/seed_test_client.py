"""
Seed a dedicated test client's transaction history in sb-ai, so the real
categorizer has something to run its similarity search against.

Calls the public add-transactions API (not the internal Python endpoint),
which is what actually creates the Client row via getClientOrCreate. Writes
real rows to the sb-ai database -- only ever point --external-client-id at a
client ID you've made up for this purpose, never a real user's.

CSV columns expected (header row required):
    qbTransactionId, date, amount, qbTransactionType, bankDetail, qbCategoryName, qbCategoryId

    - date: any ISO-parseable date, e.g. 2026-01-15
    - amount: signed dollars, e.g. -45.99 (matches how QB exports typically look)
    - qbCategoryName / qbCategoryId: the category this historical transaction
      was actually filed under -- required for history rows, since this is
      what similarity search will draw on later. Leave blank only if you
      really don't know (it'll be filed as uncategorized history, which is
      of limited use for grounding future categorizations).

Usage (identity flags spelled out):
    python adapters/seed_test_client.py \\
        --csv history.csv \\
        --external-client-id eval-harness-test-client-001 \\
        --first-name Eval --last-name Harness --email eval-harness@example.test

Usage (--client-config, so seeding and later categorize test runs are
guaranteed to use the same externalClientId -- see build_fixture_drafts.py,
which reads the same file):
    python adapters/seed_test_client.py \\
        --csv adapters/test_clients/client1_test/history.csv \\
        --client-config adapters/test_clients/client1_test/client.json

Requires SB_AI_URL and SB_AI_API_KEY in the environment.
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path

from _sb_ai_client import add_transactions, determine_direction, get_transaction_list_summaries

POLL_INTERVAL_SECONDS = 5
DEFAULT_POLL_TIMEOUT_SECONDS = 300


def _read_transactions_csv(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"no rows found in {path}")

    transactions = []
    for row in rows:
        amount_dollars = float(row["amount"])
        transactions.append(
            {
                "qbTransactionId": row["qbTransactionId"],
                "date": row["date"],
                "amountInCents": round(amount_dollars * 100),
                "qbTransactionType": row["qbTransactionType"],
                "bankDetail": row["bankDetail"],
                "direction": determine_direction(amount_dollars, row["qbTransactionType"]),
                "qbCategoryName": row.get("qbCategoryName") or None,
                "qbCategoryId": int(row["qbCategoryId"]) if row.get("qbCategoryId") else None,
            }
        )
    return transactions


def _wait_until_processed(
    external_client_id: str, expected_count: int, timeout_seconds: float
) -> None:
    """
    /add processes transactions asynchronously (embeddings + normalization
    via backend-py). Poll getMany, which only returns completed lists, until
    a list with at least expected_count transactions shows up.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        summaries = get_transaction_list_summaries(external_client_id)
        if any(s["transactionCount"] >= expected_count for s in summaries):
            print("Processing complete.")
            return
        print(
            f"Still processing... ({len(summaries)} completed list(s) so far, "
            f"waiting for one with >= {expected_count} transactions)"
        )
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(
        f"Transactions for {external_client_id} were not marked completed within "
        f"{timeout_seconds}s. They may still be processing in the background -- "
        "check again later, or rerun with --poll-timeout set higher."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument(
        "--client-config",
        type=Path,
        help="JSON file with externalClientId/firstName/lastName/email (see "
        "adapters/test_clients/*/client.json). Fills in any of the flags below "
        "left unset; pass both to override just one field.",
    )
    parser.add_argument("--external-client-id")
    parser.add_argument("--first-name")
    parser.add_argument("--last-name")
    parser.add_argument("--email")
    parser.add_argument("--list-class", default="History", choices=["History", "Categorizer", "BvP"])
    parser.add_argument("--poll-timeout", type=float, default=DEFAULT_POLL_TIMEOUT_SECONDS)
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Don't poll for background processing to finish before exiting.",
    )
    args = parser.parse_args()

    if args.client_config:
        config = json.loads(args.client_config.read_text())
        args.external_client_id = args.external_client_id or config.get("externalClientId")
        args.first_name = args.first_name or config.get("firstName")
        args.last_name = args.last_name or config.get("lastName")
        args.email = args.email or config.get("email")

    missing = [
        flag
        for flag, value in [
            ("--external-client-id", args.external_client_id),
            ("--first-name", args.first_name),
            ("--last-name", args.last_name),
            ("--email", args.email),
        ]
        if not value
    ]
    if missing:
        raise ValueError(
            f"missing required value(s): {', '.join(missing)} "
            "(pass the flag directly or via --client-config)"
        )

    transactions = _read_transactions_csv(args.csv)
    print(f"Loaded {len(transactions)} transactions from {args.csv}")

    result = add_transactions(
        external_client_id=args.external_client_id,
        first_name=args.first_name,
        last_name=args.last_name,
        email=args.email,
        transactions=transactions,
        list_class=args.list_class,
    )
    print(f"Queued: {result}")

    if args.no_wait:
        print("Skipping wait (--no-wait). Check status later with getMany.")
        return

    _wait_until_processed(args.external_client_id, len(transactions), args.poll_timeout)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
