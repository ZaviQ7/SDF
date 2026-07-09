import aiohttp
import re
from datetime import datetime, timezone
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class NBMTextClient:
    """Efficient bulk downloader and parser for NOAA's National Blend of Models hourly text cards."""
    
    def __init__(self):
        self.base_url = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod"

    async def fetch_latest_nbm_cards(self) -> Dict[str, str]:
        now_utc = datetime.now(timezone.utc)
        date_str = now_utc.strftime("%Y%m%d")
        headers = {"User-Agent": "KalshiWeatherBot/2.0 (contact@kalshiedgebot.com)"}
        
        for lookback in range(4):
            cycle_hour = (now_utc.hour - lookback) % 24
            cycle_str = f"{cycle_hour:02d}"
            
            url = f"{self.base_url}/blend.{date_str}/{cycle_str}/text/blend_nbhtx.t{cycle_str}z"
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers, timeout=10) as resp:
                        if resp.status == 200:
                            logger.info(f"Successfully retrieved NBM text bulletins for cycle {cycle_str}Z.")
                            bulk_text = await resp.text()
                            return self._parse_bulk_text(bulk_text)
            except Exception as e:
                logger.debug(f"NBM cycle {cycle_str}Z fetch attempt skipped: {e}")
                
        logger.warning("Failed to harvest fresh NBM text records from NOMADS. Utilizing internal fallback variance.")
        return {}

    def _parse_bulk_text(self, bulk_text: str) -> Dict[str, str]:
        station_map = {}
        chunks = re.split(r'\n(?=[A-Z][A-Z][0-9A-Z]{2}\s+NBH)', bulk_text)
        for chunk in chunks:
            match = re.match(r'^([A-Z0-9]{4})\s+', chunk.strip())
            if match:
                station_map[match.group(1)] = chunk
        return station_map

    @staticmethod
    def extract_tsd(card_text: str, target_hour_utc: int) -> Optional[float]:
        lines = card_text.split('\n')
        utc_line, tsd_line = None, None
        
        for line in lines:
            line_strip = line.strip()
            if line_strip.startswith("UTC"):
                utc_line = [int(x) for x in line_strip.split()[1:] if x.strip().replace('-', '').isdigit()]
            elif line_strip.startswith("TSD"):
                tsd_line = [int(x) for x in line_strip.split()[1:] if x.strip().replace('-', '').isdigit()]
                
        if not utc_line or not tsd_line:
            return None
            
        try:
            col_idx = min(
                range(len(utc_line)), 
                key=lambda i: min(
                    abs(utc_line[i] - target_hour_utc),
                    abs((utc_line[i] + 24) - target_hour_utc),
                    abs((utc_line[i] - 24) - target_hour_utc)
                )
            )
            if col_idx < len(tsd_line):
                val = float(tsd_line[col_idx])
                return val if val > 0 else None
        except Exception:
            pass
        return None