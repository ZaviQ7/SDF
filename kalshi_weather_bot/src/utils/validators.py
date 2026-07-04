import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

def validate_config(config: Dict[str, Any]) -> bool:
    """Validate global settings dictionary structure."""
    required_sections = ['kalshi', 'weather', 'risk', 'logging']
    for sec in required_sections:
        if sec not in config:
            logger.error(f"Config Validation Error: Missing required section '{sec}'")
            return False
            
    # Validate trading limits
    trading = config['kalshi'].get('trading', {})
    if 'max_position_per_market' not in trading:
        logger.warning("Config Warning: 'max_position_per_market' not set, using default: 10")
    if 'max_total_exposure' not in trading:
        logger.warning("Config Warning: 'max_total_exposure' not set, using default: 0.30")
        
    # Validate risk manager variables
    risk = config.get('risk', {})
    if 'bankroll' not in risk:
        logger.error("Config Validation Error: 'bankroll' must be specified under 'risk'")
        return False
        
    return True

def validate_cities(cities: List[Dict[str, Any]]) -> bool:
    """Validate city configurations in cities.yaml."""
    if not isinstance(cities, list) or len(cities) == 0:
        logger.error("Cities Validation Error: No cities configured or cities is not a list")
        return False
        
    required_keys = ['name', 'code', 'kalshi_market_prefix', 'nws_station_id', 'lat', 'lon', 'timezone']
    for idx, city in enumerate(cities):
        for key in required_keys:
            if key not in city:
                logger.error(f"Cities Validation Error: City at index {idx} ({city.get('name', 'Unknown')}) is missing required key '{key}'")
                return False
                
        # Validate coordinates range
        lat = city['lat']
        lon = city['lon']
        if not (-90.0 <= lat <= 90.0):
            logger.error(f"Cities Validation Error: City '{city['name']}' has invalid latitude: {lat}")
            return False
        if not (-180.0 <= lon <= 180.0):
            logger.error(f"Cities Validation Error: City '{city['name']}' has invalid longitude: {lon}")
            return False
            
    return True
