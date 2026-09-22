"""Global configuration - freedom-accounts platform."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
BROWSER_PROFILES_DIR = DATA_DIR / "browser_profiles"

ENV_PATH = BASE_DIR / ".env"


def _load_env_file(path: Path) -> None:
    """Load KEY=VALUE pairs into os.environ (real env vars take precedence).

    Supports: blank lines, # comments, optional `export ` prefix,
    single/double quoted values, inline ` # comment` after unquoted values.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key:
            os.environ.setdefault(key, value)


_load_env_file(ENV_PATH)

# CloakBrowser license key — file-configured ONLY (.env). Not editable at runtime;
# changes require editing .env and restarting the service.
CLOAKBROWSER_LICENSE_KEY = os.environ.get("CLOAKBROWSER_LICENSE_KEY", "").strip()

DB_PATH = DATA_DIR / "platform.db"

# Admin authentication
ADMIN_USER = os.environ.get("FA_ADMIN_USER", "admin")
# Default admin password; change it on the System Settings page after first login.
INITIAL_ADMIN_PASSWORD = os.environ.get("FA_ADMIN_PASSWORD", "admin123")
DEFAULT_JWT_SECRET = "change-me-in-production-please"
JWT_SECRET = os.environ.get("FA_JWT_SECRET", DEFAULT_JWT_SECRET)
JWT_EXPIRE_HOURS = int(os.environ.get("FA_JWT_EXPIRE_HOURS", "24"))

# Encryption key for sensitive DB fields (passwords, TOTP, proxy auth, upstream keys)
ENCRYPTION_KEY = os.environ.get("FA_ENCRYPTION_KEY", "").strip()
if not ENCRYPTION_KEY:
    raise RuntimeError(
        "FA_ENCRYPTION_KEY is required in .env; generate one with: "
        "python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )

# Server
HOST = os.environ.get("FA_HOST", "127.0.0.1")
PORT = int(os.environ.get("FA_PORT", "8000"))

# Callback
CALLBACK_TIMEOUT_SECONDS = float(os.environ.get("FA_CALLBACK_TIMEOUT", "15"))

# Task scheduling
# Hard cap per group; can also be lowered by the group's own concurrency config.
MAX_CONCURRENCY_PER_GROUP = int(os.environ.get("FA_MAX_CONCURRENCY", "5"))
# Safety boundary for random account interval (ms); the group config may narrow it but not exceed it.
INTERVAL_MIN_MS = 1000
INTERVAL_MAX_MS = 600000

for _d in (DATA_DIR, LOGS_DIR, BROWSER_PROFILES_DIR):
    _d.mkdir(parents=True, exist_ok=True)

if HOST not in {"127.0.0.1", "localhost"}:
    if JWT_SECRET == DEFAULT_JWT_SECRET:
        raise RuntimeError("FA_JWT_SECRET must be changed before non-local deployment")
    if INITIAL_ADMIN_PASSWORD == "admin123":
        raise RuntimeError("FA_ADMIN_PASSWORD must be changed before non-local deployment")
