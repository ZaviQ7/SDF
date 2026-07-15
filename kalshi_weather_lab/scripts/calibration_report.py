#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
from statistics import median

from kalshi_weather_lab.calibration import ResidualCalibrator, load_residual_rows
from kalshi_weather_lab.config import load_config
from kalshi_weather_lab.ledger import Ledger


def main() -> None:
    parser = argparse.ArgumentParser(description="Show daily hierarchical calibration coverage")
    parser.add_argument("--settings", default="config/settings.shadow.yaml")
    parser.add_argument("--cities", default="config/cities.yaml")
    args = parser.parse_args()

    config = load_config(args.settings, args.cities)
    ledger = Ledger(config.database_path)
    rows = ledger.residual_rows()
    grouped = load_residual_rows(rows)
    calibrator = ResidualCalibrator(grouped)

    print(f"Residual rows: {len(rows)}")
    if not rows:
        print("No residuals yet. They will appear after a scanned target date has a final NWS CLI report.")
        return

    pooled: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for (city, temp_type, model, lead), values in grouped.items():
        del city
        pooled[(temp_type, model, lead)].extend(values)

    print("\nPooled model/lead coverage:")
    for key in sorted(pooled):
        values = pooled[key]
        print(
            f"  {key[0]:4s} {key[1]:6s} {key[2]:5s} "
            f"n={len(values):4d} median_bias={median(values):+5.2f}F"
        )

    print("\nCurrent hierarchical estimates by active city (fallback sigma 2.0F):")
    models = sorted({key[2] for key in grouped})
    leads = sorted({key[3] for key in grouped})
    for city in config.cities:
        if not city.active:
            continue
        for temp_type in ("HIGH", "LOW"):
            for model in models:
                for lead in leads:
                    hours = {"0-6": 3, "6-12": 9, "12-24": 18, "24-48": 36, "48+": 60}[lead]
                    estimate = calibrator.estimate(
                        city.code,
                        temp_type,
                        model,
                        hours,
                        fallback_sigma=2.0,
                    )
                    if estimate.pooled_count or estimate.count:
                        print(
                            f"  {city.code:5s} {temp_type:4s} {model:6s} {lead:5s} "
                            f"bias={estimate.bias:+5.2f} sigma={estimate.sigma:4.2f} "
                            f"exact={estimate.count:3d} pooled={estimate.pooled_count:3d} "
                            f"level={estimate.level}"
                        )


if __name__ == "__main__":
    main()
