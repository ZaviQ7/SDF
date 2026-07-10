#!/bin/bash
set -euo pipefail

cd /home/pi/SDF/kalshi_weather_lab

.venv/bin/kalshi-weather report

python3 - <<'PY'
from pathlib import Path
from html import escape

source = Path("reports/dashboard.md")
destination = Path("../docs/index.html")

markdown = source.read_text(encoding="utf-8")

html = f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="300">
    <title>Kalshi Weather Plays</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            max-width: 900px;
            margin: 0 auto;
            padding: 18px;
            line-height: 1.5;
            background: #f5f5f5;
        }}
        main {{
            background: white;
            padding: 18px;
            border-radius: 12px;
        }}
        pre {{
            white-space: pre-wrap;
            overflow-wrap: anywhere;
            font-family: Arial, sans-serif;
        }}
    </style>
</head>
<body>
<main>
<pre>{escape(markdown)}</pre>
</main>
</body>
</html>
"""

destination.write_text(html, encoding="utf-8")
print(destination)
PY

cd /home/pi/SDF

git add docs/index.html

if ! git diff --cached --quiet; then
    git commit -m "Update Kalshi weather dashboard"
    git push origin main
fi
