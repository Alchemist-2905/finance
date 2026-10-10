import concurrent.futures
from fastapi import status
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import get_db
from tests.conftest import TestingSessionLocal


def test_concurrent_transfers_prevent_double_spending():
    """
    Concurrency Stress Test:
    - Alice starts with $100.00 (10,000 cents).
    - 10 concurrent threads each attempt to transfer $15.00 (1,500 cents) to Bob.
    - Total requested: $150.00 (15,000 cents).
    - Available funds: $100.00 (10,000 cents).
    
    Invariant verification:
    - Exactly 6 transfers can succeed (6 * 1500 = 9000 cents).
    - Exactly 4 transfers must fail with HTTP 400 (insufficient_funds).
    - Alice ending balance must be exactly $10.00 (1,000 cents).
    - Bob ending balance must be exactly $90.00 (9,000 cents).
    - Under NO circumstances can Alice's balance become negative or double-spent.
    """
    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    # 1. Create accounts
    alice = client.post("/api/v1/accounts", json={
        "name": "Concurrent Alice",
        "account_type": "LIABILITY",
        "currency": "USD",
        "allow_negative_balance": False,
    }).json()

    bob = client.post("/api/v1/accounts", json={
        "name": "Concurrent Bob",
        "account_type": "LIABILITY",
        "currency": "USD",
        "allow_negative_balance": False,
    }).json()

    clearing = client.post("/api/v1/accounts", json={
        "name": "Concurrent Clearing",
        "account_type": "ASSET",
        "currency": "USD",
        "allow_negative_balance": True,
    }).json()

    # Fund Alice with 10,000 cents ($100.00)
    client.post("/api/v1/transactions", json={
        "description": "Seed Alice",
        "entries": [
            {"account_id": clearing["id"], "amount": 10000, "direction": "DEBIT"},
            {"account_id": alice["id"], "amount": 10000, "direction": "CREDIT"},
        ]
    })

    # 2. Launch 10 concurrent transfer requests
    num_threads = 10
    transfer_amount = 1500  # $15.00

    def attempt_transfer(thread_idx: int):
        # Dedicated client instance per thread for thread safety
        with TestClient(app) as thread_client:
            payload = {
                "source_account_id": alice["id"],
                "destination_account_id": bob["id"],
                "amount": transfer_amount,
                "description": f"Concurrent transfer attempt {thread_idx}",
            }
            res = thread_client.post("/api/v1/transactions/transfer", json=payload)
            return res.status_code, res.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        results = list(executor.map(attempt_transfer, range(num_threads)))

    successes = [r for r in results if r[0] == status.HTTP_201_CREATED]
    failures = [r for r in results if r[0] == status.HTTP_400_BAD_REQUEST]

    assert len(successes) == 6, f"Expected 6 successes, got {len(successes)}"
    assert len(failures) == 4, f"Expected 4 failures, got {len(failures)}"

    for status_code, data in failures:
        assert data["error"]["code"] == "insufficient_funds"

    # Verify final balances
    alice_bal = client.get(f"/api/v1/accounts/{alice['id']}/balance").json()["balance_cents"]
    bob_bal = client.get(f"/api/v1/accounts/{bob['id']}/balance").json()["balance_cents"]

    assert alice_bal == 1000, f"Expected Alice balance to be 1000, got {alice_bal}"
    assert bob_bal == 9000, f"Expected Bob balance to be 9000, got {bob_bal}"
    assert alice_bal + bob_bal == 10000, "Conservation of money violated!"

    app.dependency_overrides.clear()


def test_bidirectional_transfers_no_deadlock():
    """
    Deadlock Prevention Test:
    - Simultaneously executes:
      A -> B transfers
      B -> A transfers
    - Proves deterministic lock ordering prevents database deadlocks.
    """
    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    acc_x = client.post("/api/v1/accounts", json={
        "name": "Party X",
        "account_type": "LIABILITY",
        "currency": "USD",
    }).json()

    acc_y = client.post("/api/v1/accounts", json={
        "name": "Party Y",
        "account_type": "LIABILITY",
        "currency": "USD",
    }).json()

    clearing = client.post("/api/v1/accounts", json={
        "name": "Clearing",
        "account_type": "ASSET",
        "currency": "USD",
        "allow_negative_balance": True,
    }).json()

    # Fund both with $100 (10,000 cents)
    client.post("/api/v1/transactions", json={
        "description": "Fund X and Y",
        "entries": [
            {"account_id": clearing["id"], "amount": 20000, "direction": "DEBIT"},
            {"account_id": acc_x["id"], "amount": 10000, "direction": "CREDIT"},
            {"account_id": acc_y["id"], "amount": 10000, "direction": "CREDIT"},
        ]
    })

    def transfer(direction: str, idx: int):
        src = acc_x["id"] if direction == "X_TO_Y" else acc_y["id"]
        dst = acc_y["id"] if direction == "X_TO_Y" else acc_x["id"]
        with TestClient(app) as thread_client:
            payload = {
                "source_account_id": src,
                "destination_account_id": dst,
                "amount": 500,  # $5.00
                "description": f"Bidirectional transfer {direction} #{idx}",
            }
            res = thread_client.post("/api/v1/transactions/transfer", json=payload)
            return res.status_code

    tasks = []
    # 6 transfers X -> Y, 6 transfers Y -> X in parallel
    for i in range(6):
        tasks.append(("X_TO_Y", i))
        tasks.append(("Y_TO_X", i))

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        status_codes = list(executor.map(lambda t: transfer(*t), tasks))

    # All transfers should succeed without deadlock timeout
    assert all(code == status.HTTP_201_CREATED for code in status_codes)

    # Net balance after 6 transfers each way is unchanged: $100.00 each
    x_bal = client.get(f"/api/v1/accounts/{acc_x['id']}/balance").json()["balance_cents"]
    y_bal = client.get(f"/api/v1/accounts/{acc_y['id']}/balance").json()["balance_cents"]

    assert x_bal == 10000
    assert y_bal == 10000

    app.dependency_overrides.clear()
