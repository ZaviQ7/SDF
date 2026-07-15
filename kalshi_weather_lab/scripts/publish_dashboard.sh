#!/bin/bash
set -euo pipefail

cd /home/pi/SDF/kalshi_weather_lab

.venv/bin/kalshi-weather \
  --settings config/settings.shadow.yaml \
  report

.venv/bin/python - <<'PY'
from pathlib import Path
import re
import markdown

source = Path("reports/dashboard.md")
destination = Path("../docs/index.html")

markdown_text = source.read_text(encoding="utf-8")

markdown_text = markdown_text.replace(
    "# Kalshi Weather Lab — Paper Portfolio",
    "# Kalshi Weather Lab — Shadow Portfolio",
    1,
)

# NOAA observation stations used for each Kalshi city code.
NOAA_STATIONS = {
    "AUS": "KAUS",
    "ATL": "KATL",
    "BOS": "KBOS",
    "CHI": "KORD",
    "DEN": "KDEN",
    "HOU": "KHOU",
    "MIA": "KMIA",
    "NOLA": "KMSY",
    "NY": "KNYC",
    "NYC": "KNYC",
    "OKC": "KOKC",
    "PHIL": "KPHL",
    "PHX": "KPHX",
    "SEA": "KSEA",
    "SFO": "KSFO",
}

CITY_SLUGS = {
    "AUS": "austin",
    "ATL": "atlanta",
    "BOS": "boston",
    "CHI": "chicago",
    "DEN": "denver",
    "HOU": "houston",
    "MIA": "miami",
    "NOLA": "new-orleans",
    "NY": "new-york",
    "NYC": "new-york",
    "OKC": "oklahoma-city",
    "PHIL": "philadelphia",
    "PHX": "phoenix",
    "SEA": "seattle",
    "SFO": "san-francisco",
}


def ticker_links(match: re.Match[str]) -> str:
    ticker = match.group(1)

    parts = ticker.split("-")
    if len(parts) < 2:
        return f"`{ticker}`"

    series = parts[0]
    event_ticker = "-".join(parts[:2])

    # Use Kalshi's direct series/event route. This avoids guessing the
    # inconsistent descriptive slug used by different temperature series.
    kalshi_url = (
        f"https://kalshi.com/markets/"
        f"{series.lower()}/"
        f"{event_ticker.lower()}"
    )

    SERIES_STATIONS = {
        "KXHIGHTSEA": "KSEA",
        "KXHIGHTPHX": "KPHX",
        "KXHIGHTSFO": "KSFO",
        "KXHIGHNY": "KNYC",
        "KXHIGHMIA": "KMIA",
        "KXHIGHPHIL": "KPHL",
        "KXHIGHTOKC": "KOKC",
        "KXHIGHCHI": "KORD",
        "KXHIGHBOS": "KBOS",
        "KXHIGHAUS": "KAUS",
        "KXHIGHTATL": "KATL",
        "KXHIGHTHOU": "KHOU",
        "KXHIGHTNOLA": "KMSY",
        "KXHIGHDEN": "KDEN",

        "KXLOWTSEA": "KSEA",
        "KXLOWTPHX": "KPHX",
        "KXLOWTSFO": "KSFO",
        "KXLOWTNYC": "KNYC",
        "KXLOWTMIA": "KMIA",
        "KXLOWTPHIL": "KPHL",
        "KXLOWTOKC": "KOKC",
        "KXLOWTCHI": "KORD",
        "KXLOWTBOS": "KBOS",
        "KXLOWTAUS": "KAUS",
        "KXLOWTATL": "KATL",
        "KXLOWTHOU": "KHOU",
        "KXLOWTNOLA": "KMSY",
        "KXLOWDEN": "KDEN",
    }

    links = [f"[`{ticker}`]({kalshi_url})"]

    station = SERIES_STATIONS.get(series)
    if station:
        noaa_url = (
            "https://forecast.weather.gov/data/obhistory/"
            f"{station}.html"
        )
        links.append(f"[NOAA]({noaa_url})")

    return " · ".join(links)


# Replace every backticked Kalshi ticker in Positions and Recent Decisions.
ticker_pattern = re.compile(
    r"`(KX[A-Z]+-\d{2}[A-Z]{3}\d{2}(?:-[A-Z0-9.]+)?)`"
)

markdown_text = ticker_pattern.sub(ticker_links, markdown_text)

body = markdown.markdown(
    markdown_text,
    extensions=["tables", "fenced_code"],
)

html = f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="300">

    <title>Kalshi Weather Plays</title>

    <style>
        * {{
            box-sizing: border-box;
        }}

        body {{
            margin: 0;
            padding: 16px;
            background: #f3f5f7;
            color: #17202a;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                         Roboto, Helvetica, Arial, sans-serif;
            line-height: 1.45;
        }}

        main {{
            width: min(1200px, 100%);
            margin: 0 auto;
        }}

        .notice {{
            margin-bottom: 16px;
            padding: 14px 16px;
            border: 1px solid #b8d4ff;
            border-radius: 12px;
            background: #eaf3ff;
        }}

        .notice strong {{
            display: block;
            margin-bottom: 4px;
        }}

        .card {{
            padding: 18px;
            border-radius: 14px;
            background: white;
            box-shadow: 0 2px 12px rgba(0, 0, 0, 0.07);
        }}

        h1 {{
            margin-top: 0;
            font-size: 1.65rem;
        }}

        h2 {{
            margin-top: 28px;
            padding-bottom: 7px;
            border-bottom: 1px solid #dfe4ea;
            font-size: 1.25rem;
        }}

        blockquote {{
            margin: 16px 0;
            padding: 10px 14px;
            border-left: 4px solid #8ca9c7;
            background: #f6f8fa;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 12px 0 20px;
            font-size: 0.92rem;
        }}

        th,
        td {{
            padding: 10px 9px;
            border: 1px solid #d9dee4;
            text-align: left;
            vertical-align: top;
        }}

        th {{
            background: #edf1f5;
            font-weight: 650;
        }}

        tbody tr:nth-child(even) {{
            background: #f8fafb;
        }}

        code {{
            padding: 2px 5px;
            border-radius: 5px;
            background: #edf1f5;
            overflow-wrap: normal;
            white-space: nowrap;
        }}

        a {{
            color: #0969da;
            text-decoration: none;
        }}

        a:hover {{
            text-decoration: underline;
        }}

        @media (max-width: 760px) {{
            body {{
                padding: 9px;
            }}

            .card {{
                padding: 13px;
            }}

            h1 {{
                font-size: 1.35rem;
            }}

            table {{
                display: block;
                overflow-x: auto;
                white-space: nowrap;
                font-size: 0.82rem;
            }}

            th,
            td {{
                padding: 8px 7px;
            }}
        }}
    </style>
</head>

<body>
<main>
    <div class="notice">
        <strong>Shadow mode is active.</strong>
        Ticker links open Kalshi. NOAA links open the observation
        history for the corresponding weather station.
    </div>

    <div class="card">
        {body}
    </div>
</main>
</body>
</html>
"""

destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(html, encoding="utf-8")

print(f"Published dashboard with links to {destination}")
PY

cd /home/pi/SDF

git add docs/index.html

if ! git diff --cached --quiet; then
    git commit -m "Add Kalshi and NOAA dashboard links"
    git push origin main
else
    echo "Dashboard content unchanged; nothing to push."
fi
