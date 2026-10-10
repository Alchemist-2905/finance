from fastapi import APIRouter
from app.api.v1.accounts import router as accounts_router
from app.api.v1.transactions import router as transactions_router
from app.api.v1.reconciliation import router as reconciliation_router

api_router = APIRouter()
api_router.include_router(accounts_router)
api_router.include_router(transactions_router)
api_router.include_router(reconciliation_router)
