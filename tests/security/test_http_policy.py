import pytest

from security.http_policy import content_length_bytes, parse_allowed_origins


def test_cors_origins_are_exact_deduplicated_values():
    assert parse_allowed_origins(
        " https://one.example/,https://two.example,https://one.example "
    ) == ["https://one.example", "https://two.example"]
    assert parse_allowed_origins("*") == []


def test_request_size_policy_is_bounded():
    assert content_length_bytes(20) == 20 * 1024 * 1024
    with pytest.raises(ValueError):
        content_length_bytes(0)
    with pytest.raises(ValueError):
        content_length_bytes(101)
