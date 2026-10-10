from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_idempotency_key
from app.schemas.transaction import (
    TransactionCreate,
    TransferRequest,
    TransactionResponse,
)
from app.services import ledger_service

router = APIRouter(prefix="/transactions", tags=["Transactions & Ledger"])


@router.post("", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
def create_transaction(
    txn_in: TransactionCreate,
    response: Response,
    idempotency_key: Optional[str] = Depends(get_idempotency_key),
    db: Session = Depends(get_db),
):
    """
    Execute an arbitrary multi-legged financial transaction.
    Enforces strict double-entry balance: sum(debits) == sum(credits).
    Supports Stripe-style idempotency via the `Idempotency-Key` header.
    """
    def _execute():
        return ledger_service.execute_transaction(db, txn_in, idempotency_key=idempotency_key)

    result, is_cached = ledger_service.handle_idempotent_execution(
        db=db,
        idempotency_key=idempotency_key,
        payload_dict=txn_in.model_dump(mode="json"),
        execute_fn=_execute,
    )

    if is_cached:
        response.headers["Idempotent-Replay"] = "true"
        response.status_code = status.HTTP_200_OK

    return result


@router.post("/transfer", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
def transfer_funds(
    transfer_in: TransferRequest,
    response: Response,
    idempotency_key: Optional[str] = Depends(get_idempotency_key),
    db: Session = Depends(get_db),
):
    """
    Execute a point-to-point wallet transfer.
    Automatically establishes double-entry debit/credit legs and applies row locks in sorted order
    to prevent deadlocks and race conditions.
    """
    def _execute():
        return ledger_service.transfer_funds(db, transfer_in, idempotency_key=idempotency_key)

    result, is_cached = ledger_service.handle_idempotent_execution(
        db=db,
        idempotency_key=idempotency_key,
        payload_dict=transfer_in.model_dump(mode="json"),
        execute_fn=_execute,
    )

    if is_cached:
        response.headers["Idempotent-Replay"] = "true"
        response.status_code = status.HTTP_200_OK

    return result


@router.post("/{transaction_id}/reverse", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
def reverse_transaction(
    transaction_id: str,
    response: Response,
    description: Optional[str] = Query(None, description="Optional reason/memo for reversal"),
    idempotency_key: Optional[str] = Depends(get_idempotency_key),
    db: Session = Depends(get_db),
):
    """
    Reverse a posted transaction by creating a compensating transaction with inverted legs.
    Original entries remain immutable in the historical ledger.
    """
    payload_dict = {"transaction_id": transaction_id, "description": description}

    def _execute():
        return ledger_service.reverse_transaction(
            db=db,
            transaction_id=transaction_id,
            description=description,
            idempotency_key=idempotency_key,
        )

    result, is_cached = ledger_service.handle_idempotent_execution(
        db=db,
        idempotency_key=idempotency_key,
        payload_dict=payload_dict,
        execute_fn=_execute,
    )

    if is_cached:
        response.headers["Idempotent-Replay"] = "true"
        response.status_code = status.HTTP_200_OK

    return result


@router.get("", response_model=List[TransactionResponse])
def list_transactions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List recent financial transactions with their corresponding journal entry legs."""
    return ledger_service.list_transactions(db, skip=skip, limit=limit)


@router.get("/{transaction_id}", response_model=TransactionResponse)
def get_transaction(
    transaction_id: str,
    db: Session = Depends(get_db),
):
    """Retrieve details and journal entries for a specific transaction."""
    return ledger_service.get_transaction(db, transaction_id)
