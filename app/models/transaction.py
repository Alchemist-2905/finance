import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Enum as SQLEnum, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base


class TransactionStatus(str, enum.Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


def generate_transaction_id() -> str:
    return f"txn_{uuid.uuid4().hex[:24]}"


class Transaction(Base):
    """
    Financial Transaction grouping two or more atomic double-entry legs.
    Transactions are append-only. To undo a transaction, create a compensating/reversal transaction.
    """
    __tablename__ = "transactions"

    id = Column(String(32), primary_key=True, default=generate_transaction_id)
    description = Column(String(255), nullable=False)
    reference_id = Column(String(128), nullable=True, index=True)
    idempotency_key = Column(String(128), nullable=True, unique=True, index=True)
    status = Column(SQLEnum(TransactionStatus), nullable=False, default=TransactionStatus.POSTED)
    
    # If this transaction was reversed, points to the reversing transaction
    reversed_by_id = Column(String(32), ForeignKey("transactions.id"), nullable=True)

    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    entries = relationship("Entry", back_populates="transaction", cascade="all, delete-orphan", lazy="joined")
    reversing_transaction = relationship("Transaction", remote_side=[id], foreign_keys=[reversed_by_id])

    def __repr__(self) -> str:
        return f"<Transaction(id='{self.id}', status='{self.status}', description='{self.description}')>"
