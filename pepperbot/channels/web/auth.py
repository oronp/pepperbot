"""Auth utilities for the web UI channel."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from pathlib import Path


# ---------------------------------------------------------------------------
# Password hashing (PBKDF2 via stdlib, no extra deps)
# ---------------------------------------------------------------------------

_ITERATIONS = 260_000
_ALGO = "sha256"


def hash_password(password: str) -> str:
    """Return a salted PBKDF2 hash string for *password*."""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(_ALGO, password.encode(), salt.encode(), _ITERATIONS)
    return f"pbkdf2:{_ALGO}:{_ITERATIONS}:{salt}:{base64.b64encode(dk).decode()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Return True if *password* matches *stored_hash*."""
    try:
        _, algo, iters, salt, hash_b64 = stored_hash.split(":", 4)
        dk = hashlib.pbkdf2_hmac(algo, password.encode(), salt.encode(), int(iters))
        return hmac.compare_digest(base64.b64decode(hash_b64), dk)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Session cookie signing (HMAC-SHA256, no extra deps)
# ---------------------------------------------------------------------------


def sign_session(payload: dict, *, secret: str) -> str:
    """Return a signed token encoding *payload*."""
    data = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode()
    sig = hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}.{sig}"


def verify_session(token: str, *, secret: str) -> dict | None:
    """Return the payload dict if *token* is valid, else None."""
    try:
        data, sig = token.rsplit(".", 1)
        expected = hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        return json.loads(base64.urlsafe_b64decode(data))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# User store
# ---------------------------------------------------------------------------


def load_users(users_file: Path) -> list[dict]:
    """Load users list from *users_file*. Returns [] if file missing."""
    if not users_file.exists():
        return []
    return json.loads(users_file.read_text())


def save_users(users: list[dict], users_file: Path) -> None:
    """Write *users* list to *users_file*, creating parent dirs as needed."""
    users_file.parent.mkdir(parents=True, exist_ok=True)
    users_file.write_text(json.dumps(users, indent=2))


def authenticate(username: str, password: str, users_file: Path) -> bool:
    """Return True if *username*/*password* match an entry in *users_file*."""
    for user in load_users(users_file):
        if user.get("username") == username:
            return verify_password(password, user.get("password_hash", ""))
    return False
