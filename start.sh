#!/usr/bin/env sh
# Startet SnapRec unter Linux/macOS (legt beim ersten Start eine venv an).
cd "$(dirname "$0")" || exit 1
if [ ! -d .venv ]; then
  echo "Erster Start: Pakete werden installiert ..."
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt || exit 1
fi
exec .venv/bin/python -m snaprec "$@"
