from typing import Annotated

from fastapi import Header

from app.auth.dependencies import require_roles
from app.constants import Role

# Roles allowed to move money (admins have no payments functionality).
money_user = require_roles(Role.USER, Role.MERCHANT)
admin_only = require_roles(Role.ADMIN)
merchant_only = require_roles(Role.MERCHANT)

IdempotencyKeyHeader = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        description="Unique key (e.g. a UUID) that makes this money-moving request safe to retry.",
    ),
]
