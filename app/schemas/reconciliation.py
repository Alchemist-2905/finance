from typing import List
from pydantic import BaseModel, Field


class AccountReconciliationResponse(BaseModel):
    account_id: str
    account_name: str
    currency: str
    cached_balance: int = Field(..., description="Fast cached balance stored on account record")
    computed_balance: int = Field(..., description="Balance recomputed from all historical journal entries")
    is_reconciled: bool = Field(..., description="True if cached balance matches computed balance exactly")
    discrepancy: int = Field(..., description="Difference between cached and computed balances")
    total_debits: int
    total_credits: int
    entry_count: int


class GlobalLedgerAuditResponse(BaseModel):
    is_balanced: bool = Field(..., description="True if sum of all debits across the entire ledger equals credits")
    total_debits: int = Field(..., description="Sum of all debit entries across all transactions")
    total_credits: int = Field(..., description="Sum of all credit entries across all transactions")
    discrepancy: int
    total_transactions: int
    total_entries: int
    account_audits: List[AccountReconciliationResponse]
