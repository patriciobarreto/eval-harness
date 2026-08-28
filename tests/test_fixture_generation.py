"""
Tests for the fixture-generation tooling (adapters/_sb_ai_client.py,
adapters/build_fixture_drafts.py). No network calls -- these only exercise
the pure mapping logic, not the scripts' HTTP calls.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "adapters"))

from _sb_ai_client import determine_direction
from build_fixture_drafts import _draft_fixture_from_response

CATEGORIES = [{"id": 42, "name": "Office Supplies", "classification": "Expense"}]


def test_determine_direction_negative_amount_is_debit():
    assert determine_direction(-45.99, "Expense") == "debit"


def test_determine_direction_positive_expense_type_is_debit():
    # Mirrors the TS server action: a positive amount with an expense-like
    # qbTransactionType is still a debit, the sign alone isn't decisive.
    assert determine_direction(45.99, "Expense Payment") == "debit"


def test_determine_direction_positive_deposit_type_is_credit():
    assert determine_direction(200.00, "Deposit") == "credit"


def test_determine_direction_positive_unknown_type_defaults_credit():
    assert determine_direction(10.00, "Journal Entry") == "credit"


def _fake_categorize_response():
    return {
        "success": True,
        "results": [
            {
                "success": True,
                "qbTransactionId": "txn_1",
                "systemInstructions": "You are a categorizer.",
                "userPrompt": "Categorize this: STAPLES #4821",
                "model": "claude-sonnet-4-5-20250929",
                "qbTransaction": {
                    "qbTransactionId": "txn_1",
                    "bankDetail": "STAPLES #4821",
                    "amountInCents": -4599,
                    "direction": "debit",
                    "date": "2026-01-15",
                    "qbTransactionType": "Expense",
                    "qbCategory": {"id": 42, "name": "Office Supplies", "classification": "Expense"},
                },
            }
        ],
    }


def test_draft_fixture_pulls_prompt_from_preview_result():
    fixture = _draft_fixture_from_response("draft_001", CATEGORIES, _fake_categorize_response())

    assert fixture["id"] == "draft_001"
    txn = fixture["input"]["transactions"][0]
    assert txn["systemInstructions"] == "You are a categorizer."
    assert txn["userPrompt"] == "Categorize this: STAPLES #4821"
    assert txn["llmModel"] == "claude-sonnet-4-5-20250929"
    assert txn["llmProvider"] == "anthropic"


def test_draft_fixture_expected_output_and_scoring_keyed_by_transaction_id():
    fixture = _draft_fixture_from_response("draft_001", CATEGORIES, _fake_categorize_response())

    assert fixture["expected_output"] == {"txn_1": "Office Supplies"}
    assert fixture["scoring"] == {"txn_1": "exact"}
