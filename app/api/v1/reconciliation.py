from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.reconciliation import (
    AccountReconciliationResponse,
    GlobalLedgerAuditResponse,
)
from app.services import reconciliation_service

router = APIRouter(prefix="/reconciliation", tags=["Audit & Reconciliation"])


@router.get("/accounts/{account_id}", response_model=AccountReconciliationResponse)
def reconcile_account(
    account_id: str,
    db: Session = Depends(get_db),
):
    """
    Audit an individual account.
    Recalculates balance from scratch by summing all historical journal entries
    and compares it to the fast cached balance to verify mathematical integrity.
    """
    return reconciliation_service.reconcile_account(db, account_id)


@router.get("/audit", response_model=GlobalLedgerAuditResponse)
def audit_global_ledger(
    db: Session = Depends(get_db),
):
    """
    Run a full ledger audit.
    Verifies that total debits equal total credits across all entries in the system
    and that all individual account balances match their journal histories.
    """
    return reconciliation_service.audit_global_ledger(db)
