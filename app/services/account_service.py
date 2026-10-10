from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models.account import Account
from app.models.entry import Entry
from app.schemas.account import AccountCreate, AccountBalanceResponse
from app.core.exceptions import AccountNotFoundError


def create_account(db: Session, account_in: AccountCreate) -> Account:
    account = Account(
        name=account_in.name,
        account_type=account_in.account_type,
        currency=account_in.currency,
        allow_negative_balance=account_in.allow_negative_balance,
        cached_balance=0,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def get_account(db: Session, account_id: str) -> Account:
    account = db.get(Account, account_id)
    if not account:
        raise AccountNotFoundError(account_id=account_id)
    return account


def get_account_balance(db: Session, account_id: str) -> AccountBalanceResponse:
    account = get_account(db, account_id)
    dollars = account.cached_balance / 100.0
    formatted = f"{dollars:,.2f} {account.currency}"
    return AccountBalanceResponse(
        account_id=account.id,
        name=account.name,
        currency=account.currency,
        balance_cents=account.cached_balance,
        formatted_balance=formatted,
    )


def list_accounts(db: Session, skip: int = 0, limit: int = 100) -> List[Account]:
    stmt = select(Account).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def get_account_entries(db: Session, account_id: str, skip: int = 0, limit: int = 100) -> List[Entry]:
    # Verify account exists
    get_account(db, account_id)
    stmt = (
        select(Entry)
        .where(Entry.account_id == account_id)
        .order_by(Entry.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())
