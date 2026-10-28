"""Record the fingerprint seed each browser actually launched with.

The seed is the master key the engine derives canvas / WebGL / audio noise from,
so "what did the last launch really use" must be recoverable after the fact.
Accounts without a configured seed get a fresh random one on every launch; the
identity is otherwise lost the moment the window closes, and there is no way to
tell what the browser reported to a detection site.
"""
import json
from datetime import datetime
from pathlib import Path

from app.core import config

_DIR = config.DATA_DIR / "last_seeds"


def _path(key: str) -> Path:
    # profile_key 形如 a12_manual / g3_a12_fpcheck，只保留安全字符避免穿越。
    safe = "".join(ch for ch in key if ch.isalnum() or ch in "_-")
    return _DIR / f"{safe}.json"


def remember(key: str | None, seed, engine: str = "") -> None:
    """Persist the seed used by one launch. Never raises: logging must not
    break the launch itself."""
    try:
        seed_int = int(seed)
    except (TypeError, ValueError):
        return
    if not key or seed_int <= 0:
        return
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "seed": seed_int,
            "engine": engine or "",
            "launched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        path = _path(key)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def read(key: str | None) -> dict | None:
    """Last recorded seed for one launch key, or None when unavailable."""
    if not key:
        return None
    try:
        data = json.loads(_path(key).read_text(encoding="utf-8"))
        seed = int(data.get("seed"))
    except Exception:
        return None
    if seed <= 0:
        return None
    return {
        "seed": seed,
        "engine": str(data.get("engine") or ""),
        "launched_at": str(data.get("launched_at") or ""),
    }
