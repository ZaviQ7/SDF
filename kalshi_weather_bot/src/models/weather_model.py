import logging
from typing import Dict, List, Any, Optional
import numpy as np

logger = logging.getLogger(__name__)

class WeatherModelProcessor:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.bias_correction_value = 0.0 
        
    def get_mixture_weights(self, hours_to_target: float, has_hrrr: bool = False) -> Dict[str, float]:
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
        temp_type: str, 
        bias_offset: float = 0.0,
        hrrr_data: Optional[Dict[str, Any]] = None,
        icon_data: Optional[Dict[str, Any]] = None,
        gem_data: Optional[Dict[str, Any]] = None,
        hours_to_target: float = 48.0,
        station_id: Optional[str] = None,
        nbm_data: Optional[Dict[str, str]] = None,
        target_utc_hour: Optional[int] = None
    ) -> np.ndarray:
        model_temps = {}

        def extract_member_temps(data):
            if not data or "members" not in data: return []
            temps = []
            for m_name, hourly_temps in data["members"].items():
                if not hourly_temps: continue
                val = max(hourly_temps) if temp_type == "HIGH" else min(hourly_temps)
                temps.append(val + self.bias_correction_value + bias_offset)
            return temps

        model_temps["gfs"] = extract_member_temps(gfs_data)
        model_temps["ecmwf"] = extract_member_temps(ecmwf_data)
        model_temps["icon"] = extract_member_temps(icon_data)
        model_temps["gem"] = extract_member_temps(gem_data)

        hrrr_val = None
        if hrrr_data:
            if "temps" in hrrr_data:
                hrrr_raw = hrrr_data["temps"]
            elif "hourly" in hrrr_data:
                h = hrrr_data.get("hourly", {})
                hrrr_raw = h.get("temperature_2m_ncep_hrrr_conus") or h.get("temperature_2m", [])
            else:
                hrrr_raw = []
                
            if hrrr_raw:
                hrrr_val = max(hrrr_raw) if temp_type == "HIGH" else min(hrrr_raw)
                
                nbm_tsd = None
                if nbm_data and station_id and target_utc_hour is not None:
                    from src.data_ingestion.nbm_client import NBMTextClient
                    card_text = nbm_data.get(station_id)
                    if card_text:
                        nbm_tsd = NBMTextClient.extract_tsd(card_text, target_utc_hour)
                
                if nbm_tsd is not None:
                    hrrr_sd = max(1.2, nbm_tsd)
                    logger.debug(f"Applied NOAA Dynamic NBM Variance for {station_id}: {hrrr_sd}°F")
                else:
                    hrrr_sd = max(1.5, min(2.5, 1.4 + 0.02 * hours_to_target))
                
                hrrr_samples = np.random.normal(loc=hrrr_val, scale=hrrr_sd, size=50)
                model_temps["hrrr"] = list(hrrr_samples + self.bias_correction_value + bias_offset)

        active_models = [m for m, temps in model_temps.items() if len(temps) > 0]
        if not active_models:
            return np.array([])

        has_hrrr = "hrrr" in active_models
        raw_weights = self.get_mixture_weights(hours_to_target, has_hrrr=has_hrrr)
        
        active_weights = {m: raw_weights.get(m, 0.0) for m in active_models}
        weight_sum = sum(active_weights.values())
        if weight_sum <= 0:
            normalized_weights = {m: 1.0 / len(active_models) for m in active_models}
        else:
            normalized_weights = {m: w / weight_sum for m, w in active_weights.items()}

        logger.info(f"Assigned mixture weights for {temp_type}: " + ", ".join([f"{m}: {w:.1%}" for m, w in normalized_weights.items()]))

        total_samples = 10000
        pooled_samples = []
        sorted_models = sorted(normalized_weights.keys(), key=lambda m: normalized_weights[m], reverse=True)
        
        for model in sorted_models:
            w = normalized_weights[model]
            temps = model_temps[model]
            n_samples = int(round(total_samples * w))
            if n_samples > 0:
                sampled = np.random.choice(temps, size=n_samples, replace=True)
                pooled_samples.extend(sampled)

        diff = total_samples - len(pooled_samples)
        if diff > 0 and len(pooled_samples) > 0:
            highest_model = sorted_models[0]
            extra_samples = np.random.choice(model_temps[highest_model], size=diff, replace=True)
            pooled_samples.extend(extra_samples)
        elif diff < 0:
            pooled_samples = pooled_samples[:total_samples]

        return np.array(pooled_samples)
        
    def get_distribution_stats(self, pooled_temps: np.ndarray) -> Dict[str, Any]:
        if len(pooled_temps) == 0:
            return {"mean": 0.0, "std": 2.0, "min": 0.0, "max": 0.0, "count": 0}
            
        mean_val = float(np.mean(pooled_temps))
        std_val = float(np.std(pooled_temps))
        if std_val < 0.5:
            std_val = 1.5
            
        return {
            "mean": mean_val,
            "std": std_val,
            "min": float(np.min(pooled_temps)),
            "max": float(np.max(pooled_temps)),
            "count": len(pooled_temps)
        }