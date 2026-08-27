"""
Demo agent: a support-ticket categorizer.

This is the public stand-in for a production classifier (in the real
version, a transaction categorizer). Same shape: text in, one category
label out, with ambiguous cases where more than one label is defensible.

The classification logic here is a deliberately simple keyword match, not
an LLM call, so this repo runs standalone with no API key required. Swap
`classify()` for a real LLM call and nothing else in the harness changes,
that's the point of the adapter pattern: the harness only ever calls
`.run()`, it doesn't know or care what's inside it.
"""

from typing import Any

CATEGORIES = {
    "billing": ["charge", "charged", "invoice", "refund", "payment", "subscription"],
    "account": ["password", "login", "email address", "username", "locked out"],
    "technical": ["error", "crash", "not working", "broken", "500", "timeout"],
    "bug_report": ["bug", "glitch", "unexpected behavior", "reproduce"],
    "feature_request": ["would be nice", "please add", "feature", "wish it could"],
    "feedback": ["just wanted to say", "love the product", "suggestion"],
}


class TicketClassifier:
    def run(self, input: dict[str, Any]) -> dict[str, Any]:
        text = f"{input.get('subject', '')} {input.get('body', '')}".lower()

        best_category = "uncategorized"
        best_hits = 0
        for category, keywords in CATEGORIES.items():
            hits = sum(1 for kw in keywords if kw in text)
            if hits > best_hits:
                best_hits = hits
                best_category = category

        return {"category": best_category}
