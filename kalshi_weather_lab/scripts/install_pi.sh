#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e '.[dev]'
cp -n config/settings.example.yaml config/settings.yaml || true
cp -n config/cities.example.yaml config/cities.yaml || true
.venv/bin/kalshi-weather init --bankroll 15.00
.venv/bin/pytest
printf '\nInstalled. Edit config/cities.yaml with your real Kalshi series tickers.\n'
