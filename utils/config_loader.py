"""Lightweight configuration loader for IIGP v2.0.

Loads the YAML files under ``config/`` and resolves ``${ENV_VAR}`` placeholders
against the process environment (populated from ``.env`` in development).

This is the Phase-0 loader: it intentionally has no heavy dependencies beyond
PyYAML and python-dotenv so it can run before the full stack is installed.
Pydantic v2 schema validation (DD-001/DD-002) is layered on top in later phases.
"""

from __future__ import annotations

import os
import re
from functools import cache
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - guidance for fresh checkouts
    raise ImportError(
        "PyYAML is required. Install dependencies with `pip install -r requirements.txt`."
    ) from exc

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _load_dotenv() -> None:
    """Best-effort load of a local .env without requiring python-dotenv."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        env_path = Path(__file__).resolve().parent.parent / ".env"
        if not env_path.exists():
            return
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def _resolve_env(value: Any) -> Any:
    """Recursively replace ${ENV_VAR} placeholders in nested structures."""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value


@cache
def load_config(name: str, resolve_env: bool = True) -> dict[str, Any]:
    """Load and cache a single config file by stem name (e.g. ``"settings"``)."""
    _load_dotenv()
    path = CONFIG_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _resolve_env(data) if resolve_env else data


def load_all() -> dict[str, dict[str, Any]]:
    """Load every config file in CONFIG_DIR keyed by stem name."""
    return {p.stem: load_config(p.stem) for p in sorted(CONFIG_DIR.glob("*.yaml"))}


if __name__ == "__main__":
    for cfg_name, cfg in load_all().items():
        print(f"loaded config/{cfg_name}.yaml -> {len(cfg)} top-level keys")
