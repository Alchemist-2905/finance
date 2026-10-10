from typing import Any, Dict, Optional
from fastapi import Request, status
from fastapi.responses import JSONResponse

HTTP_422 = 422


class LedgerException(Exception):
    """Base exception for all ledger domain errors."""
    def __init__(self, message: str, code: str = "ledger_error", status_code: int = status.HTTP_400_BAD_REQUEST, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class InsufficientFundsError(LedgerException):
    def __init__(self, account_id: str, current_balance: int, requested_amount: int):
        super().__init__(
            message=f"Account '{account_id}' has insufficient funds. Current balance: {current_balance} cents, requested: {requested_amount} cents.",
            code="insufficient_funds",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={
                "account_id": account_id,
                "current_balance": current_balance,
                "requested_amount": requested_amount,
            }
        )


class UnbalancedTransactionError(LedgerException):
    def __init__(self, total_debits: int, total_credits: int):
        super().__init__(
            message=f"Transaction violates double-entry principle. Debits ({total_debits}) must equal Credits ({total_credits}). Difference: {abs(total_debits - total_credits)} cents.",
            code="unbalanced_transaction",
            status_code=HTTP_422,
            details={
                "total_debits": total_debits,
                "total_credits": total_credits,
                "difference": abs(total_debits - total_credits),
            }
        )


class EmptyTransactionError(LedgerException):
    def __init__(self):
        super().__init__(
            message="A transaction must have at least two entry legs (one debit and one credit).",
            code="empty_transaction",
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class AccountNotFoundError(LedgerException):
    def __init__(self, account_id: str):
        super().__init__(
            message=f"Account with ID '{account_id}' was not found.",
            code="account_not_found",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"account_id": account_id}
        )


class CurrencyMismatchError(LedgerException):
    def __init__(self, expected_currency: str, actual_currency: str, account_id: str):
        super().__init__(
            message=f"Currency mismatch for account '{account_id}'. Expected {expected_currency}, got {actual_currency}.",
            code="currency_mismatch",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={
                "account_id": account_id,
                "expected_currency": expected_currency,
                "actual_currency": actual_currency,
            }
        )


class InvalidAmountError(LedgerException):
    def __init__(self, amount: int):
        super().__init__(
            message=f"Amount must be a positive integer in cents. Received: {amount}.",
            code="invalid_amount",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"amount": amount}
        )


class IdempotencyConflictError(LedgerException):
    def __init__(self, idempotency_key: str):
        super().__init__(
            message=f"A request with idempotency key '{idempotency_key}' is currently in progress. Please retry after a brief delay.",
            code="idempotency_in_flight",
            status_code=status.HTTP_409_CONFLICT,
            details={"idempotency_key": idempotency_key}
        )


class IdempotencyPayloadMismatchError(LedgerException):
    def __init__(self, idempotency_key: str):
        super().__init__(
            message=f"Idempotency key '{idempotency_key}' has already been used with a different request payload.",
            code="idempotency_key_mismatch",
            status_code=HTTP_422,
            details={"idempotency_key": idempotency_key}
        )


class TransactionAlreadyReversedError(LedgerException):
    def __init__(self, transaction_id: str):
        super().__init__(
            message=f"Transaction '{transaction_id}' has already been reversed.",
            code="transaction_already_reversed",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"transaction_id": transaction_id}
        )


async def ledger_exception_handler(request: Request, exc: LedgerException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "type": "invalid_request_error",
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )
