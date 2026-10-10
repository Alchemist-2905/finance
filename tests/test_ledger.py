from fastapi import status
from fastapi.testclient import TestClient


def test_deposit_and_transfer_flow(client: TestClient, sample_accounts):
    clearing = sample_accounts["clearing"]
    alice = sample_accounts["alice"]
    bob = sample_accounts["bob"]

    # 1. Fund Alice's wallet: External deposit of $500 (50,000 cents)
    # Accounting: Debit Clearing (Asset increases), Credit Alice (Liability increases)
    deposit_payload = {
        "description": "ACH Deposit from external bank",
        "reference_id": "ach_dep_001",
        "entries": [
            {"account_id": clearing.id, "amount": 50000, "direction": "DEBIT"},
            {"account_id": alice.id, "amount": 50000, "direction": "CREDIT"},
        ],
    }
    dep_res = client.post("/api/v1/transactions", json=deposit_payload)
    assert dep_res.status_code == status.HTTP_201_CREATED
    txn_data = dep_res.json()
    assert txn_data["status"] == "POSTED"
    assert len(txn_data["entries"]) == 2

    # Verify Alice balance is 50,000 cents ($500.00)
    alice_bal = client.get(f"/api/v1/accounts/{alice.id}/balance").json()
    assert alice_bal["balance_cents"] == 50000

    # 2. Transfer $150 (15,000 cents) from Alice to Bob using convenience endpoint
    transfer_payload = {
        "source_account_id": alice.id,
        "destination_account_id": bob.id,
        "amount": 15000,
        "description": "Lunch split reimbursement",
        "reference_id": "lunch_p2p_001",
    }
    tx_res = client.post("/api/v1/transactions/transfer", json=transfer_payload)
    assert tx_res.status_code == status.HTTP_201_CREATED

    # Verify Alice balance = $350.00 (35,000 cents)
    alice_bal = client.get(f"/api/v1/accounts/{alice.id}/balance").json()
    assert alice_bal["balance_cents"] == 35000

    # Verify Bob balance = $150.00 (15,000 cents)
    bob_bal = client.get(f"/api/v1/accounts/{bob.id}/balance").json()
    assert bob_bal["balance_cents"] == 15000


def test_multi_leg_transaction_with_fee_split(client: TestClient, sample_accounts):
    """
    Test Stripe-style multi-party transaction:
    Customer pays $100.00 (10,000 cents):
    - Alice (Customer): Debited 10,000 cents
    - Bob (Merchant): Credited 9,710 cents ($97.10)
    - Revenue (Platform Fee): Credited 290 cents ($2.90)
    Total Debits = 10,000; Total Credits = 9,710 + 290 = 10,000.
    """
    alice = sample_accounts["alice"]
    bob = sample_accounts["bob"]
    revenue = sample_accounts["revenue"]
    clearing = sample_accounts["clearing"]

    # Fund Alice with $200
    client.post("/api/v1/transactions", json={
        "description": "Initial Alice Deposit",
        "entries": [
            {"account_id": clearing.id, "amount": 20000, "direction": "DEBIT"},
            {"account_id": alice.id, "amount": 20000, "direction": "CREDIT"},
        ]
    })

    split_payload = {
        "description": "E-Commerce Checkout with Stripe Processing Fee",
        "reference_id": "order_inv_9981",
        "entries": [
            {"account_id": alice.id, "amount": 10000, "direction": "DEBIT"},
            {"account_id": bob.id, "amount": 9710, "direction": "CREDIT"},
            {"account_id": revenue.id, "amount": 290, "direction": "CREDIT"},
        ],
    }
    res = client.post("/api/v1/transactions", json=split_payload)
    assert res.status_code == status.HTTP_201_CREATED

    alice_bal = client.get(f"/api/v1/accounts/{alice.id}/balance").json()["balance_cents"]
    bob_bal = client.get(f"/api/v1/accounts/{bob.id}/balance").json()["balance_cents"]
    rev_bal = client.get(f"/api/v1/accounts/{revenue.id}/balance").json()["balance_cents"]

    assert alice_bal == 10000  # 20000 - 10000
    assert bob_bal == 9710
    assert rev_bal == 290


def test_unbalanced_transaction_rejected(client: TestClient, sample_accounts):
    alice = sample_accounts["alice"]
    bob = sample_accounts["bob"]

    unbalanced_payload = {
        "description": "Unbalanced transfer attempt",
        "entries": [
            {"account_id": alice.id, "amount": 5000, "direction": "DEBIT"},
            {"account_id": bob.id, "amount": 4000, "direction": "CREDIT"},  # Off by 1,000 cents
        ],
    }
    res = client.post("/api/v1/transactions", json=unbalanced_payload)
    # Caught by Pydantic validation or domain engine
    assert res.status_code in (422, status.HTTP_400_BAD_REQUEST)


def test_insufficient_funds_rejected(client: TestClient, sample_accounts):
    alice = sample_accounts["alice"]
    bob = sample_accounts["bob"]

    # Alice has $0 balance and attempts to transfer $50
    overdraw_payload = {
        "source_account_id": alice.id,
        "destination_account_id": bob.id,
        "amount": 5000,
        "description": "Unauthorized overdraft transfer",
    }
    res = client.post("/api/v1/transactions/transfer", json=overdraw_payload)
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    data = res.json()
    assert data["error"]["code"] == "insufficient_funds"


def test_currency_mismatch_rejected(client: TestClient, sample_accounts):
    alice = sample_accounts["alice"]

    # Create a EUR account
    eur_acc = client.post("/api/v1/accounts", json={
        "name": "Euro Merchant Account",
        "account_type": "LIABILITY",
        "currency": "EUR",
    }).json()

    # Attempt cross-currency transfer without FX conversion
    cross_fx_payload = {
        "description": "Cross-currency attempt",
        "entries": [
            {"account_id": alice.id, "amount": 5000, "direction": "DEBIT"},
            {"account_id": eur_acc["id"], "amount": 5000, "direction": "CREDIT"},
        ],
    }
    res = client.post("/api/v1/transactions", json=cross_fx_payload)
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    data = res.json()
    assert data["error"]["code"] == "currency_mismatch"


def test_transaction_reversal(client: TestClient, sample_accounts):
    clearing = sample_accounts["clearing"]
    alice = sample_accounts["alice"]
    bob = sample_accounts["bob"]

    # Fund Alice with $100
    client.post("/api/v1/transactions", json={
        "description": "Alice Deposit",
        "entries": [
            {"account_id": clearing.id, "amount": 10000, "direction": "DEBIT"},
            {"account_id": alice.id, "amount": 10000, "direction": "CREDIT"},
        ]
    })

    # Transfer $40 to Bob
    res = client.post("/api/v1/transactions/transfer", json={
        "source_account_id": alice.id,
        "destination_account_id": bob.id,
        "amount": 4000,
        "description": "Transfer to be reversed",
    })
    txn_id = res.json()["id"]

    assert client.get(f"/api/v1/accounts/{alice.id}/balance").json()["balance_cents"] == 6000
    assert client.get(f"/api/v1/accounts/{bob.id}/balance").json()["balance_cents"] == 4000

    # Reverse transaction
    rev_res = client.post(f"/api/v1/transactions/{txn_id}/reverse?description=Refund+requested")
    assert rev_res.status_code == status.HTTP_201_CREATED
    rev_txn = rev_res.json()
    assert rev_txn["reference_id"] == f"rev_{txn_id}"

    # Verify balances restored
    assert client.get(f"/api/v1/accounts/{alice.id}/balance").json()["balance_cents"] == 10000
    assert client.get(f"/api/v1/accounts/{bob.id}/balance").json()["balance_cents"] == 0

    # Attempting to reverse a second time must fail
    second_rev = client.post(f"/api/v1/transactions/{txn_id}/reverse")
    assert second_rev.status_code == status.HTTP_400_BAD_REQUEST
    assert second_rev.json()["error"]["code"] == "transaction_already_reversed"
