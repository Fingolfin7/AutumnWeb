"""Configuration management for Autumn CLI."""

import os
import yaml
from pathlib import Path
from typing import Optional


CONFIG_DIR = Path.home() / ".autumn"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


def ensure_config_dir():
    """Create config directory if it doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Load configuration from file."""
    ensure_config_dir()
    
    if not CONFIG_FILE.exists():
        return {}
    
    try:
        with open(CONFIG_FILE, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def save_config(config: dict):
    """Save configuration to file."""
    ensure_config_dir()
    
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False)


def get_api_key() -> Optional[str]:
    """Get API key from config or environment variable."""
    # Environment variable takes precedence
    env_key = os.getenv("AUTUMN_API_KEY")
    if env_key:
        return env_key
    
    # Fall back to config file
    config = load_config()
    return config.get("api_key")


def get_base_url() -> str:
    """Get base URL from config or environment variable, with default."""
    # Environment variable takes precedence
    env_url = os.getenv("AUTUMN_API_BASE")
    if env_url:
        return env_url.rstrip("/")
    
    # Fall back to config file
    config = load_config()
    return config.get("base_url", "http://localhost:8000").rstrip("/")


def set_api_key(api_key: str):
    """Set API key in config file."""
    config = load_config()
    config["api_key"] = api_key
    save_config(config)


def set_base_url(base_url: str):
    """Set base URL in config file."""
    config = load_config()
    config["base_url"] = base_url.rstrip("/")
    save_config(config)
