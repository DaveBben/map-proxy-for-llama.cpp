import logging.config
import os
from pathlib import Path
from typing import Any, Dict

import yaml

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    pass


class EmptyConfig(Exception):
    pass


def _load_yaml_file(file_path: Path) -> Dict[str, Any]:
    """
    Load and parse a YAML file.

    Args:
        file_path: Path to the YAML file
        required: Whether the file is required (raises exception if missing)

    Returns:
        Dictionary containing the YAML data

    Raises:
        ConfigError: If required file is missing or invalid
    """
    try:
        logger.debug(f"Loading logging configuration from {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data

    except FileNotFoundError:
        msg = f"Config file not found: {file_path}"
        raise ConfigError(msg)

    except yaml.YAMLError as e:
        msg = f"Error parsing YAML file {file_path}: {e}"
        raise ConfigError(msg)

    except Exception as e:
        msg = f"Unexpected error loading {file_path}: {e}"
        raise ConfigError(msg)


def load_config():
    """Load the main configuration file."""
    config_path = Path(__file__).parent / "config.yaml"
    logger.debug(f"Loading config from: {config_path}")
    return _load_yaml_file(config_path)


def get_root_logger():
    """Set up logging from YAML configuration."""
    try:
        # Create logs directory
        logs_dir = Path(__file__).parent.parent.parent.parent / "logs"
        logs_dir.mkdir(exist_ok=True)
        config = load_config()
        log_level = os.environ.get("LOG_LEVEL")
        if log_level:
            config["logging"]["root"]["level"] = log_level.upper()


        # Apply configuration
        logging.config.dictConfig(config)
        logger.debug("Applied logging config")
        return logging.getLogger("app")
    except ConfigError:
        raise
    except Exception:
        raise


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a specific module under the app namespace."""
    return logging.getLogger(f"app.{name}")