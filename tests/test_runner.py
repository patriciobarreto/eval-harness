"""
This is the file that actually proves the harness works end to end.

`test_no_regressions` is the one you'd run in CI: load the golden dataset,
run it through the demo agent, fail if anything scores below its baseline.
The other tests exercise scoring and the judge directly, since those are
where a silent bug would be most costly (a scoring bug that always
returns 1.0 would make every future regression invisible).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "demo"))

from eval_harness import AnthropicJudge, Fixture, FakeJudge, load_fixtures, run, score_fixture
from ticket_classifier import TicketClassifier

FIXTURES_DIR = Path(__file__).parent.parent / "demo" / "fixtures"


def test_fixtures_load():
    fixtures = load_fixtures(FIXTURES_DIR)
    assert len(fixtures) == 8
    assert {f.id for f in fixtures} == {f"ticket_{i:03d}" for i in range(1, 9)}


def test_exact_match_scoring():
    fixtures = load_fixtures(FIXTURES_DIR)
    billing_fixture = next(f for f in fixtures if f.id == "ticket_001")
    result = score_fixture(billing_fixture, {"category": "billing"}, FakeJudge())
    assert result.score == 1.0
    assert not result.regressed


def test_exact_match_catches_a_wrong_answer():
    fixtures = load_fixtures(FIXTURES_DIR)
    billing_fixture = next(f for f in fixtures if f.id == "ticket_001")
    result = score_fixture(billing_fixture, {"category": "technical"}, FakeJudge())
    assert result.score == 0.0
    assert result.regressed


def test_judge_gives_partial_credit_for_reasonable_alternative():
    fixtures = load_fixtures(FIXTURES_DIR)
    ambiguous_fixture = next(f for f in fixtures if f.id == "ticket_007")
    # The classifier predicts "billing" here, expected is "account", these
    # two are in the judge's reasonable-alternatives set.
    result = score_fixture(ambiguous_fixture, {"category": "billing"}, FakeJudge())
    assert result.score == 0.5
    assert not result.regressed  # baseline_score for this fixture is 0.5


def test_no_regressions():
    """The actual CI check: run every fixture through the real demo agent."""
    fixtures = load_fixtures(FIXTURES_DIR)
    agent = TicketClassifier()
    judge = FakeJudge()

    report = run(agent, fixtures, judge)

    assert report.passed, f"\n{report.summary()}"


def test_scoring_a_field_missing_from_expected_output_is_rejected():
    """
    A `scoring` key with no matching key in `expected_output` is almost
    always a typo. Without this check both sides default to None and the
    field scores 1.0 forever, no matter what the agent returns.
    """
    with pytest.raises(ValueError, match="not present in expected_output"):
        Fixture.from_dict(
            {
                "id": "ticket_typo",
                "input": {"subject": "x", "body": "y"},
                "expected_output": {"category": "billing"},
                "scoring": {"categroy": "exact"},  # typo: doesn't match expected_output
            }
        )


class _ExplodingAgent:
    def run(self, input):
        raise RuntimeError("boom")


def test_agent_exception_fails_that_fixture_without_crashing_the_run():
    fixtures = load_fixtures(FIXTURES_DIR)
    report = run(_ExplodingAgent(), fixtures, FakeJudge())

    assert not report.passed
    assert len(report.results) == len(fixtures)
    assert all(r.score == 0.0 and r.error is not None for r in report.results)


class _FakeAnthropicResponse:
    def __init__(self, text):
        self.content = [type("Block", (), {"text": text})()]


class _FakeAnthropicClient:
    def __init__(self, verdict):
        self._verdict = verdict
        self.messages = self

    def create(self, **kwargs):
        return _FakeAnthropicResponse(self._verdict)


@pytest.mark.parametrize(
    "verdict,expected_score",
    [("MATCH", 1.0), ("PARTIAL", 0.5), ("MISS", 0.0)],
)
def test_anthropic_judge_maps_verdicts_to_scores(verdict, expected_score):
    """
    AnthropicJudge must honor the same 1.0/0.5/0.0 contract as FakeJudge
    (per the Judge protocol) -- a MATCH/MISS-only judge silently drops
    partial credit for fixtures like ticket_007 that rely on it.
    """
    judge = AnthropicJudge()
    judge._client = _FakeAnthropicClient(verdict)

    score = judge.score("category", {"subject": "x"}, "account", "billing")

    assert score == expected_score
