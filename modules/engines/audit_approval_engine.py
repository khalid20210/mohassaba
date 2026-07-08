"""Audit & Approval engine facade.

Groups approval workflow APIs and audit event recording behind one module.
"""

from modules.approval_service import (  # noqa: F401
    approve_request,
    create_approval_request,
    ensure_operation_or_create_request,
    get_request_by_id,
    list_pending_requests,
    list_requests,
    reject_request,
)
from modules.audit_service import record_audit_event  # noqa: F401
