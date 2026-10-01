"""Authentication and authorization abstractions.

V1 Security Foundation:
- AuthContext: represents an authenticated user/session
- Permission: enum of available permissions
- RBACManager: role-based access control

Production IAM integration is NOT implemented in V1.
Mark as PARTIAL.
"""

import os
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class Permission(str, Enum):
    VALIDATE = "validate"
    GENERATE = "generate"
    READ_EVIDENCE = "read_evidence"
    WRITE_EVIDENCE = "write_evidence"
    READ_FLAG_PREVIEW = "read_flag_preview"
    EXPORT_PII = "export_pii"
    ADMIN = "admin"
    VIEW_LINEAGE = "view_lineage"
    VIEW_AUDIT = "view_audit"
    RUN_BENCHMARK = "run_benchmark"


class AuthContext:
    """Represents an authenticated user/session.

    In V1, this reads from environment variables.
    Production IAM integration is a LATER item.
    """

    def __init__(self, user_id: str = "", roles: Optional[List[str]] = None):
        self.user_id = user_id or os.environ.get("DQ_USER_ID", "anonymous")
        self.roles = set(roles or os.environ.get("DQ_USER_ROLES", "viewer").split(","))
        self.authenticated = self.user_id != "anonymous"

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "roles": sorted(self.roles),
            "authenticated": self.authenticated,
        }


class RBACManager:
    """Role-based access control manager.

    V1 roles:
    - admin: all permissions
    - operator: validate, generate, read/write evidence, read flag preview, view lineage/audit, benchmark
    - viewer: read evidence, read flag preview, view lineage/audit
    - pii_exporter: read flag preview, export_pii
    """

    ROLE_PERMISSIONS: Dict[str, Set[Permission]] = {
        "admin": set(Permission),
        "operator": {
            Permission.VALIDATE,
            Permission.GENERATE,
            Permission.READ_EVIDENCE,
            Permission.WRITE_EVIDENCE,
            Permission.READ_FLAG_PREVIEW,
            Permission.VIEW_LINEAGE,
            Permission.VIEW_AUDIT,
            Permission.RUN_BENCHMARK,
        },
        "viewer": {
            Permission.READ_EVIDENCE,
            Permission.READ_FLAG_PREVIEW,
            Permission.VIEW_LINEAGE,
            Permission.VIEW_AUDIT,
        },
        "pii_exporter": {
            Permission.READ_FLAG_PREVIEW,
            Permission.EXPORT_PII,
        },
    }

    def __init__(self):
        self._roles: Dict[str, Set[Permission]] = dict(self.ROLE_PERMISSIONS)

    def check_permission(self, auth_context: AuthContext, permission: Permission) -> bool:
        """Check if the auth context has the given permission."""
        for role in auth_context.roles:
            if role in self._roles and permission in self._roles[role]:
                return True
        return False

    def require_permission(self, auth_context: AuthContext, permission: Permission) -> None:
        """Raise if the auth context lacks the permission."""
        if not self.check_permission(auth_context, permission):
            raise PermissionDenied(
                f"User '{auth_context.user_id}' with roles {auth_context.roles} "
                f"lacks permission '{permission.value}'"
            )

    def get_permissions(self, role: str) -> Set[Permission]:
        return set(self._roles.get(role, set()))


class PermissionDenied(Exception):
    """Raised when authorization check fails."""
    pass


class SecretsManager:
    """Abstraction for secrets management.

    V1: reads from environment variables only.
    Production vault integration is LATER.
    """

    @staticmethod
    def get_secret(key: str, default: str = "") -> str:
        """Get a secret value. Reads from environment variable DQ_SECRET_<KEY>."""
        env_key = f"DQ_SECRET_{key.upper()}"
        return os.environ.get(env_key, default)

    @staticmethod
    def get_config(key: str, default: str = "") -> str:
        """Get a config value (not a secret). Reads from DQ_CONFIG_<KEY>."""
        env_key = f"DQ_CONFIG_{key.upper()}"
        return os.environ.get(env_key, default)
