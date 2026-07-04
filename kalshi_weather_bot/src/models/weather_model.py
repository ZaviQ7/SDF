import logging
from typing import Dict, List, Any, Optional
import numpy as np

logger = logging.getLogger(__name__)

class WeatherModelProcessor:
    """Process ensemble weather forecasts and generate temperature distributions."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.bias_correction_value = 0.0 # Model bias offset in Fahrenheit
        
    def process_ensembles(
        self,
        gfs_data: Optional[Dict[str, Any]],
        ecmwf_data: Optional[Dict[str, Any]],
        temp_type: str,  # "HIGH" or "LOW"
        bias_offset: float = 0.0,
        hrrr_data: Optional[Dict[str, Any]] = None
    ) -> np.ndarray:
        """
        Extract daily High or Low temperatures for all members, and pool them.
        
        Args:
            gfs_data: Forecast dict from GFSDownloader
            ecmwf_data: Forecast dict from ECMWFDownloader
            temp_type: "HIGH" or "LOW"
            
        Returns:
            np.ndarray of pooled daily temperatures
        """
        pooled_temps = []
        
        # 1. Process GFS
        if gfs_data and "members" in gfs_data:
            gfs_members = gfs_data["members"]
            for m_name, hourly_temps in gfs_members.items():
                if not hourly_temps:
                    continue
                # Calculate daily high or low for this member
                if temp_type == "HIGH":
                    daily_val = max(hourly_temps)
                else:
                    daily_val = min(hourly_temps)
                pooled_temps.append(daily_val)
                
        # 2. Process ECMWF
        if ecmwf_data and "members" in ecmwf_data:
            ecmwf_members = ecmwf_data["members"]
            for m_name, hourly_temps in ecmwf_members.items():
                if not hourly_temps:
                    continue
                if temp_type == "HIGH":
                    daily_val = max(hourly_temps)
                else:
                    daily_val = min(hourly_temps)
                pooled_temps.append(daily_val)
                
        # Apply bias correction
        final_temps = np.array(pooled_temps) + self.bias_correction_value + bias_offset
        
        # Apply HRRR shift if available and enabled
        if hrrr_data and "temps" in hrrr_data and len(final_temps) > 0:
            hrrr_weight = float(self.config['weather'].get('hrrr', {}).get('weight', 0.4))
            hrrr_raw = hrrr_data["temps"]
            hrrr_val = max(hrrr_raw) if temp_type == "HIGH" else min(hrrr_raw)
            
            # Calculate shift: (HRRR - ensemble_mean) * weight
            ensemble_mean = np.mean(final_temps)
            shift = (hrrr_val - ensemble_mean) * hrrr_weight
            
            logger.info(f"Applying HRRR short-term shift: {shift:+.2f}°F (Weight: {hrrr_weight}, HRRR: {hrrr_val:.1f}°F, Ensemble Mean: {ensemble_mean:.1f}°F)")
            final_temps = final_temps + shift
            
        logger.debug(
            f"Processed {temp_type} ensembles. Total pooled members: {len(final_temps)}. "
            f"Mean: {np.mean(final_temps) if len(final_temps) > 0 else 0.0:.2f}°F"
        )
        return final_temps
        
    def get_distribution_stats(self, pooled_temps: np.ndarray) -> Dict[str, Any]:
        """Calculate statistical metrics from the pooled ensemble temperatures."""
        if len(pooled_temps) == 0:
            return {
                "mean": 0.0,
                "std": 2.0,
                "min": 0.0,
                "max": 0.0,
                "count": 0
            }
            
        mean_val = float(np.mean(pooled_temps))
        std_val = float(np.std(pooled_temps))
        
        # Ensure standard deviation doesn't collapse to 0 (default error margin = 1.5°F)
        if std_val < 0.5:
            std_val = 1.5
            
        return {
            "mean": mean_val,
            "std": std_val,
            "min": float(np.min(pooled_temps)),
            "max": float(np.max(pooled_temps)),
            "count": len(pooled_temps)
        }
