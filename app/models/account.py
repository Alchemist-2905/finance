import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, BigInteger, Boolean, DateTime, Enum as SQLEnum, CheckConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base


class AccountType(str, enum.Enum):
    ASSET = "ASSET"          # Cash, Bank Accounts, Receivables (Debit normal)
    LIABILITY = "LIABILITY"  # Customer Wallets, Accounts Payable (Credit normal)
    EQUITY = "EQUITY"        # Retained Earnings, Owner Capital (Credit normal)
    REVENUE = "REVENUE"      # Processing Fees, Subscription Income (Credit normal)
    EXPENSE = "EXPENSE"      # Interchange, Server Costs (Debit normal)


def generate_account_id() -> str:
    return f"acc_{uuid.uuid4().hex[:24]}"


class Account(Base):
    __tablename__ = "accounts"

    id = Column(String(32), primary_key=True, default=generate_account_id)
    name = Column(String(128), nullable=False, index=True)
    account_type = Column(SQLEnum(AccountType), nullable=False)
    currency = Column(String(3), nullable=False, index=True)  # e.g., 'USD', 'EUR'
    
    # Materialized/cached balance in cents (minor currency unit)
    # Allows O(1) balance lookups and row-level locking checks
    cached_balance = Column(BigInteger, nullable=False, default=0)
    
    # If False, any transaction driving this account below 0 will be rejected
    allow_negative_balance = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        CheckConstraint(
            "(allow_negative_balance = 1) OR (cached_balance >= 0)",
            name="check_non_negative_balance",
        ),
    )

    entries = relationship("Entry", back_populates="account", lazy="select")

    def __repr__(self) -> str:
        return f"<Account(id='{self.id}', name='{self.name}', type='{self.account_type}', balance={self.cached_balance} {self.currency})>"
