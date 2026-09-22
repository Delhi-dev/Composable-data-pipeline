from __future__ import annotations

from dataclasses import dataclass

from .database import PostgreSQLDatabase


class AccessDenied(PermissionError):
    pass


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    roles: tuple[str, ...]
    reason: str


class AccessService:
    """Union matching grants from all active roles; an explicit deny wins."""

    def __init__(self, db: PostgreSQLDatabase):
        self.db = db

    def decide(
        self,
        user_id: str,
        action: str,
        *,
        stage: str | None = None,
        purpose: str | None = None,
    ) -> AccessDecision:
        user = self.db.one(
            "SELECT active FROM cbcr_control.user_account WHERE user_id=%s", (user_id,)
        )
        if not user or not user["active"]:
            return AccessDecision(False, (), "unknown or inactive user")
        rows = self.db.all(
            """SELECT ur.role_id,p.action,p.stage,p.purpose,p.effect
               FROM cbcr_control.user_role ur
               JOIN cbcr_control.role r ON r.role_id=ur.role_id AND r.active=true
               JOIN cbcr_control.role_permission p ON p.role_id=ur.role_id
               WHERE ur.user_id=%s AND (p.action=%s OR p.action='*')
                 AND (p.stage IS NULL OR p.stage=%s OR p.stage='*')
                 AND (p.purpose IS NULL OR p.purpose=%s OR p.purpose='*')""",
            (user_id, action, stage, purpose),
        )
        roles = tuple(sorted({row["role_id"] for row in rows}))
        if any(row["effect"] == "deny" for row in rows):
            return AccessDecision(False, roles, "explicit deny")
        if any(row["effect"] == "allow" for row in rows):
            return AccessDecision(True, roles, "role grant")
        return AccessDecision(False, roles, "no matching grant")

    def require(
        self,
        user_id: str,
        action: str,
        *,
        stage: str | None = None,
        purpose: str | None = None,
    ) -> AccessDecision:
        decision = self.decide(user_id, action, stage=stage, purpose=purpose)
        if not decision.allowed:
            raise AccessDenied(f"{action} denied: {decision.reason}")
        return decision

