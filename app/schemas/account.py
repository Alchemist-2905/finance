from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.models.account import AccountType


class AccountCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=128, description="Human-readable account label (e.g., 'User Alice Wallet')")
    account_type: AccountType = Field(..., description="Double-entry account classification (ASSET, LIABILITY, EQUITY, REVENUE, EXPENSE)")
    currency: str = Field(default="USD", min_length=3, max_length=3, description="ISO 4217 3-letter currency code")
    allow_negative_balance: bool = Field(default=False, description="Whether this account can hold a negative balance")

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, v: str) -> str:
        return v.upper()


class AccountResponse(BaseModel):
    id: str
    name: str
    account_type: AccountType
    currency: str
    cached_balance: int = Field(..., description="Current balance in cents")
    allow_negative_balance: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AccountBalanceResponse(BaseModel):
    account_id: str
    name: str
    currency: str
    balance_cents: int
    formatted_balance: str  # e.g., "$125.50" or "USD 125.50"
