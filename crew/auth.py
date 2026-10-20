"""RBAC skeleton (owner/operator/viewer). No network, no real 2FA yet."""
import enum
class Role(str, enum.Enum): OWNER="owner"; OPERATOR="operator"; VIEWER="viewer"
PERMS = {Role.OWNER: {"view","approve","kill","mode_change","config","research"},
         Role.OPERATOR: {"view","kill","research"}, Role.VIEWER: {"view"}}
class Forbidden(Exception): pass
def require(role: Role, perm: str) -> None:
    if perm not in PERMS.get(role, set()): raise Forbidden(f"{role} lacks {perm}")
