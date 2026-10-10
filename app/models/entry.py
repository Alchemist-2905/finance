import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, BigInteger, DateTime, Enum as SQLEnum, ForeignKey, CheckConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base


class EntryDirection(str, enum.Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


def generate_entry_id() -> str:
    return f"ent_{uuid.uuid4().hex[:24]}"


class Entry(Base):
    """
    Immutable Journal Entry Leg.
    In double-entry bookkeeping, an Entry represents one leg of a multi-legged Transaction.
    Entries are strictly append-only. They are NEVER modified or deleted.
    """
    __tablename__ = "entries"

    id = Column(String(32), primary_key=True, default=generate_entry_id)
    transaction_id = Column(String(32), ForeignKey("transactions.id", ondelete="RESTRICT"), nullable=False, index=True)
    account_id = Column(String(32), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    
    # Amount in cents (strictly positive integer)
    amount = Column(BigInteger, nullable=False)
    direction = Column(SQLEnum(EntryDirection), nullable=False)

    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        CheckConstraint("amount > 0", name="check_positive_amount"),
    )

    transaction = relationship("Transaction", back_populates="entries")
    account = relationship("Account", back_populates="entries")

    def __repr__(self) -> str:
        return f"<Entry(id='{self.id}', txn='{self.transaction_id}', account='{self.account_id}', dir='{self.direction}', amount={self.amount})>"
