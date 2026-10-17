"""OPC UA users, passwords and permissions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass

from asyncua import ua
from asyncua.crypto.permission_rules import USER_TYPES, PermissionRuleset, User, UserRole

from .config import Config

# scrypt cost parameters (about 16 MB and 50 ms per hash on a laptop).
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def hash_password(password: str, salt: bytes | None = None) -> str:
    """Encode as scrypt$N$r$p$salt$hash (base64), for opcua.users.password_hash."""
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = encoded.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                                dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


@dataclass
class BridgeUser(User):
    """An asyncua user plus whether it may change the game (write values, call methods)."""

    can_write: bool = False


class UserManager:
    """Logs in configured users and, if allowed, anonymous clients. Never grants asyncua's Admin role."""

    def __init__(self, config: Config) -> None:
        self._anonymous = config.anonymous
        self._users = {u.name: u for u in config.users}

    def get_user(self, iserver, username: str | None = None, password: str | None = None,
                 certificate=None) -> BridgeUser | None:
        if not username:
            if self._anonymous == "none":
                return None
            return BridgeUser(role=UserRole.User, name=None, can_write=self._anonymous == "write")
        user = self._users.get(username)
        if user is None or password is None or not verify_password(password, user.password_hash):
            return None
        return BridgeUser(role=UserRole.User, name=username, can_write=user.role == "write")


WRITE_TYPES = {ua.NodeId(ua.ObjectIds.WriteRequest_Encoding_DefaultBinary),
               ua.NodeId(ua.ObjectIds.CallRequest_Encoding_DefaultBinary)}
ALL_USER_TYPES = {ua.NodeId(t) for t in USER_TYPES}


class Ruleset(PermissionRuleset):
    """Every logged-in user may browse, read and subscribe; only write users may write or call methods.

    asyncua checks this for every request, before it reaches a service. It never
    allows address-space edits (AddNodes and so on), which need the Admin role.
    """

    def check_validity(self, user, action_type_id, body) -> bool:
        if action_type_id not in ALL_USER_TYPES:
            return False
        if action_type_id in WRITE_TYPES:
            return bool(getattr(user, "can_write", False))
        return True
