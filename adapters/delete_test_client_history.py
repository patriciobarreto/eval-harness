"""
Delete a test client's transaction list(s) in sb-ai -- including the vector
store embeddings, not just the DB rows. Needed before re-seeding: if a
previous seed run left transactions with missing/incomplete vector data
(e.g. a vector store disconnect mid-run), the old list has to actually be
gone before a fresh /add call can rebuild it cleanly.

Calls DELETE /api/bookkeeping/transactions/delete, which for each
transaction with a vectorId removes the embedding from the vector store
first (via backend-py), then the DB row, then the
TransactionCategorizationResult rows for the list, then the TransactionList
itself once every transaction is gone. A transaction with no vectorId (e.g.
one that never finished embedding) is deleted from the DB directly, vector
step skipped since there's nothing there to remove.

Usage:
    python adapters/delete_test_client_history.py \\
        --client-config adapters/test_clients/client1_test/client.json

Deletes every transaction list currently associated with that client. Pass
--transaction-list-id to target just one instead.

Requires SB_AI_URL and SB_AI_API_KEY in the environment.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from _sb_ai_client import delete_transaction_list, get_transaction_list_summaries

POLL_INTERVAL_SECONDS = 5
DEFAULT_POLL_TIMEOUT_SECONDS = 300


def _wait_until_gone(external_client_id: str, transaction_list_id: str, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        remaining_ids = {s["id"] for s in get_transaction_list_summaries(external_client_id)}
        if transaction_list_id not in remaining_ids:
            print(f"  {transaction_list_id} gone.")
            return
        print(f"  still deleting {transaction_list_id}...")
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(
        f"{transaction_list_id} was not fully deleted within {timeout_seconds}s -- "
        "it may still be processing in the background, check again later."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-config", required=True, type=Path)
    parser.add_argument(
        "--transaction-list-id",
        help="Delete just this list instead of every list currently on the client.",
    )
    parser.add_argument("--poll-timeout", type=float, default=DEFAULT_POLL_TIMEOUT_SECONDS)
    args = parser.parse_args()

    config = json.loads(args.client_config.read_text())
    external_client_id = config["externalClientId"]

    if args.transaction_list_id:
        target_ids = [args.transaction_list_id]
    else:
        summaries = get_transaction_list_summaries(external_client_id)
        target_ids = [s["id"] for s in summaries]
        if not target_ids:
            print(f"No transaction lists found for {external_client_id}. Nothing to delete.")
            return
        print(f"Found {len(target_ids)} transaction list(s) for {external_client_id}: {target_ids}")

    for transaction_list_id in target_ids:
        print(f"Deleting {transaction_list_id}...")
        result = delete_transaction_list(external_client_id, transaction_list_id)
        print(f"  queued: {result}")
        _wait_until_gone(external_client_id, transaction_list_id, args.poll_timeout)

    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
