import enum
from datetime import datetime, timezone, timedelta
from sqlalchemy import Column, String, Integer, Text, DateTime, Enum as SQLEnum
from app.core.database import Base
from app.core.config import settings


class IdempotencyStatus(str, enum.Enum):
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"


class IdempotencyRecord(Base):
    """
    Stores idempotency state for critical mutation operations (e.g., transfers).
    Ensures safe client retries without double-execution.
    """
    __tablename__ = "idempotency_records"

    key = Column(String(128), primary_key=True)
    request_hash = Column(String(64), nullable=False)  # SHA-256 hex digest
    status = Column(SQLEnum(IdempotencyStatus), nullable=False, default=IdempotencyStatus.PROCESSING)
    
    response_code = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc) + timedelta(hours=settings.IDEMPOTENCY_EXPIRATION_HOURS),
    )

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at.replace(tzinfo=timezone.utc)

    def __repr__(self) -> str:
        return f"<IdempotencyRecord(key='{self.key}', status='{self.status}')>"
