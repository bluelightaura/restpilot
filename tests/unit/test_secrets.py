"""Environment variable expansion and secret masking."""

from __future__ import annotations

import pytest

from restpilot.exceptions import ConfigurationError
from restpilot.utils.secrets import (
    is_sensitive_header,
    mask_header,
    mask_headers,
    mask_secret,
    substitute_env_vars,
    substitute_env_vars_in_mapping,
)

pytestmark = pytest.mark.unit


def test_substitute_env_vars_replaces_placeholder():
    result = substitute_env_vars("Bearer ${TOKEN}", environ={"TOKEN": "secret"})
    assert result == "Bearer secret"


def test_substitute_env_vars_keeps_plain_text():
    assert substitute_env_vars("application/json", environ={}) == "application/json"


def test_substitute_env_vars_raises_for_missing_variable():
    with pytest.raises(ConfigurationError) as error:
        substitute_env_vars("Bearer ${MISSING_TOKEN}", environ={})
    assert "MISSING_TOKEN" in error.value.message
    assert error.value.hint is not None


def test_substitute_env_vars_reads_process_environment(monkeypatch):
    monkeypatch.setenv("RESTPILOT_TOKEN", "from-process")
    assert substitute_env_vars("${RESTPILOT_TOKEN}") == "from-process"


def test_substitute_env_vars_in_mapping():
    resolved = substitute_env_vars_in_mapping(
        {"Authorization": "Bearer ${TOKEN}", "Accept": "application/json"},
        environ={"TOKEN": "abc"},
    )
    assert resolved == {"Authorization": "Bearer abc", "Accept": "application/json"}


def test_mask_secret_keeps_authentication_scheme():
    assert mask_secret("Bearer eyJhbGciOiJIUzI1NiJ9") == "Bearer eyJhb..."


def test_mask_secret_masks_short_values_completely():
    assert mask_secret("abcd") == "***"
    assert mask_secret("") == ""


def test_mask_secret_masks_raw_token():
    assert mask_secret("abcdefghijkl") == "abcde..."


@pytest.mark.parametrize("name", ["Authorization", "cookie", "X-API-Key", "SET-COOKIE"])
def test_is_sensitive_header_is_case_insensitive(name):
    assert is_sensitive_header(name)


def test_mask_headers_leaves_harmless_headers_untouched():
    masked = mask_headers(
        {
            "Accept": "application/json",
            "Authorization": "Bearer supersecrettoken",
            "X-API-Key": "abcdefghijklmnop",
        }
    )
    assert masked["Accept"] == "application/json"
    assert masked["Authorization"] == "Bearer super..."
    assert masked["X-API-Key"] == "abcde..."
    assert "supersecrettoken" not in str(masked)


def test_mask_header_returns_value_for_regular_header():
    assert mask_header("Accept", "text/plain") == "text/plain"
