"""
The one interface the harness cares about.

Any agent, a toy demo classifier or a production filing agent, plugs in by
implementing this single method. The harness never imports or knows about
your actual agent code. You write a small adapter that wraps your agent
to match this shape, and point the harness at the adapter.

Keeping this boring on purpose: input in, output out. No Soundboard-specific
or classifier-specific assumptions belong here. If you find yourself wanting
to add fields to this interface for one specific agent, that's a sign the
extra structure belongs in that agent's own output, not in the protocol.
"""

from typing import Any, Protocol


class Agent(Protocol):
    def run(self, input: dict[str, Any]) -> dict[str, Any]:
        """
        Take one fixture's input, return the agent's output.

        Both input and output are plain dicts, matching whatever shape
        the golden dataset fixtures use for this agent. The harness does
        not interpret their contents, that's the scoring layer's job.
        """
        ...
