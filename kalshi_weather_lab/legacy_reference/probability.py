import logging
from typing import Optional, List, Union
import numpy as np

logger = logging.getLogger(__name__)

def calculate_market_probability(
    rtype: str,
    val1: int,
    val2: Optional[int],
    pooled_temps: Union[np.ndarray, List[float]]
) -> float:
    """
    Calculate empirical probability for a contract based on its range type,
    rounding each ensemble forecast to the nearest integer (matching Kalshi/NOAA).
    
    Args:
        rtype: "between", "greater", "less"
        val1: The lower bound or threshold value
        val2: The upper bound value (only used for "between")
        pooled_temps: Array or list of pooled ensemble temperatures
        
    Returns:
        Probability from 0.01 to 0.99
    """
    if len(pooled_temps) == 0:
        return 0.5
        
    # Round to matching integer resolution
    rounded_temps = np.round(pooled_temps).astype(int)
    total_members = len(rounded_temps)
    
    if rtype == "between":
        if val2 is None:
            val2 = val1
        matches = np.sum((rounded_temps >= val1) & (rounded_temps <= val2))
    elif rtype == "greater":
        # Strictly greater than, e.g. T95 corresponds to >95 (which is >=96)
        matches = np.sum(rounded_temps > val1)
    elif rtype == "less":
        # Strictly less than, e.g. T88 corresponds to <88 (which is <=87)
        matches = np.sum(rounded_temps < val1)
    else:
        logger.warning(f"Unknown range type: {rtype}. Defaulting to 50/50.")
        return 0.5
        
    p = float(matches) / float(total_members)
    
    # Bound the probability to avoid 0.0 or 1.0 (limits extreme risk)
    return max(0.01, min(0.99, p))
