import configparser

from config import validate_config


def production_config(**overrides):
    values = {
        "env": "production",
        "debug": "false",
        "jwt_on": "true",
        "secret_key": "f" * 32,
        "jwt_secret_string": "j" * 32,
        **overrides,
    }
    candidate = configparser.ConfigParser()
    candidate["application"] = values
    return candidate


def test_production_config_accepts_closed_defaults():
    validate_config(production_config())


def test_production_config_rejects_debug_and_disabled_authentication():
    for overrides, expected in (
        ({"debug": "true"}, "production_debug_must_be_disabled"),
        ({"jwt_on": "false"}, "production_jwt_must_be_enabled"),
    ):
        try:
            validate_config(production_config(**overrides))
        except RuntimeError as exc:
            assert str(exc) == expected
        else:
            raise AssertionError(f"unsafe production configuration accepted: {overrides}")


def test_production_config_rejects_placeholder_secrets():
    for name, value in (("secret_key", "secret"), ("jwt_secret_string", "jwt_secret")):
        try:
            validate_config(production_config(**{name: value}))
        except RuntimeError as exc:
            assert str(exc) == f"production_secret_invalid:{name}"
        else:
            raise AssertionError(f"placeholder production secret accepted: {name}")
