import logging
from typing import Dict, List, Any, Optional
import numpy as np

logger = logging.getLogger(__name__)

class WeatherModelProcessor:
    """Process ensemble weather forecasts and generate temperature distributions."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.bias_correction_value = 0.0 # Model bias offset in Fahrenheit
        
    def get_mixture_weights(self, hours_to_target: float, has_hrrr: bool = False) -> Dict[str, float]:
        """Compute expert model mixture splits based on lead hours to target date."""
        weights = {
            "ecmwf": 0.40,
            "gfs": 0.35,
            "icon": 0.15,
            "gem": 0.10
        }
        if has_hrrr and hours_to_target > 0:
            if hours_to_target <= 12:    hrrr_w = 0.45
            elif hours_to_target <= 24:  hrrr_w = 0.30
            elif hours_to_target <= 36:  hrrr_w = 0.15
            elif hours_to_target <= 48:  hrrr_w = 0.05
            else:                        hrrr_w = 0.0

            if hrrr_w > 0:
                scale_factor = 1.0 - hrrr_w
                for k in weights:
                    weights[k] *= scale_factor
                weights["hrrr"] = hrrr_w
                
        return weights

    def process_ensembles(
        self,
        gfs_data: Optional[Dict[str, Any]],
        ecmwf_data: Optional[Dict[str, Any]],
        temp_type: str,  # "HIGH" or "LOW"
        bias_offset: float = 0.0,
        hrrr_data: Optional[Dict[str, Any]] = None,
        icon_data: Optional[Dict[str, Any]] = None,
        gem_data: Optional[Dict[str, Any]] = None,
        hours_to_target: float = 48.0
    ) -> np.ndarray:
        """
        Extract daily High or Low temperatures for all members, apply dynamic expert weighting,
        and bootstrap a backward-compatible pooled distribution.
        """
        model_temps = {}

        # Helper to extract daily max/min per member
        def extract_member_temps(data):
            if not data or "members" not in data:
                return []
            temps = []
            for m_name, hourly_temps in data["members"].items():
                if not hourly_temps:
                    continue
                val = max(hourly_temps) if temp_type == "HIGH" else min(hourly_temps)
                temps.append(val + self.bias_correction_value + bias_offset)
            return temps

        # Extract for each ensemble model
        model_temps["gfs"] = extract_member_temps(gfs_data)
        model_temps["ecmwf"] = extract_member_temps(ecmwf_data)
        model_temps["icon"] = extract_member_temps(icon_data)
        model_temps["gem"] = extract_member_temps(gem_data)

        # Extract HRRR short-term deterministic value
        hrrr_val = None
        if hrrr_data:
            if "temps" in hrrr_data:
                hrrr_raw = hrrr_data["temps"]
            elif "hourly" in hrrr_data:
                # Support raw open-meteo response structure
                h = hrrr_data.get("hourly", {})
                hrrr_raw = h.get("temperature_2m_ncep_hrrr_conus") or h.get("temperature_2m", [])
            else:
                hrrr_raw = []
                
            if hrrr_raw:
                hrrr_val = max(hrrr_raw) if temp_type == "HIGH" else min(hrrr_raw)
                model_temps["hrrr"] = [hrrr_val + self.bias_correction_value + bias_offset]

        # Determine mixture weights for active models
        active_models = [m for m, temps in model_temps.items() if len(temps) > 0]
        if not active_models:
            return np.array([])

        has_hrrr = "hrrr" in active_models
        raw_weights = self.get_mixture_weights(hours_to_target, has_hrrr=has_hrrr)
        
        # Filter and normalize weights
        active_weights = {m: raw_weights.get(m, 0.0) for m in active_models}
        weight_sum = sum(active_weights.values())
        if weight_sum <= 0:
            # Fallback to equal weights if config or logic returns 0
            normalized_weights = {m: 1.0 / len(active_models) for m in active_models}
        else:
            normalized_weights = {m: w / weight_sum for m, w in active_weights.items()}

        logger.info(f"Assigned mixture weights for {temp_type}: " + ", ".join([f"{m}: {w:.1%}" for m, w in normalized_weights.items()]))

        # Bootstrap/resample 10,000 values to represent the blended mixture distribution
        # This keeps the output fully backward-compatible with 1D numpy array expectations
        total_samples = 10000
        pooled_samples = []
        
        # Sort to make assignment deterministic
        sorted_models = sorted(normalized_weights.keys(), key=lambda m: normalized_weights[m], reverse=True)
        
        for model in sorted_models:
            w = normalized_weights[model]
            temps = model_temps[model]
            n_samples = int(round(total_samples * w))
            if n_samples > 0:
                # Sample with replacement from this expert model's distribution
                sampled = np.random.choice(temps, size=n_samples, replace=True)
                pooled_samples.extend(sampled)

        # Pad or trim to exactly 10,000 samples if rounding differences occur
        diff = total_samples - len(pooled_samples)
        if diff > 0 and len(pooled_samples) > 0:
            # Pad using the model with the highest weight
            highest_model = sorted_models[0]
            extra_samples = np.random.choice(model_temps[highest_model], size=diff, replace=True)
            pooled_samples.extend(extra_samples)
        elif diff < 0:
            pooled_samples = pooled_samples[:total_samples]

        final_temps = np.array(pooled_samples)

        logger.debug(
            f"Processed {temp_type} ensembles using Mixture Bootstrapping. "
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
