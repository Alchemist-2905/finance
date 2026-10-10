from typing import List
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.account import AccountCreate, AccountResponse, AccountBalanceResponse
from app.schemas.transaction import EntryResponse
from app.services import account_service

router = APIRouter(prefix="/accounts", tags=["Accounts & Wallets"])


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
def create_account(
    account_in: AccountCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new financial account or customer wallet.
    Accounts are classified by standard double-entry types:
    - ASSET (e.g. Bank Reserve, Cash)
    - LIABILITY (e.g. User Wallets, Deposits)
    - EQUITY (e.g. Owner Capital)
    - REVENUE (e.g. Platform Processing Fees)
    - EXPENSE (e.g. Interchange Fees)
    """
    return account_service.create_account(db, account_in)


@router.get("", response_model=List[AccountResponse])
def list_accounts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List all accounts in the ledger."""
    return account_service.list_accounts(db, skip=skip, limit=limit)


@router.get("/{account_id}", response_model=AccountResponse)
def get_account(
    account_id: str,
    db: Session = Depends(get_db),
):
    """Retrieve detailed metadata and current balance for a specific account."""
    return account_service.get_account(db, account_id)


@router.get("/{account_id}/balance", response_model=AccountBalanceResponse)
def get_account_balance(
    account_id: str,
    db: Session = Depends(get_db),
):
    """Get the current available balance for an account with currency formatting."""
    return account_service.get_account_balance(db, account_id)


@router.get("/{account_id}/entries", response_model=List[EntryResponse])
def get_account_entries(
    account_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Retrieve the immutable journal entry history (account statement) for this account."""
    return account_service.get_account_entries(db, account_id, skip=skip, limit=limit)
