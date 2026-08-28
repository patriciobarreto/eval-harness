"""
Run the real categorizer against every test client's held-out transactions
and report exact-match accuracy against ground truth -- numbers only, no
fixture files written.

For each client directory (adapters/test_clients/*_test/, must already be
seeded -- see seed_test_client.py): calls /categorize on to_categorize.csv
the same way build_fixture_drafts.py does, then compares each proposed
category against ground_truth.csv by qbTransactionId.

Two numbers per client:
  - transactions categorized: how many got a real category proposal rather
    than "Uncategorized" (coverage -- did the model attempt one at all)
  - categorized correctly: of those, how many matched ground truth exactly
    (precision on the transactions it was willing to categorize)

Usage:
    python adapters/run_categorizer_eval.py --llm-model claude-haiku-4-5-20251001

    # just one or two clients instead of every adapters/test_clients/*_test/ dir:
    python adapters/run_categorizer_eval.py --llm-model claude-haiku-4-5-20251001 \\
        --client-dir adapters/test_clients/client1_test

Requires SB_AI_URL and SB_AI_API_KEY in the environment.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from _sb_ai_client import categorize_transactions
from build_fixture_drafts import _chunks, _read_transactions_csv

TEST_CLIENTS_DIR = Path(__file__).parent / "test_clients"
DEFAULT_BATCH_SIZE = 10


def _load_ground_truth(path: Path) -> dict[str, str]:
    with open(path, newline="") as f:
        return {row["qbTransactionId"]: row["qbCategoryName"] for row in csv.DictReader(f)}


def _run_client(client_dir: Path, llm_provider: str, llm_model: str, batch_size: int) -> dict:
    config = json.loads((client_dir / "client.json").read_text())
    categories = json.loads((client_dir / "categories.json").read_text())
    transactions = _read_transactions_csv(client_dir / "to_categorize.csv")
    ground_truth = _load_ground_truth(client_dir / "ground_truth.csv")

    total = len(transactions)
    categorized = 0
    correct = 0

    for batch_num, batch in enumerate(_chunks(transactions, batch_size), start=1):
        print(
            f"  [{client_dir.name}] batch {batch_num} ({len(batch)} transactions)...",
            file=sys.stderr,
        )
        response = categorize_transactions(
            external_client_id=config["externalClientId"],
            client_profession=config["clientProfession"],
            transactions=batch,
            categories=categories,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
        for result in response["results"]:
            txn = result["qbTransaction"]
            txn_id = result.get("qbTransactionId") or txn["qbTransactionId"]
            proposed = txn["qbCategory"]["name"]
            if proposed != "Uncategorized":
                categorized += 1
                if proposed == ground_truth.get(txn_id):
                    correct += 1

    return {"total": total, "categorized": categorized, "correct": correct}


def _report(label: str, stats: dict) -> None:
    total, categorized, correct = stats["total"], stats["categorized"], stats["correct"]
    cat_pct = (categorized / total * 100) if total else 0.0
    correct_pct = (correct / categorized * 100) if categorized else 0.0
    print(f"{label}:")
    print(f"  {categorized}/{total} transactions categorized ({cat_pct:.0f}%)")
    print(f"  {correct}/{categorized} categorized correctly ({correct_pct:.0f}%)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm-provider", default="anthropic", choices=["anthropic", "openai"])
    parser.add_argument("--llm-model", required=True)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--client-dir",
        action="append",
        type=Path,
        help="Repeatable. Defaults to every adapters/test_clients/*_test/ directory.",
    )
    args = parser.parse_args()

    client_dirs = args.client_dir or sorted(
        d for d in TEST_CLIENTS_DIR.iterdir() if d.is_dir() and (d / "client.json").exists()
    )
    if not client_dirs:
        raise ValueError(f"no test client directories found under {TEST_CLIENTS_DIR}")

    totals = {"total": 0, "categorized": 0, "correct": 0}
    for client_dir in client_dirs:
        stats = _run_client(client_dir, args.llm_provider, args.llm_model, args.batch_size)
        _report(client_dir.name, stats)
        for key in totals:
            totals[key] += stats[key]
        print()

    _report("combined", totals)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
