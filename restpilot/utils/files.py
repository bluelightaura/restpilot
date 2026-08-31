"""Filesystem helpers with path-traversal protection."""

from __future__ import annotations

from pathlib import Path

from restpilot.exceptions import ConfigurationError

#: Permissions for files that may contain credentials.
PRIVATE_FILE_MODE = 0o600


def ensure_directory(path: Path) -> Path:
    """Create ``path`` (and parents) if needed and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_output_path(base_dir: Path, name: str) -> Path:
    """Resolve ``name`` inside ``base_dir``, refusing to escape it.

    Args:
        base_dir: Directory the file must stay within.
        name: User supplied file name or relative path.

    Returns:
        The absolute path of the output file.

    Raises:
        ConfigurationError: If ``name`` is absolute or escapes ``base_dir``.
    """
    candidate = Path(name)
    if candidate.is_absolute() or candidate.drive:
        raise ConfigurationError(
            f"output path {name!r} must be relative to {base_dir}.",
            hint="Pass a file name without a leading '/'.",
        )
    base = base_dir.resolve()
    target = (base / candidate).resolve()
    if target != base and base not in target.parents:
        raise ConfigurationError(
            f"output path {name!r} escapes the target directory {base}.",
            hint="Path traversal ('..') is not allowed.",
        )
    return target


def validate_writable_path(path: Path) -> Path:
    """Validate a user supplied output path and create its parent directory.

    Args:
        path: The requested output file.

    Returns:
        The absolute path of the file.

    Raises:
        ConfigurationError: If the path points at an existing directory.
    """
    target = path.expanduser().resolve()
    if target.is_dir():
        raise ConfigurationError(
            f"output path {path} is a directory.",
            hint="Pass a file name instead.",
        )
    ensure_directory(target.parent)
    return target


def write_text(path: Path, content: str, *, private: bool = False) -> Path:
    """Write ``content`` to ``path`` atomically.

    Args:
        path: Destination file.
        content: Text to write.
        private: When true, restrict the file to the owner (0600).

    Returns:
        The written path.
    """
    ensure_directory(path.parent)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    if private:
        temporary.chmod(PRIVATE_FILE_MODE)
    temporary.replace(path)
    return path


def read_text(path: Path) -> str:
    """Read a UTF-8 text file, raising a friendly error when it is missing."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ConfigurationError(f"file {path} does not exist.") from error
    except OSError as error:  # pragma: no cover - depends on the filesystem
        raise ConfigurationError(f"cannot read {path}: {error}.") from error
