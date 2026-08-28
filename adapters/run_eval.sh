#!/usr/bin/env bash
# Simple entry point for run_categorizer_eval.py -- loads adapters/.env and
# calls it with the Python interpreter that actually has `requests`
# installed (plain `python3` on this machine resolves to Xcode's bundled
# 3.9.6, which doesn't have it -- see adapters/README.md).
#
# Usage:
#   ./adapters/run_eval.sh                                   # both test clients, default model
#   ./adapters/run_eval.sh --llm-model gpt-4o                # override the model
#   ./adapters/run_eval.sh --client-dir adapters/test_clients/client1_test   # just one client
#
# Override EVAL_HARNESS_PYTHON if your `requests`-capable interpreter lives
# somewhere else.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${EVAL_HARNESS_PYTHON:-/opt/homebrew/opt/python@3.11/bin/python3.11}"

set -a
source "$SCRIPT_DIR/.env"
set +a

exec "$PYTHON" "$SCRIPT_DIR/run_categorizer_eval.py" --llm-model claude-haiku-4-5-20251001 "$@"
