import configparser
import os


def validate_config(candidate):
    if candidate.get("application", "env", fallback="development").strip().lower() != "production":
        return
    if candidate.getboolean("application", "debug", fallback=False):
        raise RuntimeError("production_debug_must_be_disabled")
    if not candidate.getboolean("application", "jwt_on", fallback=True):
        raise RuntimeError("production_jwt_must_be_enabled")
    for name in ("secret_key", "jwt_secret_string"):
        value = candidate.get("application", name, fallback="").strip()
        if len(value) < 32 or value.lower() in {"secret", "jwt_secret", "change-me"}:
            raise RuntimeError(f"production_secret_invalid:{name}")


config = configparser.ConfigParser()
default_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "properties.ini")
config.read(os.environ.get("CRAB_CONFIG_FILE", default_path))
validate_config(config)
