from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Header


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    org_id: str
    user_id: str


def resolve_tenant(
    x_tenant_id: Optional[str] = Header(default='default-tenant'),
    x_org_id: Optional[str] = Header(default='default-org'),
    x_user_id: Optional[str] = Header(default='system'),
) -> TenantContext:
    return TenantContext(
        tenant_id=(x_tenant_id or 'default-tenant').strip(),
        org_id=(x_org_id or 'default-org').strip(),
        user_id=(x_user_id or 'system').strip(),
    )
