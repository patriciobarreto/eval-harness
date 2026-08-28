"""
Run the real categorizer (through sb-ai's public API, against a dedicated
test client) and write out DRAFT eval-harness fixtures.

The category each draft fixture claims as `expected_output` is just the
model's own proposal for that transaction -- NOT verified ground truth.
Scoring a fixture against the same model's own guess is tautological and
would make it pass forever regardless of real regressions. Drafts land in
adapters/fixtures/drafts/, a subdirectory load_fixtures() never sees (it
only globs the fixtures/ dir itself), specifically so an unreviewed draft
can't accidentally get treated as a real golden example. A human must open
each draft, correct `expected_output` to what the category should actually
be, and move the file up into adapters/fixtures/ before it counts.

CSV columns expected (header row required):
    qbTransactionId, date, amount, qbTransactionType, bankDetail

Categories file: a JSON file containing a list of
    {"id": int, "name": str, "classification": str}
matching the client's real chart of accounts.

Usage (identity flags spelled out):
    python adapters/build_fixture_drafts.py \\
        --csv to_categorize.csv \\
        --categories categories.json \\
        --external-client-id eval-harness-test-client-001 \\
        --client-profession "Freelance graphic designer" \\
        --llm-model claude-haiku-4-5-20251001

Usage (--client-config, so this run is guaranteed to use the same
externalClientId that seed_test_client.py used to seed this client's
history -- see seed_test_client.py, which reads the same file):
    python adapters/build_fixture_drafts.py \\
        --csv adapters/test_clients/client1_test/to_categorize.csv \\
        --categories adapters/test_clients/client1_test/categories.json \\
        --client-config adapters/test_clients/client1_test/client.json \\
        --llm-model claude-haiku-4-5-20251001

Requires SB_AI_URL and SB_AI_API_KEY in the environment. The test client
must already exist (run seed_test_client.py first) so similarity search has
history to draw on.
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from _sb_ai_client import categorize_transactions, determine_direction

DEFAULT_BATCH_SIZE = 10
UNCATEGORIZED_PLACEHOLDER = {"id": 0, "name": "Uncategorized", "classification": "default"}


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
                "qbCategory": UNCATEGORIZED_PLACEHOLDER,
            }
        )
    return transactions


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _draft_fixture_from_response(
    fixture_id: str, categories: list[dict[str, Any]], response: dict[str, Any]
) -> dict[str, Any]:
    fixture_transactions = []
    expected_output = {}
    scoring = {}

    for result in response["results"]:
        txn = result["qbTransaction"]
        txn_id = result.get("qbTransactionId") or txn["qbTransactionId"]
        model = result.get("model")

        fixture_transactions.append(
            {
                "qbTransactionId": txn_id,
                "bankDetail": txn["bankDetail"],
                "amountInCents": txn["amountInCents"],
                "direction": txn["direction"],
                "date": txn["date"],
                "qbTransactionType": txn["qbTransactionType"],
                "systemInstructions": result.get("systemInstructions"),
                "userPrompt": result.get("userPrompt"),
                "llmProvider": "anthropic"
                if "claude" in str(model or "").lower()
                else "openai",
                "llmModel": model,
            }
        )
        expected_output[txn_id] = txn["qbCategory"]["name"]  # UNVERIFIED -- see module docstring
        scoring[txn_id] = "exact"

    return {
        "id": fixture_id,
        "input": {"categories": categories, "transactions": fixture_transactions},
        "expected_output": expected_output,
        "scoring": scoring,
        "baseline_score": 1.0,
    }


def _write_draft(fixture: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# UNVERIFIED DRAFT -- do not use as a golden fixture as-is.\n"
        "# expected_output currently holds the model's OWN proposed category for each\n"
        "# transaction, not confirmed ground truth. A human must review every entry\n"
        "# below, correct expected_output where the proposal was wrong, and move this\n"
        "# file out of drafts/ into adapters/fixtures/ before it's trustworthy.\n"
    )
    body = yaml.safe_dump(fixture, sort_keys=False, allow_unicode=True, width=100)
    out_path.write_text(header + body)
    print(f"Wrote {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--categories", required=True, type=Path)
    parser.add_argument(
        "--client-config",
        type=Path,
        help="JSON file with externalClientId/clientProfession (see "
        "adapters/test_clients/*/client.json) -- the same file seed_test_client.py "
        "reads, so both steps use the same externalClientId. Fills in any of the "
        "flags below left unset; pass both to override just one field.",
    )
    parser.add_argument("--external-client-id")
    parser.add_argument("--client-profession")
    parser.add_argument("--llm-provider", default="anthropic", choices=["anthropic", "openai"])
    parser.add_argument("--llm-model", required=True)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--id-prefix", default="draft")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).parent / "fixtures" / "drafts",
    )
    args = parser.parse_args()

    if args.client_config:
        config = json.loads(args.client_config.read_text())
        args.external_client_id = args.external_client_id or config.get("externalClientId")
        args.client_profession = args.client_profession or config.get("clientProfession")

    missing = [
        flag
        for flag, value in [
            ("--external-client-id", args.external_client_id),
            ("--client-profession", args.client_profession),
        ]
        if not value
    ]
    if missing:
        raise ValueError(
            f"missing required value(s): {', '.join(missing)} "
            "(pass the flag directly or via --client-config)"
        )

    transactions = _read_transactions_csv(args.csv)
    categories = json.loads(args.categories.read_text())
    print(f"Loaded {len(transactions)} transactions and {len(categories)} categories")

    for batch_index, batch in enumerate(_chunks(transactions, args.batch_size), start=1):
        print(f"Categorizing batch {batch_index} ({len(batch)} transactions)...")
        response = categorize_transactions(
            external_client_id=args.external_client_id,
            client_profession=args.client_profession,
            transactions=batch,
            categories=categories,
            llm_provider=args.llm_provider,
            llm_model=args.llm_model,
        )
        if not response.get("success"):
            print(f"  warning: batch {batch_index} had failures: {response}", file=sys.stderr)

        fixture_id = f"{args.id_prefix}_{batch_index:03d}"
        fixture = _draft_fixture_from_response(fixture_id, categories, response)
        _write_draft(fixture, args.out_dir / f"{fixture_id}.yaml")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
