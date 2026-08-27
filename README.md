# eval-harness

Golden-dataset regression testing for LLM-powered agents. Runs your agent against a set of known-good examples on every code change and fails the build if anything that used to pass, stops passing.

## Why this exists

Changing a prompt or swapping a model on an LLM-powered feature is a gamble without a way to measure it. It might get better at one thing and quietly worse at another, and there's often no way to know until a real output comes out wrong. The usual first fix is a human checking outputs by hand. This project turns that manual check into something that runs itself, the same way unit tests replaced manually clicking through an app before every release.

This repo ships with a small demo agent (a support-ticket classifier) and a synthetic golden dataset so it runs standalone with no setup and no API key. The harness itself doesn't know or care what agent it's testing, see "Using your own agent" below.

## How scoring works

Every fixture in the golden dataset can grade its fields two different ways:

- **Exact match**, for fields with exactly one right answer (a category from a fixed set, a dollar amount, a status code).
- **LLM-as-judge**, for fields where more than one answer can be defensible (is this classification a clear miss, or a reasonable alternative given the input).

These two paths are kept separate on purpose. Blending them into one fuzzy similarity score hides the difference between "wrong" and "arguably fine," which is exactly the distinction that matters when you're deciding whether a change actually broke something. See `demo/fixtures/ticket_007.yaml` for a case built specifically to exercise the judge path: a ticket that could reasonably be filed as either "billing" or "account."

## Running it

```bash
pip install -e .
pytest tests/ -v
```

`tests/test_runner.py::test_no_regressions` is the one that matters, it loads every fixture, runs it through the demo classifier, and fails if any fixture scores below its stored baseline.

## Using your own agent

The harness only knows about one interface (`eval_harness.Agent`):

```python
class Agent(Protocol):
    def run(self, input: dict) -> dict:
        ...
```

Write a small adapter that wraps your real agent to match this shape, point the harness at your own fixtures directory, and it runs the same way it runs against the demo classifier here. The harness never imports your agent's code or touches your production data, it just calls `.run()` and scores what comes back.

I run a version of this against a production transaction-categorization pipeline, with the golden dataset built from user-verified categories rather than hand-written examples. That adapter and dataset are private (real user data), this repo is the general framework version.

## What's not here yet

- The `AnthropicJudge` in `judge.py` is real but untested against a live API key in this repo's own CI, since the demo is designed to run with zero external dependencies. `FakeJudge` stands in for demo and test purposes.
- No weighting between fields yet, a fixture's overall score is a flat average across its scored fields.
