#!/bin/bash
set -euo pipefail

cd /home/pi/SDF/kalshi_weather_lab

.venv/bin/kalshi-weather \
  --settings config/settings.shadow.yaml \
  settle-open

.venv/bin/kalshi-weather \
  --settings config/settings.shadow.yaml \
  run-once \
  --paper-execute
