"""User & Permissions engine facade.

Re-exports current RBAC contract to provide a modular boundary.
"""

from modules.rbac_service import (  # noqa: F401
    DEFAULT_PERMISSION_KEYS,
    ensure_role_permission_sync,
    get_effective_permissions,
    list_known_permission_keys,
    sync_role_permissions_from_legacy_json,
    sync_user_role_assignment,
    user_has_perm,
)
