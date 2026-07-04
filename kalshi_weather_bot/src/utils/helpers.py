import re
import math
from typing import Tuple, Optional

def parse_range(title: str) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """
    Parse the target temperature range/threshold from Kalshi market titles.
    Supports formats like:
      - "85 to 86" (between)
      - ">= 85" or "85 or above" (greater)
      - "< 85" or "below 85" (less)
      
    Returns:
        Tuple: (range_type, val1, val2)
        e.g., ("between", 85, 86) or ("greater", 85, None)
    """
    # 1. Matches "89 to 90" or "89-90" or "89 to 90°F"
    m_between = re.search(r'(\d+)\s*(?:to|-)\s*(\d+)', title)
    if m_between:
        return "between", int(m_between.group(1)), int(m_between.group(2))
        
    # 2. Matches ">=85" or "85 or above" or "above 85" or "over 85"
    m_greater = re.search(r'(?:>=|>)\s*(\d+)|(\d+)\s*(?:or above|or higher|above|over)', title)
    if m_greater:
        val = m_greater.group(1) or m_greater.group(2)
        return "greater", int(val), None
        
    # 3. Matches "<85" or "below 85" or "under 85"
    m_less = re.search(r'(?:<=|<)\s*(\d+)|(\d+)\s*(?:or below|or lower|below|under)', title)
    if m_less:
        val = m_less.group(1) or m_less.group(2)
        return "less", int(val), None
        
    return None, None, None

def calculate_maker_fee(price: float, size: int = 1) -> float:
    """
    Calculate Kalshi's Maker fee: 1.75% * Price * (1 - Price) * Size.
    Rounded up to the nearest cent.
    """
    raw_fee = 0.0175 * size * price * (1.0 - price)
    return math.ceil(raw_fee * 100) / 100.0
