from __future__ import annotations

from dataclasses import dataclass

from .database import Database


class AccessDenied(PermissionError):
    pass


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    roles: tuple[str, ...]
    reason: str


class AccessService:
    """Union of active role grants; any matching explicit deny wins."""

    def __init__(self, db: Database):
        self.db = db

    def decide(
        self, user_id: str, action: str, *, stage: str | None = None,
        purpose: str | None = None,
    ) -> AccessDecision:
        user = self.db.one("SELECT active FROM users WHERE user_id=?", (user_id,))
        if not user or not user["active"]:
            return AccessDecision(False, (), "unknown or inactive user")
        rows = self.db.all(
            """SELECT ur.role_id,p.action,p.stage,p.purpose,p.effect
               FROM user_roles ur JOIN role_permissions p ON p.role_id=ur.role_id
               WHERE ur.user_id=? AND (p.action=? OR p.action='*')
               AND (p.stage IS NULL OR p.stage=? OR p.stage='*')
               AND (p.purpose IS NULL OR p.purpose=? OR p.purpose='*')""",
            (user_id, action, stage, purpose),
        )
        roles = tuple(sorted({row["role_id"] for row in rows}))
        if any(row["effect"] == "deny" for row in rows):
            return AccessDecision(False, roles, "explicit deny")
        if any(row["effect"] == "allow" for row in rows):
            return AccessDecision(True, roles, "role grant")
        return AccessDecision(False, roles, "no matching grant")

    def require(
        self, user_id: str, action: str, *, stage: str | None = None,
        purpose: str | None = None,
    ) -> AccessDecision:
        decision = self.decide(user_id, action, stage=stage, purpose=purpose)
        if not decision.allowed:
            raise AccessDenied(f"{action} denied: {decision.reason}")
        return decision
