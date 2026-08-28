# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Golden-dataset regression testing for LLM-powered agents. It runs an agent against a set of known-good examples and fails the build if anything that used to pass stops passing. The harness itself is agent-agnostic: it only knows about `eval_harness.Agent`, a one-method protocol (`run(input: dict) -> dict`). This repo ships a small demo agent (`demo/ticket_classifier.py`, a keyword-based support-ticket classifier) and a synthetic golden dataset (`demo/fixtures/*.yaml`) so it runs standalone with no API key.

## Commands

```bash
pip install -e .              # install package + deps
pytest tests/ -v               # run the full suite
pytest tests/test_runner.py::test_no_regressions -v   # the one CI actually gates on
pytest tests/test_runner.py::test_judge_gives_partial_credit_for_reasonable_alternative -v  # run a single test
pip install -e ".[anthropic]"  # add the anthropic extra, needed for AnthropicJudge
```

There is no lint/format/typecheck tooling configured in this repo.

## Architecture

Pipeline: `fixtures.load_fixtures()` → `runner.run(agent, fixtures, judge)` → per-fixture `scoring.score_fixture()` → `RunReport`.

- **`agent_protocol.py`** — the single interface (`Agent.run`) the harness depends on. Deliberately kept generic (input dict in, output dict out); agent-specific structure belongs in the agent's own output, never added here.
- **`fixtures.py`** — loads one YAML file per golden example from a directory. Each fixture has `input`, `expected_output`, a `scoring` dict (field name → `"exact"` | `"judge"`), and a `baseline_score`.
- **`judge.py`** — LLM-as-judge, kept deliberately separate from exact match. Exact match answers "is this identical"; judge answers "is this a clear miss or a reasonable alternative" (only meaningful for fields where more than one answer can be defensible, e.g. category labels). Two implementations: `FakeJudge` (deterministic, hardcoded `REASONABLE_ALTERNATIVES` pairs, no API calls — used by tests and the demo) and `AnthropicJudge` (real API call per judged field, lazy-imports `anthropic` so the module loads without the package installed).
- **`scoring.py`** — grades one (expected, actual) pair field by field per the fixture's `scoring` dict, never mixing exact/judge within a field. Fixture's overall score is a flat average across its field scores (no field weighting yet).
- **`runner.py`** — orchestrates: for every fixture, call `agent.run()`, score the result, collect into a `RunReport`. `RunReport.regressed` fixtures are those scoring below their stored `baseline_score`.
- **`demo/ticket_classifier.py`** — the demo agent, a pure keyword-match classifier (no LLM call) standing in for a real production classifier, wired to the harness via the `Agent` protocol.

### Adding your own agent

Write an adapter implementing `Agent.run()` that wraps the real agent, point `load_fixtures()` at your own fixtures directory, and choose a judge. The harness never imports agent code directly or touches production data — it only calls `.run()` and scores what comes back.

### Fixture scoring notes

- `baseline_score` is not always `1.0`. See `demo/fixtures/ticket_007.yaml`: a deliberately ambiguous ticket where the judge path awards partial credit (0.5) as the expected, non-regressed outcome — a scoring bug that always returns 1.0 would make this kind of case (and all future regressions) invisible, which is why `test_runner.py` also unit-tests scoring and the judge directly, not just the end-to-end run.
- `FakeJudge.REASONABLE_ALTERNATIVES` is a fixed set of category pairs for the demo domain only; expand it per-domain when adapting the judge for a different agent.

## CI

`.github/workflows/eval.yml` runs `pytest tests/ -v` on every PR and push to `main`, comments the result on the PR, and optionally notifies Slack on failure (via `SLACK_WEBHOOK_URL` secret).

## Known gaps (from README)

- `AnthropicJudge` is untested against a live API key in this repo's own CI (the demo is designed for zero external dependencies); `FakeJudge` stands in for demo/test purposes.
- No per-field weighting; every fixture's score is a flat average across its scored fields.
