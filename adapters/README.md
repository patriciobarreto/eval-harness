# Transaction categorizer adapter

Wraps Soundboard's real transaction-categorizer agent so it can run through
`eval_harness`. See [transaction_categorizer.py](transaction_categorizer.py)
for the full rationale; this file covers setup and how to build fixtures.

## Why this calls backend-py directly, not backend-ts

`categorizeTransactions.ts` calls backend-py's
`/api/bookkeeping/transactions/categorize` and, in normal persisted mode,
writes `CategorizationAgentExecution`, `TransactionCategorizationResult`,
and `TransactionList` rows. The backend-py endpoint itself does no DB
writes, it only calls the LLM and parses the response. This adapter calls
backend-py directly, so running the eval suite -- including in CI, on every
PR -- never touches production data.

The cost of that: backend-py's endpoint expects `systemInstructions` and
`userPrompt` already built. Building them for real (in TS) means a live
vector search over the client's transaction history plus DB-stored agent
config -- state this harness has no business reconstructing, since a
reimplementation would drift out of sync with the real thing over time.
Fixtures sidestep this by freezing a real, already-built prompt rather than
generating one.

## Setup

```bash
pip install -e ".[adapters]"
export PYTHON_BACKEND_URL=https://<backend-py host>   # or BACKEND_PY_URL
export INTERNAL_SERVICE_KEY=<the same key backend-ts uses>
```

## Building fixtures from real data

We have no DB access from the eval-harness side, and fixture prompts should
come from the real TS retrieval and prompt-building path. So fixtures come
from a **dedicated test client**: seed it with realistic transaction
history, run the real categorizer against it through the front door
(`SB_AI_URL`, same API the Next.js app calls) in `persist=false` preview
mode, and turn the results into fixtures. Two scripts handle this; both need
`SB_AI_URL` and `SB_AI_API_KEY` set (not
`PYTHON_BACKEND_URL` / `INTERNAL_SERVICE_KEY` -- those are for the adapter
itself at eval-run time, this is generation time and goes through TS).

### Test client layout

Each test client gets a directory under `adapters/test_clients/` (gitignored
-- this holds real client financial data): `client1_test/`, `client2_test/`,
etc. Every one holds the same four files, built by
[convert_qb_export.py](convert_qb_export.py) and
[convert_chart_of_accounts.py](convert_chart_of_accounts.py) from a QB
export and a chart-of-accounts export, split at a cutoff date:

- `history.csv` -- transactions before the cutoff, with real categories
- `to_categorize.csv` -- transactions on/after the cutoff, categories stripped
- `ground_truth.csv` -- the same on/after-cutoff transactions, real category
  kept alongside `qbTransactionId`, joined back up after generation
- `categories.json` -- the chart of accounts
- `client.json` -- `{externalClientId, firstName, lastName, email,
  clientProfession}`

`client.json` exists specifically so the id used to seed a client's history
and the id used to run categorize test batches against it can't drift apart
-- both scripts below accept `--client-config path/to/client.json` and pull
every identity field from the same file, instead of it being retyped (and
possibly mistyped) at each step.

**1. Seed the test client's history**, so similarity search has something
real to draw on. Never point a test client's `externalClientId` at a real
client's:

```bash
python adapters/seed_test_client.py \
  --csv adapters/test_clients/client1_test/history.csv \
  --client-config adapters/test_clients/client1_test/client.json
```

`history.csv` columns: `qbTransactionId, date, amount, qbTransactionType,
bankDetail, qbCategoryName, qbCategoryId` (amount is signed dollars,
e.g. `-45.99`; category columns are the ones this historical transaction
was actually filed under). This is what actually creates the test client
(`add` calls `getClientOrCreate` under the hood) and writes real rows to
sb-ai's DB -- by design, since only real history gets real similarity
matches, but that's why the client ID has to be unmistakably a test one.

**2. Generate draft fixtures** for the transactions you actually want
golden examples for:

```bash
python adapters/build_fixture_drafts.py \
  --csv adapters/test_clients/client1_test/to_categorize.csv \
  --categories adapters/test_clients/client1_test/categories.json \
  --client-config adapters/test_clients/client1_test/client.json \
  --llm-model claude-sonnet-4-5-20250929
```

`to_categorize.csv` columns: `qbTransactionId, date, amount,
qbTransactionType, bankDetail` (no category -- these are what's being
categorized). `categories.json` is the chart of accounts, a JSON list of
`{"id": int, "name": str, "classification": str}`.

This calls the real `/categorize` API with `persist=false` and pulls
`userPrompt` and `systemInstructions` straight out of each preview result
(no DB query or review-row write needed -- the front-door API already
returns them), then writes one draft fixture per batch to
`adapters/fixtures/drafts/`.

**3. Review every draft before it counts.** `expected_output` in a draft is
just the model's own proposed category, not verified ground truth --
scoring a fixture against the model's own guess would make it pass forever
regardless of real regressions. Cross-check each entry against that test
client's `ground_truth.csv` (joined by `qbTransactionId`) rather than
judging blind -- it holds the category these exact holdout transactions were
really filed under. `load_fixtures()` only globs
`adapters/fixtures/*.yaml` (not the `drafts/` subdirectory), so a draft
literally cannot be picked up by a run until someone corrects
`expected_output` where the proposal was wrong and moves the file up out of
`drafts/`. Use `judge` scoring (wire up `AnthropicJudge`, or extend
`FakeJudge.REASONABLE_ALTERNATIVES` for this domain) for transactions where
more than one category is defensible; `exact` where there's one right
answer.

`scoring` and `expected_output` are keyed by `qbTransactionId` -- one
scored field per transaction in the batch, no changes to the harness core
required.

[batch_001.yaml](fixtures/batch_001.yaml) is a hand-written schema template
with placeholder prompts, kept for reference -- prefer the scripts above for
anything meant to be trusted.

## Running it

```python
from pathlib import Path
from eval_harness import FakeJudge, load_fixtures, run

import sys
sys.path.insert(0, str(Path(__file__).parent))
from transaction_categorizer import TransactionCategorizerAgent

fixtures = load_fixtures(Path(__file__).parent / "fixtures")
agent = TransactionCategorizerAgent()
report = run(agent, fixtures, FakeJudge())
print(report.summary())
assert report.passed
```
