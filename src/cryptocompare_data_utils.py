import os
from pathlib import Path

import yaml
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
ENV_PATH = PROJECT_ROOT / ".env"


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_cryptocompare_api_key(config=None):
    config = config or load_config()
    crypto_config = config.get("cryptocompare", {})
    load_dotenv(ENV_PATH)

    api_key = crypto_config.get("api_key")
    if api_key:
        return api_key

    api_key_env = crypto_config.get("api_key_env")
    if api_key_env:
        api_key = os.getenv(api_key_env)
        if api_key:
            return api_key
        raise KeyError(f"Environment variable is not set: {api_key_env}")

    api_key_file = crypto_config.get("api_key_file")
    if not api_key_file:
        raise KeyError(
            "Set cryptocompare.api_key_env, cryptocompare.api_key, "
            "or cryptocompare.api_key_file in config.yaml"
        )

    path = PROJECT_ROOT / api_key_file
    if not path.exists():
        raise FileNotFoundError(f"CryptoCompare API key file not found: {path}")

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("CRYPTOCOMPARE_API_KEY="):
            return line.split("=", 1)[1].strip()
        return line

    raise ValueError(f"CryptoCompare API key file is empty: {path}")


def cryptocompare_headers(config=None):
    api_key = load_cryptocompare_api_key(config)
    return {"authorization": f"Apikey {api_key}"}
