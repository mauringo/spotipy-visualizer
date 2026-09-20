#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt

export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-60123}"
.venv/bin/python Flask/spotify_player.py

printf '\nConfiguration: %s/Flask/spotify.ini\n' "${SNAP_COMMON:-$PWD}"
printf 'Open http://127.0.0.1:%s\n' "$PORT"
printf 'Press Ctrl+C to stop.\n\n'
exec .venv/bin/python Flask/app.py
