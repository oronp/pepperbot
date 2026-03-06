"""Configuration module for pepperbot."""

from pepperbot.config.loader import get_config_path, load_config
from pepperbot.config.schema import Config

__all__ = ["Config", "load_config", "get_config_path"]
