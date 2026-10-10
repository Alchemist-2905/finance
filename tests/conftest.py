import os
from typing import Generator
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from app.core.database import Base, get_db
from app.main import app
from app.models.account import Account, AccountType

TEST_DB_FILE = "./test_ledger.db"
TEST_DATABASE_URL = f"sqlite:///{TEST_DB_FILE}"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)


@event.listens_for(test_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=15000")
    cursor.close()


TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    bind=test_engine,
)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Ensure clean test database at the beginning and end of test session."""
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except OSError:
            pass

    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except OSError:
            pass


@pytest.fixture(autouse=True)
def clean_tables_per_test():
    """Ensure database tables are cleaned up after every single test."""
    yield
    with test_engine.connect() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
        conn.commit()


@pytest.fixture
def db() -> Generator[Session, None, None]:
    """Yields a database session with transaction rollback per test."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """TestClient configured with dependency override for testing database session."""
    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def sample_accounts():
    """
    Creates standard test accounts:
    - clearing_account: ASSET (Bank settlement holding, allows negative for deposits)
    - alice_wallet: LIABILITY (Customer deposit wallet)
    - bob_wallet: LIABILITY (Customer deposit wallet)
    - platform_revenue: REVENUE (Stripe processing fee income)
    """
    session = TestingSessionLocal()
    clearing = Account(
        name="Settlement Clearing Account",
        account_type=AccountType.ASSET,
        currency="USD",
        cached_balance=0,  # Starts at 0 to maintain perfect ledger parity
        allow_negative_balance=True,
    )
    alice = Account(
        name="Alice Wallet",
        account_type=AccountType.LIABILITY,
        currency="USD",
        cached_balance=0,
        allow_negative_balance=False,
    )
    bob = Account(
        name="Bob Wallet",
        account_type=AccountType.LIABILITY,
        currency="USD",
        cached_balance=0,
        allow_negative_balance=False,
    )
    revenue = Account(
        name="Stripe Processing Fee Revenue",
        account_type=AccountType.REVENUE,
        currency="USD",
        cached_balance=0,
        allow_negative_balance=False,
    )

    session.add_all([clearing, alice, bob, revenue])
    session.commit()
    accounts = {
        "clearing": clearing,
        "alice": alice,
        "bob": bob,
        "revenue": revenue,
    }
    session.close()
    return accounts
