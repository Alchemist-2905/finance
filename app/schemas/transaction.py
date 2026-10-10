from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.models.entry import EntryDirection
from app.models.transaction import TransactionStatus


class EntryCreate(BaseModel):
    account_id: str = Field(..., description="Target account ID")
    amount: int = Field(..., gt=0, description="Amount in cents (strictly positive integer)")
    direction: EntryDirection = Field(..., description="DEBIT or CREDIT")


class TransactionCreate(BaseModel):
    description: str = Field(..., min_length=3, max_length=255, description="Purpose of transaction")
    reference_id: Optional[str] = Field(default=None, max_length=128, description="External reference (e.g. invoice/order ID)")
    entries: List[EntryCreate] = Field(..., min_length=2, description="At least two journal legs")

    @model_validator(mode="after")
    def validate_double_entry_balance(self):
        debits = sum(e.amount for e in self.entries if e.direction == EntryDirection.DEBIT)
        credits = sum(e.amount for e in self.entries if e.direction == EntryDirection.CREDIT)
        if debits != credits:
            raise ValueError(
                f"Double-entry violation: Total debits ({debits} cents) must equal total credits ({credits} cents)."
            )
        return self


class TransferRequest(BaseModel):
    """
    High-level request for point-to-point wallet transfers.
    Constructs the appropriate double-entry legs automatically based on account types.
    """
    source_account_id: str = Field(..., description="Origin account ID")
    destination_account_id: str = Field(..., description="Destination account ID")
    amount: int = Field(..., gt=0, description="Transfer amount in cents")
    description: str = Field(..., min_length=3, max_length=255, description="Transfer memo/description")
    reference_id: Optional[str] = Field(default=None, max_length=128, description="Optional external order or payment ID")


class EntryResponse(BaseModel):
    id: str
    transaction_id: str
    account_id: str
    amount: int
    direction: EntryDirection
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TransactionResponse(BaseModel):
    id: str
    description: str
    reference_id: Optional[str]
    idempotency_key: Optional[str]
    status: TransactionStatus
    reversed_by_id: Optional[str]
    created_at: datetime
    entries: List[EntryResponse]

    model_config = ConfigDict(from_attributes=True)
