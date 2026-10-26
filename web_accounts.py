"""Personal web logins configured as password hashes in Render, never in Git."""
from functools import lru_cache
import hashlib
import hmac
import json
import os
import re

from werkzeug.security import check_password_hash, generate_password_hash

_DUMMY_HASH = generate_password_hash("unused-invalid-account")


def personal_accounts_enabled() -> bool:
    # A present but invalid/empty configuration fails closed instead of enabling
    # the former shared login again.
    return "DENNI_POV_WEB_USERS" in os.environ


@lru_cache(maxsize=4)
def _parse_accounts(raw: str) -> dict[str, str]:
    try:
        values = json.loads(raw)
        if not isinstance(values, dict) or not values:
            return {}
        accounts = {}
        for address, password_hash in values.items():
            email = str(address).strip().casefold()
            if (not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)
                    or email in accounts or not isinstance(password_hash, str)
                    or not password_hash.startswith(("scrypt:", "pbkdf2:sha256:"))
                    or password_hash.count("$") != 2):
                return {}
            accounts[email] = password_hash
        return accounts
    except (TypeError, ValueError):
        return {}


def _accounts() -> dict[str, str]:
    return _parse_accounts(os.getenv("DENNI_POV_WEB_USERS", ""))


def session_fingerprint(email: str) -> str:
    password_hash = _accounts().get(email)
    if not password_hash:
        return ""
    return hashlib.sha256((email + "\0" + password_hash).encode()).hexdigest()


def authenticate(email: str, password: str) -> str | None:
    """Return the canonical account identity only after password verification."""
    identity = email.strip().casefold()
    accounts = _accounts()
    try:
        valid = check_password_hash(accounts.get(identity, _DUMMY_HASH), password)
    except (ValueError, TypeError):
        valid = False
    return identity if valid and identity in accounts else None


def personal_session_valid(session) -> bool:
    identity = str(session.get("denni_pov_username") or "")
    expected = session_fingerprint(identity)
    supplied = str(session.get("denni_pov_account_fingerprint") or "")
    return bool(expected and supplied and hmac.compare_digest(supplied, expected))
