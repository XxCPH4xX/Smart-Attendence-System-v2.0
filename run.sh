#!/bin/sh
set -eu

cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ ! -x .venv/bin/python ]; then
    printf '%s\n' 'Set up the environment first: uv sync --locked' >&2
    exit 1
fi

exec ./.venv/bin/python -m scripts.run_local "$@"
