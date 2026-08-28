"""
Adapter wrapping the Soundboard transaction-categorizer agent for the eval harness.

Calls the Python inference service directly (backend-py's
`/api/bookkeeping/transactions/categorize`), not the TypeScript layer. That
matters: the TS controller (categorizeTransactions.ts) calls this same
endpoint and then writes a CategorizationAgentExecution + TransactionList
row to production for every transaction. The Python endpoint itself does no
DB writes, it only calls the LLM and parses the response, so calling it
directly here is safe to run repeatedly from CI with zero risk of touching
production data.

The tradeoff: this endpoint doesn't build its own prompt. `systemInstructions`
and `userPrompt` must already be assembled (normally done in TS from a live
vector search over the client's transaction history plus DB-stored agent
config). Fixtures for this adapter carry a frozen snapshot of a real,
human-verified categorization: the exact `promptSent` / `systemInstructions`
values TS already persists to CategorizationAgentExecution for every past
run. That way each fixture tests the piece that actually regresses (the LLM
categorization call) without reimplementing retrieval logic that would drift
out of sync with production. See adapters/README.md for how to build fixtures.

One fixture holds a batch of transactions. `run()` returns one category name
per transaction, keyed by qbTransactionId, so a fixture's `expected_output`
and `scoring` dicts are keyed by transaction ID too, one per transaction in
the batch. No changes to the harness itself were needed for this: each
transaction ID is just an ordinary scored field.
"""

import os
from typing import Any

import requests

DEFAULT_TIMEOUT_SECONDS = 30


class TransactionCategorizerAgent:
    """
    Wraps backend-py's /api/bookkeeping/transactions/categorize endpoint.

    Requires PYTHON_BACKEND_URL (or BACKEND_PY_URL) and INTERNAL_SERVICE_KEY
    in the environment, matching sb-ai's own ResilientPythonClient config
    (see backend-ts/src/lib/resilient-client.ts).
    """

    def __init__(
        self,
        base_url: str | None = None,
        service_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.base_url = (
            base_url
            or os.environ.get("PYTHON_BACKEND_URL")
            or os.environ.get("BACKEND_PY_URL")
        )
        if not self.base_url:
            raise ValueError(
                "TransactionCategorizerAgent needs PYTHON_BACKEND_URL "
                "(or BACKEND_PY_URL) set"
            )
        self.service_key = service_key or os.environ.get("INTERNAL_SERVICE_KEY", "")
        self.timeout = timeout

    def run(self, input: dict[str, Any]) -> dict[str, Any]:
        """
        input:
            {
              "categories": [{"id": int, "name": str, "classification": str}, ...],
              "transactions": [
                {
                  "qbTransactionId": str,
                  "bankDetail": str,
                  "amountInCents": int,
                  "direction": "debit" | "credit",
                  "date": str,
                  "qbTransactionType": str,
                  "systemInstructions": str,  # frozen CategorizationAgentExecution snapshot
                  "userPrompt": str,          # frozen CategorizationAgentExecution snapshot
                  "llmProvider": "anthropic" | "openai",
                  "llmModel": str,
                },
                ...
              ],
            }

        Returns one category name per transaction, keyed by qbTransactionId:
            {"txn_1": "Meals & Entertainment", "txn_2": "Office Supplies", ...}

        A transaction whose API call fails is returned as None rather than
        raising, so one bad transaction in a batch doesn't take the rest of
        the fixture's transactions down with it -- scoring will still
        correctly mark that one transaction a miss against its expected
        category.
        """
        categories = input["categories"]
        return {
            txn["qbTransactionId"]: self._categorize_one(txn, categories)
            for txn in input["transactions"]
        }

    def _categorize_one(
        self, txn: dict[str, Any], categories: list[dict[str, Any]]
    ) -> str | None:
        body = {
            "transaction": {
                "qbTransactionId": txn["qbTransactionId"],
                "bankDetail": txn["bankDetail"],
                "amountInCents": txn["amountInCents"],
                "direction": txn["direction"],
                "date": txn["date"],
                "qbTransactionType": txn["qbTransactionType"],
            },
            "systemInstructions": txn["systemInstructions"],
            "userPrompt": txn["userPrompt"],
            "llmProvider": txn["llmProvider"],
            "llmModel": txn["llmModel"],
        }

        try:
            response = requests.post(
                f"{self.base_url}/api/bookkeeping/transactions/categorize",
                json=body,
                headers={"Internal-Service-Key": self.service_key},
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            return None

        if not data.get("success"):
            return None

        return self._map_category_name(data.get("categoryId"), categories)

    @staticmethod
    def _map_category_name(category_id: Any, categories: list[dict[str, Any]]) -> str:
        """
        Mirrors mapQbCategory() in categorizeTransactions.ts: the Python
        endpoint's `categoryName` field is never actually populated on
        success (only `categoryId` is), so name resolution has to happen
        on this side too.
        """
        if category_id is not None:
            for category in categories:
                if category["id"] == int(category_id):
                    return category["name"]
        return "Uncategorized"
