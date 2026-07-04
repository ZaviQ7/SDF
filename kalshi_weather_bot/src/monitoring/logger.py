import logging
import logging.handlers
import os

def setup_logging(config: dict) -> logging.Logger:
    """
    Set up standard and file-rotated logging based on settings.yaml.
    """
    log_config = config.get('logging', {})
    log_level = log_config.get('level', 'INFO')
    log_file = log_config.get('file', 'data/logs/weather_bot.log')
    max_bytes = log_config.get('max_file_size', 10485760)
    backup_count = log_config.get('backup_count', 5)
    log_format = log_config.get('format', "%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Create directory for log file if it does not exist
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # Reset existing handlers to prevent duplicate logging
    root_logger.handlers = []

    # 1. Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format))
    root_logger.addHandler(console_handler)

    # 2. Rotated File handler
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setFormatter(logging.Formatter(log_format))
        root_logger.addHandler(file_handler)
    except Exception as e:
        print(f"Error creating file logging handler: {e}")

    logger = logging.getLogger("weather_bot")
    logger.info("Structured logging initialized successfully.")
    return logger
