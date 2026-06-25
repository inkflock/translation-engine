"""Minimal .env loader so the API key can live in a gitignored file.

Only what the harness needs: KEY=VALUE lines, optional `export ` prefix,
optional single/double quotes, # comments. Existing environment variables
always win over the file.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: Path | str = ".env") -> dict[str, str]:
    """Load variables from a .env file into os.environ.

    Returns only the variables actually set by this call (already-set
    environment variables are never overridden). A missing file is not an
    error — returns an empty dict.
    """
    env_path = Path(path)
    if not env_path.is_file():
        return {}

    loaded: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if not key or key in os.environ:
            continue
        os.environ[key] = value
        loaded[key] = value
    return loaded
