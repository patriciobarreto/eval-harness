"""
Orchestration: for every fixture, run the agent, score the output, check
it against baseline. This is the piece that would be a manual, by-eye
comparison against CPA returns if you were doing it the old way. Here it's
one function call.
"""

from dataclasses import dataclass

from .agent_protocol import Agent
from .fixtures import Fixture
from .judge import Judge
from .scoring import ScoreResult, score_fixture


@dataclass
class RunReport:
    results: list[ScoreResult]

    @property
    def regressions(self) -> list[ScoreResult]:
        return [r for r in self.results if r.regressed]

    @property
    def passed(self) -> bool:
        return len(self.regressions) == 0

    def summary(self) -> str:
        lines = [f"{len(self.results)} fixtures, {len(self.regressions)} regressions"]
        for r in self.results:
            marker = "REGRESSION" if r.regressed else "ok"
            lines.append(f"  [{marker}] {r.fixture_id}: {r.score:.2f} (baseline {r.baseline_score:.2f})")
        return "\n".join(lines)


def run(agent: Agent, fixtures: list[Fixture], judge: Judge) -> RunReport:
    results = []
    for fixture in fixtures:
        actual_output = agent.run(fixture.input)
        results.append(score_fixture(fixture, actual_output, judge))
    return RunReport(results=results)
