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
from .scoring import ScoreResult, score_agent_error, score_fixture


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
            line = f"  [{marker}] {r.fixture_id}: {r.score:.2f} (baseline {r.baseline_score:.2f})"
            if r.error:
                line += f" -- agent raised {r.error}"
            lines.append(line)
        return "\n".join(lines)


def run(agent: Agent, fixtures: list[Fixture], judge: Judge) -> RunReport:
    results = []
    for fixture in fixtures:
        try:
            actual_output = agent.run(fixture.input)
        except Exception as exc:
            # A single fixture crashing the agent shouldn't crash the whole
            # eval run -- record it as a failing result and keep going.
            results.append(score_agent_error(fixture, exc))
            continue
        results.append(score_fixture(fixture, actual_output, judge))
    return RunReport(results=results)
