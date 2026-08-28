"""
Tests for the transaction-categorizer adapter (adapters/transaction_categorizer.py).

These mock the HTTP call to backend-py, so they run offline like the rest of
this repo's suite -- no PYTHON_BACKEND_URL or INTERNAL_SERVICE_KEY needed.
Nothing here calls the real, deployed service.
"""

import sys
from pathlib import Path
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "adapters"))

from eval_harness import load_fixtures
from transaction_categorizer import TransactionCategorizerAgent

ADAPTER_FIXTURES_DIR = Path(__file__).parent.parent / "adapters" / "fixtures"

CATEGORIES = [
    {"id": 42, "name": "Office Supplies", "classification": "Expense"},
    {"id": 43, "name": "Meals & Entertainment", "classification": "Expense"},
]


def _agent():
    return TransactionCategorizerAgent(
        base_url="https://fake-backend-py.internal", service_key="test-key"
    )


def _transaction(**overrides):
    txn = {
        "qbTransactionId": "txn_1",
        "bankDetail": "STAPLES STORE #4821",
        "amountInCents": -4599,
        "direction": "debit",
        "date": "2026-01-15",
        "qbTransactionType": "Expense",
        "systemInstructions": "You are a categorizer.",
        "userPrompt": "Categorize this transaction.",
        "llmProvider": "anthropic",
        "llmModel": "claude-sonnet-4-5-20250929",
    }
    txn.update(overrides)
    return txn


def _fake_response(json_body, status_ok=True):
    response = Mock()
    response.json.return_value = json_body
    if status_ok:
        response.raise_for_status.return_value = None
    else:
        response.raise_for_status.side_effect = requests.HTTPError("500")
    return response


def test_maps_returned_category_id_to_name():
    agent = _agent()
    with patch(
        "transaction_categorizer.requests.post",
        return_value=_fake_response({"success": True, "categoryId": 42}),
    ):
        result = agent.run(
            {"categories": CATEGORIES, "transactions": [_transaction()]}
        )

    assert result == {"txn_1": "Office Supplies"}


def test_unmatched_category_id_falls_back_to_uncategorized():
    agent = _agent()
    with patch(
        "transaction_categorizer.requests.post",
        return_value=_fake_response({"success": True, "categoryId": 9999}),
    ):
        result = agent.run(
            {"categories": CATEGORIES, "transactions": [_transaction()]}
        )

    assert result == {"txn_1": "Uncategorized"}


def test_api_success_false_returns_none_for_that_transaction():
    agent = _agent()
    with patch(
        "transaction_categorizer.requests.post",
        return_value=_fake_response({"success": False, "error": "LLM timeout"}),
    ):
        result = agent.run(
            {"categories": CATEGORIES, "transactions": [_transaction()]}
        )

    assert result == {"txn_1": None}


def test_request_exception_fails_only_that_transaction_not_the_whole_batch():
    agent = _agent()
    responses = [
        requests.ConnectionError("boom"),
        _fake_response({"success": True, "categoryId": 43}),
    ]

    def fake_post(*args, **kwargs):
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    with patch("transaction_categorizer.requests.post", side_effect=fake_post):
        result = agent.run(
            {
                "categories": CATEGORIES,
                "transactions": [
                    _transaction(qbTransactionId="txn_1"),
                    _transaction(qbTransactionId="txn_2"),
                ],
            }
        )

    assert result == {"txn_1": None, "txn_2": "Meals & Entertainment"}


def test_requires_base_url():
    import pytest

    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="PYTHON_BACKEND_URL"):
            TransactionCategorizerAgent()


def test_batch_fixture_template_parses_and_matches_the_batch_scoring_shape():
    """
    Not a live-agent run (the template's prompts are placeholders, not real
    snapshots) -- just confirms the batch-per-fixture schema described in
    adapters/README.md actually loads and lines up: one scoring/expected_output
    key per transaction in the batch.
    """
    fixtures = load_fixtures(ADAPTER_FIXTURES_DIR)
    batch_001 = next(f for f in fixtures if f.id == "batch_001")

    txn_ids = {t["qbTransactionId"] for t in batch_001.input["transactions"]}
    assert txn_ids == set(batch_001.expected_output.keys())
    assert txn_ids == set(batch_001.scoring.keys())
