"""Configuration loading: YAML defaults + environment overrides. No secrets in YAML."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "default.yaml"

_ENV_OVERRIDES: dict[str, tuple[str, ...]] = {
    "RA_CAMERA_URI": ("camera", "uri"),
    "NEBIUS_BASE_URL": ("nebius", "base_url"),
    "RA_MODEL_FAST": ("nebius", "models", "fast"),
    "RA_MODEL_REASONING": ("nebius", "models", "reasoning"),
    "RA_BUDGET_TOTAL_USD": ("budget", "total_usd"),
    "RA_BUDGET_SOFT_CAP_USD": ("budget", "soft_cap_usd"),
    "RA_BUDGET_DEMO_CAP_USD": ("budget", "demo_cap_usd"),
    "RA_BUDGET_HARD_CAP_USD": ("budget", "hard_cap_usd"),
    "RA_DB_PATH": ("storage", "db_path"),
}


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader (no dependency). Existing env vars win."""
    path = path or REPO_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _set(d: dict[str, Any], keys: tuple[str, ...], value: Any) -> None:
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    old = d.get(keys[-1])
    if isinstance(old, (int, float)) and not isinstance(old, bool):
        value = type(old)(float(value))
    d[keys[-1]] = value


def deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path | None = None, *, env: bool = True) -> dict[str, Any]:
    cfg = yaml.safe_load(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    if path:
        cfg = deep_merge(cfg, yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})
    if env:
        load_dotenv()
        for var, keys in _ENV_OVERRIDES.items():
            if os.environ.get(var):
                _set(cfg, keys, os.environ[var])
    return cfg


def api_key() -> str | None:
    """Return the Token Factory key from the environment, or None (local mode)."""
    load_dotenv()
    key = os.environ.get("NEBIUS_API_KEY", "").strip()
    return key or None
