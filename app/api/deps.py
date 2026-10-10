from typing import Optional
from fastapi import Header
from app.core.database import get_db

__all__ = ["get_db", "get_idempotency_key"]


def get_idempotency_key(
    idempotency_key: Optional[str] = Header(
        default=None,
        alias="Idempotency-Key",
        description="Optional unique key to ensure request idempotency (Stripe-style)",
    )
) -> Optional[str]:
    return idempotency_key
