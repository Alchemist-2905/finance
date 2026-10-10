from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.models.account import Account, AccountType
from app.models.entry import Entry, EntryDirection
from app.models.transaction import Transaction
from app.schemas.reconciliation import AccountReconciliationResponse, GlobalLedgerAuditResponse
from app.core.exceptions import AccountNotFoundError


def reconcile_account(db: Session, account_id: str) -> AccountReconciliationResponse:
    """
    Audits a single account by recalculating its exact balance from historical journal entries
    and comparing it against the high-performance materialized cached_balance.
    """
    account = db.get(Account, account_id)
    if not account:
        raise AccountNotFoundError(account_id=account_id)

    # Sum debits
    debit_stmt = (
        select(func.coalesce(func.sum(Entry.amount), 0))
        .where(Entry.account_id == account_id, Entry.direction == EntryDirection.DEBIT)
    )
    total_debits = int(db.scalar(debit_stmt) or 0)

    # Sum credits
    credit_stmt = (
        select(func.coalesce(func.sum(Entry.amount), 0))
        .where(Entry.account_id == account_id, Entry.direction == EntryDirection.CREDIT)
    )
    total_credits = int(db.scalar(credit_stmt) or 0)

    # Count entries
    count_stmt = select(func.count(Entry.id)).where(Entry.account_id == account_id)
    entry_count = int(db.scalar(count_stmt) or 0)

    # Calculate balance based on accounting equation
    if account.account_type in (AccountType.ASSET, AccountType.EXPENSE):
        computed_balance = total_debits - total_credits
    else:  # LIABILITY, EQUITY, REVENUE
        computed_balance = total_credits - total_debits

    discrepancy = account.cached_balance - computed_balance
    is_reconciled = discrepancy == 0

    return AccountReconciliationResponse(
        account_id=account.id,
        account_name=account.name,
        currency=account.currency,
        cached_balance=account.cached_balance,
        computed_balance=computed_balance,
        is_reconciled=is_reconciled,
        discrepancy=discrepancy,
        total_debits=total_debits,
        total_credits=total_credits,
        entry_count=entry_count,
    )


def audit_global_ledger(db: Session) -> GlobalLedgerAuditResponse:
    """
    Audits the entire financial ledger:
    1. Verifies that the global sum of all debits equals the global sum of all credits.
    2. Runs reconciliation for every individual account.
    """
    # Global debits
    global_debits_stmt = select(func.coalesce(func.sum(Entry.amount), 0)).where(
        Entry.direction == EntryDirection.DEBIT
    )
    total_debits = int(db.scalar(global_debits_stmt) or 0)

    # Global credits
    global_credits_stmt = select(func.coalesce(func.sum(Entry.amount), 0)).where(
        Entry.direction == EntryDirection.CREDIT
    )
    total_credits = int(db.scalar(global_credits_stmt) or 0)

    total_txns = int(db.scalar(select(func.count(Transaction.id))) or 0)
    total_entries = int(db.scalar(select(func.count(Entry.id))) or 0)

    accounts = list(db.scalars(select(Account)).all())
    account_audits: List[AccountReconciliationResponse] = [
        reconcile_account(db, acc.id) for acc in accounts
    ]

    all_accounts_reconciled = all(audit.is_reconciled for audit in account_audits)
    discrepancy = total_debits - total_credits
    is_balanced = (discrepancy == 0) and all_accounts_reconciled

    return GlobalLedgerAuditResponse(
        is_balanced=is_balanced,
        total_debits=total_debits,
        total_credits=total_credits,
        discrepancy=discrepancy,
        total_transactions=total_txns,
        total_entries=total_entries,
        account_audits=account_audits,
    )
