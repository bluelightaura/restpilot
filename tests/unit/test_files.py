"""Filesystem helpers and path traversal protection."""

from __future__ import annotations

import stat

import pytest

from restpilot.exceptions import ConfigurationError
from restpilot.utils.files import (
    ensure_directory,
    read_text,
    resolve_output_path,
    validate_writable_path,
    write_text,
)

pytestmark = pytest.mark.unit


def test_resolve_output_path_returns_path_inside_base(tmp_path):
    target = resolve_output_path(tmp_path, "generated/test_users.py")
    assert target == (tmp_path / "generated" / "test_users.py").resolve()


def test_resolve_output_path_rejects_traversal(tmp_path):
    with pytest.raises(ConfigurationError) as error:
        resolve_output_path(tmp_path, "../../etc/passwd")
    assert "escapes" in error.value.message


def test_resolve_output_path_rejects_absolute_path(tmp_path):
    with pytest.raises(ConfigurationError) as error:
        resolve_output_path(tmp_path, "/etc/passwd")
    assert "must be relative" in error.value.message


def test_write_text_creates_parents_and_is_atomic(tmp_path):
    target = write_text(tmp_path / "nested" / "file.txt", "hello")
    assert target.read_text(encoding="utf-8") == "hello"
    assert not (tmp_path / "nested" / "file.txt.tmp").exists()


def test_write_text_private_restricts_permissions(tmp_path):
    target = write_text(tmp_path / "config.yaml", "secret: no", private=True)
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600


def test_validate_writable_path_rejects_directory(tmp_path):
    with pytest.raises(ConfigurationError) as error:
        validate_writable_path(tmp_path)
    assert "is a directory" in error.value.message


def test_validate_writable_path_creates_parent(tmp_path):
    target = validate_writable_path(tmp_path / "out" / "response.json")
    assert target.parent.is_dir()


def test_read_text_reports_missing_file(tmp_path):
    with pytest.raises(ConfigurationError):
        read_text(tmp_path / "missing.txt")


def test_ensure_directory_is_idempotent(tmp_path):
    first = ensure_directory(tmp_path / "a" / "b")
    second = ensure_directory(tmp_path / "a" / "b")
    assert first == second and first.is_dir()
