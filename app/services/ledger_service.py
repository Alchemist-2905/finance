import hashlib
import json
import threading
from typing import List, Optional, Tuple, Dict
from sqlalchemy.orm import Session
from sqlalchemy import select

# Lock for SQLite local concurrency (PostgreSQL uses native row-level SELECT FOR UPDATE)
_sqlite_ledger_lock = threading.Lock()

from app.models.account import Account, AccountType
from app.models.entry import Entry, EntryDirection
from app.models.transaction import Transaction, TransactionStatus
from app.models.idempotency import IdempotencyRecord, IdempotencyStatus
from app.schemas.transaction import TransactionCreate, TransferRequest, TransactionResponse
from app.core.exceptions import (
    InsufficientFundsError,
    UnbalancedTransactionError,
    EmptyTransactionError,
    AccountNotFoundError,
    CurrencyMismatchError,
    InvalidAmountError,
    IdempotencyConflictError,
    IdempotencyPayloadMismatchError,
    TransactionAlreadyReversedError,
)


def compute_balance_delta(account_type: AccountType, direction: EntryDirection, amount: int) -> int:
    """
    Computes how an entry affects an account's balance based on double-entry accounting rules:
    - ASSET & EXPENSE: Normal balance is DEBIT. (DEBIT = +amount, CREDIT = -amount)
    - LIABILITY, EQUITY & REVENUE: Normal balance is CREDIT. (CREDIT = +amount, DEBIT = -amount)
    """
    if account_type in (AccountType.ASSET, AccountType.EXPENSE):
        return amount if direction == EntryDirection.DEBIT else -amount
    else:
        return amount if direction == EntryDirection.CREDIT else -amount


def get_transfer_directions(source_type: AccountType, dest_type: AccountType) -> Tuple[EntryDirection, EntryDirection]:
    """
    Determines the debit/credit directions to move funds from source to destination.
    Decreasing source:
      - If LIABILITY/EQUITY/REVENUE: DEBIT decreases balance.
      - If ASSET/EXPENSE: CREDIT decreases balance.
    Increasing destination:
      - If LIABILITY/EQUITY/REVENUE: CREDIT increases balance.
      - If ASSET/EXPENSE: DEBIT increases balance.
    """
    source_dir = (
        EntryDirection.DEBIT
        if source_type in (AccountType.LIABILITY, AccountType.EQUITY, AccountType.REVENUE)
        else EntryDirection.CREDIT
    )
    dest_dir = (
        EntryDirection.CREDIT
        if dest_type in (AccountType.LIABILITY, AccountType.EQUITY, AccountType.REVENUE)
        else EntryDirection.DEBIT
    )
    return source_dir, dest_dir


def execute_transaction(
    db: Session,
    txn_in: TransactionCreate,
    idempotency_key: Optional[str] = None,
) -> Transaction:
    """
    Core Double-Entry Ledger Engine:
    1. Validates strict double-entry balance: sum(debits) == sum(credits).
    2. Deterministic Row-Level Locking: Locks all touched accounts in ascending ID order to prevent deadlocks.
    3. Validates currency uniformity across all entries.
    4. Enforces non-negative balance constraints.
    5. Atomically creates the immutable Transaction and Journal Entry legs and updates cached balances.
    """
    if len(txn_in.entries) < 2:
        raise EmptyTransactionError()

    total_debits = sum(e.amount for e in txn_in.entries if e.direction == EntryDirection.DEBIT)
    total_credits = sum(e.amount for e in txn_in.entries if e.direction == EntryDirection.CREDIT)

    if total_debits != total_credits:
        raise UnbalancedTransactionError(total_debits=total_debits, total_credits=total_credits)

    for entry_in in txn_in.entries:
        if entry_in.amount <= 0:
            raise InvalidAmountError(amount=entry_in.amount)

    # Deterministic lock ordering: sort account IDs to guarantee deadlock freedom
    distinct_account_ids = sorted(list(set(e.account_id for e in txn_in.entries)))

    is_sqlite = db.get_bind().dialect.name == "sqlite"
    if is_sqlite:
        with _sqlite_ledger_lock:
            db.expire_all()
            return _execute_internal(db, txn_in, idempotency_key, distinct_account_ids)
    return _execute_internal(db, txn_in, idempotency_key, distinct_account_ids)


def _execute_internal(
    db: Session,
    txn_in: TransactionCreate,
    idempotency_key: Optional[str],
    distinct_account_ids: List[str],
) -> Transaction:
    # Fetch and lock accounts (with_for_update natively locks rows in PostgreSQL)
    stmt = (
        select(Account)
        .where(Account.id.in_(distinct_account_ids))
        .order_by(Account.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    accounts = {acc.id: acc for acc in db.scalars(stmt).all()}

    # Verify all accounts exist
    for acc_id in distinct_account_ids:
        if acc_id not in accounts:
            raise AccountNotFoundError(account_id=acc_id)

    # Verify currency consistency across all involved accounts
    base_currency = accounts[distinct_account_ids[0]].currency
    for acc_id in distinct_account_ids:
        if accounts[acc_id].currency != base_currency:
            raise CurrencyMismatchError(
                expected_currency=base_currency,
                actual_currency=accounts[acc_id].currency,
                account_id=acc_id,
            )

    # Pre-calculate projected balance updates and verify constraints
    deltas: Dict[str, int] = {acc_id: 0 for acc_id in distinct_account_ids}
    for entry_in in txn_in.entries:
        acc = accounts[entry_in.account_id]
        delta = compute_balance_delta(acc.account_type, entry_in.direction, entry_in.amount)
        deltas[entry_in.account_id] += delta

    for acc_id, net_delta in deltas.items():
        acc = accounts[acc_id]
        projected_balance = acc.cached_balance + net_delta
        if projected_balance < 0 and not acc.allow_negative_balance:
            raise InsufficientFundsError(
                account_id=acc.id,
                current_balance=acc.cached_balance,
                requested_amount=abs(net_delta),
            )

    # Persist the Transaction header
    transaction = Transaction(
        description=txn_in.description,
        reference_id=txn_in.reference_id,
        idempotency_key=idempotency_key,
        status=TransactionStatus.POSTED,
    )
    db.add(transaction)
    db.flush()

    # Persist the immutable Entry legs and apply balance updates
    for entry_in in txn_in.entries:
        acc = accounts[entry_in.account_id]
        delta = compute_balance_delta(acc.account_type, entry_in.direction, entry_in.amount)
        acc.cached_balance += delta

        entry = Entry(
            transaction_id=transaction.id,
            account_id=entry_in.account_id,
            amount=entry_in.amount,
            direction=entry_in.direction,
        )
        db.add(entry)

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        if "check_non_negative_balance" in str(exc) or "CHECK constraint failed" in str(exc):
            raise InsufficientFundsError(
                account_id=distinct_account_ids[0],
                current_balance=0,
                requested_amount=0,
            )
        raise
    db.refresh(transaction)
    return transaction


def transfer_funds(
    db: Session,
    transfer_in: TransferRequest,
    idempotency_key: Optional[str] = None,
) -> Transaction:
    """
    Convenience method for peer-to-peer transfers. Automatically converts the transfer
    into valid double-entry debit and credit legs based on account classifications.
    """
    is_sqlite = db.get_bind().dialect.name == "sqlite"
    if is_sqlite:
        with _sqlite_ledger_lock:
            db.expire_all()
            return _transfer_funds_internal(db, transfer_in, idempotency_key)
    return _transfer_funds_internal(db, transfer_in, idempotency_key)


def _transfer_funds_internal(
    db: Session,
    transfer_in: TransferRequest,
    idempotency_key: Optional[str] = None,
) -> Transaction:
    if transfer_in.amount <= 0:
        raise InvalidAmountError(amount=transfer_in.amount)

    if transfer_in.source_account_id == transfer_in.destination_account_id:
        raise UnbalancedTransactionError(total_debits=0, total_credits=0)

    # Fetch accounts to inspect account types
    source = db.get(Account, transfer_in.source_account_id)
    if not source:
        raise AccountNotFoundError(account_id=transfer_in.source_account_id)

    dest = db.get(Account, transfer_in.destination_account_id)
    if not dest:
        raise AccountNotFoundError(account_id=transfer_in.destination_account_id)

    source_dir, dest_dir = get_transfer_directions(source.account_type, dest.account_type)

    from app.schemas.transaction import EntryCreate

    txn_in = TransactionCreate(
        description=transfer_in.description,
        reference_id=transfer_in.reference_id,
        entries=[
            EntryCreate(
                account_id=transfer_in.source_account_id,
                amount=transfer_in.amount,
                direction=source_dir,
            ),
            EntryCreate(
                account_id=transfer_in.destination_account_id,
                amount=transfer_in.amount,
                direction=dest_dir,
            ),
        ],
    )

    return _execute_internal(
        db=db,
        txn_in=txn_in,
        idempotency_key=idempotency_key,
        distinct_account_ids=sorted([transfer_in.source_account_id, transfer_in.destination_account_id]),
    )


def reverse_transaction(
    db: Session,
    transaction_id: str,
    description: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Transaction:
    """
    Double-entry accounting maintains an immutable audit trail: historical entries are NEVER deleted or updated.
    To reverse a posted transaction, we construct a compensating transaction with inverted legs.
    """
    orig_txn = db.get(Transaction, transaction_id)
    if not orig_txn:
        raise AccountNotFoundError(account_id=transaction_id)

    if orig_txn.status == TransactionStatus.REVERSED:
        raise TransactionAlreadyReversedError(transaction_id=transaction_id)

    # Invert directions: DEBIT -> CREDIT, CREDIT -> DEBIT
    from app.schemas.transaction import EntryCreate

    reversed_entries = []
    for entry in orig_txn.entries:
        opp_dir = EntryDirection.CREDIT if entry.direction == EntryDirection.DEBIT else EntryDirection.DEBIT
        reversed_entries.append(
            EntryCreate(
                account_id=entry.account_id,
                amount=entry.amount,
                direction=opp_dir,
            )
        )

    memo = description or f"Reversal of {orig_txn.id}: {orig_txn.description}"
    txn_in = TransactionCreate(
        description=memo,
        reference_id=f"rev_{orig_txn.id}",
        entries=reversed_entries,
    )

    # Execute reversing transaction
    reversing_txn = execute_transaction(db=db, txn_in=txn_in, idempotency_key=idempotency_key)

    # Mark original transaction as reversed
    orig_txn.status = TransactionStatus.REVERSED
    orig_txn.reversed_by_id = reversing_txn.id
    db.commit()
    db.refresh(reversing_txn)
    return reversing_txn


def handle_idempotent_execution(
    db: Session,
    idempotency_key: Optional[str],
    payload_dict: dict,
    execute_fn,
) -> Tuple[TransactionResponse, bool]:
    """
    Implements Stripe-grade Idempotency handling:
    - If no key provided: executes normally.
    - If key provided:
      - Hashes request payload with SHA-256.
      - Checks database for existing record:
        - If completed with matching hash: returns cached response (is_cached=True).
        - If payload mismatch: raises IdempotencyPayloadMismatchError.
        - If processing: raises IdempotencyConflictError (409 Conflict).
      - If new: creates processing lock, executes function, caches response, and returns (is_cached=False).
    """
    if not idempotency_key:
        txn = execute_fn()
        return TransactionResponse.model_validate(txn), False

    # Normalize payload for consistent hashing
    payload_json = json.dumps(payload_dict, sort_keys=True)
    request_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

    # Query existing idempotency record
    record = db.get(IdempotencyRecord, idempotency_key)
    if record:
        if record.request_hash != request_hash:
            raise IdempotencyPayloadMismatchError(idempotency_key=idempotency_key)

        if record.status == IdempotencyStatus.COMPLETED and record.response_body:
            cached_data = json.loads(record.response_body)
            return TransactionResponse.model_validate(cached_data), True

        if record.status == IdempotencyStatus.PROCESSING and not record.is_expired():
            raise IdempotencyConflictError(idempotency_key=idempotency_key)

    # Create new idempotency processing record
    if not record:
        record = IdempotencyRecord(
            key=idempotency_key,
            request_hash=request_hash,
            status=IdempotencyStatus.PROCESSING,
        )
        db.add(record)
        db.commit()

    try:
        txn = execute_fn()
        response_obj = TransactionResponse.model_validate(txn)
        
        # Save completed response body
        record.status = IdempotencyStatus.COMPLETED
        record.response_code = 201
        record.response_body = response_obj.model_dump_json()
        db.commit()
        return response_obj, False
    except Exception:
        # On failure, roll back or delete the pending idempotency record so client can retry
        db.rollback()
        fail_rec = db.get(IdempotencyRecord, idempotency_key)
        if fail_rec and fail_rec.status == IdempotencyStatus.PROCESSING:
            db.delete(fail_rec)
            db.commit()
        raise


def get_transaction(db: Session, transaction_id: str) -> Transaction:
    txn = db.get(Transaction, transaction_id)
    if not txn:
        raise AccountNotFoundError(account_id=transaction_id)
    return txn


def list_transactions(db: Session, skip: int = 0, limit: int = 50) -> List[Transaction]:
    stmt = (
        select(Transaction)
        .order_by(Transaction.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())
