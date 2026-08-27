"""
LLM-as-judge, kept separate from exact-match on purpose.

Exact match answers "is this identical." A judge answers a fuzzier question:
"is this a clear miss, or a reasonable alternative." That distinction only
matters for fields where more than one answer can be defensible, categories
being the clearest example ("Office Supplies" vs "Office Expenses" is a
judgment call, "Travel" vs "Meals" is not).

Two implementations ship here:

- FakeJudge: deterministic, no API calls, used by the test suite and by
  anyone cloning this repo without an API key. It uses a fixed set of
  known-adjacent category pairs to decide "reasonable" vs "miss".
- AnthropicJudge: the real thing, one API call per judged field, given
  the fixture's input, the expected output, and the agent's actual output.

Swap which one the harness uses at the call site, everything else in the
pipeline is identical either way.
"""

from typing import Any, Protocol


class Judge(Protocol):
    def score(
        self, field: str, input: dict[str, Any], expected: Any, actual: Any
    ) -> float:
        """Return 1.0 for a match, 0.5 for a reasonable alternative, 0.0 for a clear miss."""
        ...


class FakeJudge:
    """
    Deterministic stand-in judge for demos, tests, and running this repo
    without any API key. Not meant to replace a real judge in production,
    only to keep the harness fully runnable offline.
    """

    # Pairs of categories that a real judge would likely call "reasonable
    # alternatives" rather than clear misses. Expand this for your own domain.
    REASONABLE_ALTERNATIVES = {
        frozenset({"billing", "account"}),
        frozenset({"technical", "bug_report"}),
        frozenset({"feature_request", "feedback"}),
    }

    def score(
        self, field: str, input: dict[str, Any], expected: Any, actual: Any
    ) -> float:
        if expected == actual:
            return 1.0
        if frozenset({str(expected), str(actual)}) in self.REASONABLE_ALTERNATIVES:
            return 0.5
        return 0.0


class AnthropicJudge:
    """
    Real LLM-as-judge using the Anthropic API. Requires the `anthropic`
    package (pip install eval-harness[anthropic]) and an ANTHROPIC_API_KEY
    in the environment.
    """

    RUBRIC = (
        "You are scoring one field of an agent's output against a known-good "
        "expected value. Respond with exactly one token: MATCH if the actual "
        "value is correct or an equally valid alternative, MISS if it is wrong.\n\n"
        "Field: {field}\n"
        "Input the agent saw: {input}\n"
        "Expected value: {expected}\n"
        "Agent's actual value: {actual}"
    )

    def __init__(self, model: str = "claude-sonnet-4-6"):
        self.model = model
        self._client = None  # lazy import, so this module loads without the package installed

    def _get_client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def score(
        self, field: str, input: dict[str, Any], expected: Any, actual: Any
    ) -> float:
        client = self._get_client()
        prompt = self.RUBRIC.format(field=field, input=input, expected=expected, actual=actual)
        response = client.messages.create(
            model=self.model,
            max_tokens=5,
            messages=[{"role": "user", "content": prompt}],
        )
        verdict = response.content[0].text.strip().upper()
        return 1.0 if verdict.startswith("MATCH") else 0.0
