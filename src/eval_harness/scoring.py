"""
Turns one (expected, actual) pair into a score, field by field.

Each fixture's `scoring` dict says how to grade each field: "exact" for
anything with one right answer, "judge" for anything where a reasonable
alternative should count for partial credit. The two paths never mix
within a single field, only across fields in the same fixture.

The overall fixture score is the average of its field scores. That's a
deliberately simple aggregation, if you need weighted fields later
(some matter more than others), that's a small change here, not a
redesign of the pipeline.
"""

from dataclasses import dataclass
from typing import Any

from .fixtures import Fixture
from .judge import Judge


@dataclass
class FieldResult:
    field: str
    method: str  # "exact" | "judge"
    expected: Any
    actual: Any
    score: float


@dataclass
class ScoreResult:
    fixture_id: str
    field_results: list[FieldResult]
    score: float
    baseline_score: float

    @property
    def regressed(self) -> bool:
        return self.score < self.baseline_score


def score_fixture(fixture: Fixture, actual_output: dict[str, Any], judge: Judge) -> ScoreResult:
    field_results = []

    for field, method in fixture.scoring.items():
        expected = fixture.expected_output.get(field)
        actual = actual_output.get(field)

        if method == "exact":
            score = 1.0 if expected == actual else 0.0
        elif method == "judge":
            score = judge.score(field, fixture.input, expected, actual)
        else:
            raise ValueError(f"unknown scoring method '{method}' for field '{field}'")

        field_results.append(
            FieldResult(field=field, method=method, expected=expected, actual=actual, score=score)
        )

    overall = sum(r.score for r in field_results) / len(field_results)

    return ScoreResult(
        fixture_id=fixture.id,
        field_results=field_results,
        score=overall,
        baseline_score=fixture.baseline_score,
    )
