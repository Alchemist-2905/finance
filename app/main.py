from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import Base, engine
from app.core.exceptions import LedgerException, ledger_exception_handler
from app.api.v1 import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables on application startup
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="""
# Production-Grade Double-Entry Financial Ledger & Wallet Engine

Designed to meet Stripe's standards for precision, auditability, and concurrency safety.

### Key Architectural Guarantees:
* **Strict Double-Entry Bookkeeping**: Every transaction enforces $\\sum \\text{Debits} = \\sum \\text{Credits}$.
* **Zero Floating-Point Drift**: All currency values are stored as 64-bit integers in cents (minor currency units).
* **Deterministic Deadlock Prevention**: Accounts are sorted by ID prior to row locking to eliminate deadlocks.
* **Stripe-Grade Idempotency**: Safe client retries using `Idempotency-Key` headers.
* **Continuous Audit Reconciliation**: Verifies cached balances against historical journal entries.
    """,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register custom exception handlers
app.add_exception_handler(LedgerException, ledger_exception_handler)

# Include v1 API endpoints
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["System"])
def health_check():
    """Service health and readiness check."""
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
    }


@app.get("/", tags=["System"])
def root():
    """Root metadata and documentation link."""
    return {
        "message": "Double-Entry Financial Ledger & Wallet Engine API",
        "documentation": "/docs",
        "health": "/health",
        "api_v1": settings.API_V1_STR,
    }
