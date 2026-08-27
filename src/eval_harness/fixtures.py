"""
Golden dataset fixtures: one YAML file per example.

Each fixture is a single known-good case, an input the agent will see and
the output it should produce. The schema is deliberately small. Everything
scoring needs to know about how strict to be on each field lives in
`scoring`, not scattered across the fixture as ad hoc flags.

Example fixture (demo/fixtures/ticket_001.yaml):

    id: ticket_001
    input:
      subject: "Charged twice for my subscription"
      body: "I see two charges on my card this month for the same plan."
    expected_output:
      category: "billing"
    scoring:
      category: exact
    baseline_score: 1.0
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Fixture:
    id: str
    input: dict[str, Any]
    expected_output: dict[str, Any]
    scoring: dict[str, str]  # field name -> "exact" | "judge"
    baseline_score: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Fixture":
        required = {"id", "input", "expected_output", "scoring"}
        missing = required - data.keys()
        if missing:
            raise ValueError(f"fixture missing required keys: {missing}")
        return cls(
            id=data["id"],
            input=data["input"],
            expected_output=data["expected_output"],
            scoring=data["scoring"],
            baseline_score=float(data.get("baseline_score", 1.0)),
        )


def load_fixtures(directory: str | Path) -> list[Fixture]:
    """Load every .yaml fixture in a directory, sorted by filename for stable ordering."""
    directory = Path(directory)
    paths = sorted(directory.glob("*.yaml"))
    if not paths:
        raise FileNotFoundError(f"no .yaml fixtures found in {directory}")

    fixtures = []
    for path in paths:
        with open(path) as f:
            data = yaml.safe_load(f)
        fixtures.append(Fixture.from_dict(data))
    return fixtures
