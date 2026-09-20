#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

case "${1:-}" in
  '') ;;
  --test-only) ;;
  -h|--help)
    printf 'Usage: %s [--test-only]\nPrepare dependencies, run tests, and start the local Spotify player.\n' "$0"
    exit 0
    ;;
  *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
esac
if (( $# > 1 )); then
  printf 'Only one argument is supported.\n' >&2
  exit 2
fi

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v

if [[ "${1:-}" == --test-only ]]; then
  exit 0
fi

export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-60123}"
.venv/bin/python Flask/spotify_player.py
printf '\nConfiguration: %s/Flask/spotify.ini\n' "${SNAP_COMMON:-$PWD}"
printf 'Local player: http://127.0.0.1:%s\n' "$PORT"
printf 'Register the redirect_uri from spotify.ini in your Spotify developer app.\n'
printf 'If changing PORT, update that redirect_uri too. Press Ctrl+C to stop.\n\n'
exec .venv/bin/python Flask/app.py
