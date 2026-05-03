#!/usr/bin/env python3
"""Shared JSON persistence helpers for runtime config/state files."""

import json
import os
import tempfile


def _default_logger(message: str):
    print(message, flush=True)


def load_json(path: str, default=None, *, encoding: str = 'utf-8', logger=None, label: str = None):
    """Read JSON from path, returning default on any failure."""
    log = logger or _default_logger
    name = label or os.path.basename(path)
    try:
        with open(path, 'r', encoding=encoding) as f:
            return json.load(f)
    except Exception as e:
        log(f"[json] read failed for {name} at {path}: {e}")
        return default


def load_json_or_raise(path: str, *, encoding: str = 'utf-8', logger=None, label: str = None):
    """Read JSON from path and re-raise failures after logging."""
    log = logger or _default_logger
    name = label or os.path.basename(path)
    try:
        with open(path, 'r', encoding=encoding) as f:
            return json.load(f)
    except Exception as e:
        log(f"[json] read failed for {name} at {path}: {e}")
        raise


def save_json_atomic(
    path: str,
    data,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
    encoding: str = 'utf-8',
    logger=None,
    label: str = None,
):
    """Write JSON using a temporary file and atomic replacement."""
    log = logger or _default_logger
    name = label or os.path.basename(path)
    directory = os.path.dirname(os.path.abspath(path)) or '.'
    fd = None
    tmp_path = None
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", suffix='.tmp', dir=directory, text=True)
        with os.fdopen(fd, 'w', encoding=encoding) as f:
            fd = None
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        return True
    except Exception as e:
        log(f"[json] atomic write failed for {name} at {path}: {e}")
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        return False
