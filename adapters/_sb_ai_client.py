"""
Shared helpers for talking to sb-ai's public REST API (the same one the
Next.js app calls via SB_AI_URL / SB_AI_API_KEY) -- used by
seed_test_client.py and build_fixture_drafts.py.

Unlike transaction_categorizer.py (which calls backend-py's internal
inference endpoint directly and never touches the DB), these two scripts
go through the front door on purpose: seeding history needs the real
DB-backed pipeline, and fixture drafts need the real TS retrieval and
prompt-building path. Draft generation uses persist=false so it can return
the production prompt shape without creating categorization review rows.
That's why this is script tooling to run by hand against a dedicated test
client, not something wired into the eval harness's own CI run.
"""

import os
from typing import Any

import requests

SB_AI_URL = os.environ.get("SB_AI_URL")
SB_AI_API_KEY = os.environ.get("SB_AI_API_KEY")


def _require_config() -> None:
    if not SB_AI_URL:
        raise ValueError("SB_AI_URL must be set")


def _headers() -> dict[str, str]:
    return {"Content-Type": "application/json", "X-API-Key": SB_AI_API_KEY or ""}


def determine_direction(amount_dollars: float, qb_transaction_type: str) -> str:
    """Mirrors determineDirection() in the app's addTransactions server action."""
    if amount_dollars < 0:
        return "debit"

    lowered = qb_transaction_type.lower()
    if any(w in lowered for w in ("expense", "payment", "purchase", "withdrawal")):
        return "debit"
    if any(w in lowered for w in ("deposit", "income", "revenue", "refund")):
        return "credit"

    return "credit" if amount_dollars >= 0 else "debit"


def add_transactions(
    external_client_id: str,
    first_name: str,
    last_name: str,
    email: str,
    transactions: list[dict[str, Any]],
    list_class: str = "History",
) -> dict[str, Any]:
    """
    POST /api/bookkeeping/transactions/add.

    This is the call that creates the Client row if externalClientId doesn't
    exist yet (getClientOrCreate). Processing happens in the background on
    the server -- use wait_for_transactions_processed() afterward before
    relying on this history for similarity search.
    """
    _require_config()
    response = requests.post(
        f"{SB_AI_URL}/api/bookkeeping/transactions/add",
        json={
            "externalClientId": external_client_id,
            "firstName": first_name,
            "lastName": last_name,
            "email": email,
            "listClass": list_class,
            "transactions": transactions,
        },
        headers=_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def get_transaction_list_summaries(external_client_id: str) -> list[dict[str, Any]]:
    """GET /api/bookkeeping/transactions/getMany -- only completed lists are returned."""
    _require_config()
    response = requests.get(
        f"{SB_AI_URL}/api/bookkeeping/transactions/getMany",
        params={"externalClientId": external_client_id},
        headers=_headers(),
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("success"):
        raise RuntimeError(f"getMany returned success=false: {data}")
    return data["transactionListsSummaries"]


def delete_transaction_list(external_client_id: str, transaction_list_id: str) -> dict[str, Any]:
    """
    DELETE /api/bookkeeping/transactions/delete.

    For each transaction with a vectorId, deletes the embedding from the
    vector store first (via backend-py), then the DB row, then the
    TransactionCategorizationResult rows for the list, then the
    TransactionList itself once every transaction is gone. Runs in the
    background server-side (returns 202 immediately) -- poll
    get_transaction_list_summaries() and wait for the list to disappear
    before treating deletion as done.
    """
    _require_config()
    response = requests.delete(
        f"{SB_AI_URL}/api/bookkeeping/transactions/delete",
        json={"externalClientId": external_client_id, "transactionListId": transaction_list_id},
        headers=_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def categorize_transactions(
    external_client_id: str,
    client_profession: str,
    transactions: list[dict[str, Any]],
    categories: list[dict[str, Any]],
    llm_provider: str,
    llm_model: str,
) -> dict[str, Any]:
    """
    POST /api/bookkeeping/transactions/categorize.

    Runs the TS categorizer in preview mode. It still resolves the test
    client, reads historical transactions, performs vector similarity
    search, builds the production prompts, and calls the LLM, but it does
    not create TransactionList, CategorizationAgentExecution, or
    TransactionCategorizationResult rows.
    """
    _require_config()
    response = requests.post(
        f"{SB_AI_URL}/api/bookkeeping/transactions/categorize",
        json={
            "externalClientId": external_client_id,
            "clientProfession": client_profession,
            "transactions": transactions,
            "categories": categories,
            "llmProvider": llm_provider,
            "llmModel": llm_model,
            "persist": False,
        },
        headers=_headers(),
        timeout=300,
    )
    response.raise_for_status()
    return response.json()
