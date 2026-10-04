"""Gate F0: list models available to YOUR key and confirm NVIDIA Nemotron IDs + prices.

    python scripts/list_models.py            # prints NVIDIA models, saves runs/models-<date>.json
Never prints the API key.
"""

import json
import sys
from datetime import date

import httpx

from reliability_agent.config import REPO_ROOT, api_key, load_config


def main() -> int:
    key = api_key()
    if not key:
        print("NEBIUS_API_KEY is not set (create .env from .env.example).", file=sys.stderr)
        return 2
    base = load_config()["nebius"]["base_url"].rstrip("/")
    r = httpx.get(f"{base}/models", params={"verbose": "true"},
                  headers={"Authorization": f"Bearer {key}"}, timeout=30)
    r.raise_for_status()
    data = r.json().get("data", r.json())
    out = REPO_ROOT / "runs" / f"models-{date.today()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    nvidia = [m for m in data if "nvidia" in json.dumps(m).lower()]
    rel = out.relative_to(REPO_ROOT)
    print(f"{len(data)} models visible, {len(nvidia)} NVIDIA. Saved to {rel}")
    for m in nvidia:
        print("-", m.get("id"), "| pricing:", m.get("pricing") or m.get("price") or "n/a")
    cfg_models = load_config()["nebius"]["models"]
    ids = {m.get("id") for m in data}
    for tier, mid in cfg_models.items():
        print(f"config {tier:<9} {mid}: {'OK' if mid in ids else 'NOT AVAILABLE -> update config'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
