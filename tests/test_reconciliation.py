from fastapi import status
from fastapi.testclient import TestClient
from app.models.account import Account
from tests.conftest import TestingSessionLocal


def test_account_and_ledger_audit_success(client: TestClient, sample_accounts):
    clearing = sample_accounts["clearing"]
    alice = sample_accounts["alice"]
    bob = sample_accounts["bob"]

    # Seed Alice with $300
    client.post("/api/v1/transactions", json={
        "description": "Seed for Audit",
        "entries": [
            {"account_id": clearing.id, "amount": 30000, "direction": "DEBIT"},
            {"account_id": alice.id, "amount": 30000, "direction": "CREDIT"},
        ]
    })

    # Transfer $75 to Bob
    client.post("/api/v1/transactions/transfer", json={
        "source_account_id": alice.id,
        "destination_account_id": bob.id,
        "amount": 7500,
        "description": "Audit flow transfer",
    })

    # Reconcile Alice
    res_alice = client.get(f"/api/v1/reconciliation/accounts/{alice.id}")
    assert res_alice.status_code == status.HTTP_200_OK
    audit_alice = res_alice.json()
    assert audit_alice["is_reconciled"] is True
    assert audit_alice["discrepancy"] == 0
    assert audit_alice["cached_balance"] == 22500
    assert audit_alice["computed_balance"] == 22500

    # Reconcile Bob
    res_bob = client.get(f"/api/v1/reconciliation/accounts/{bob.id}")
    assert res_bob.status_code == status.HTTP_200_OK
    audit_bob = res_bob.json()
    assert audit_bob["is_reconciled"] is True
    assert audit_bob["cached_balance"] == 7500
    assert audit_bob["computed_balance"] == 7500

    # Global ledger audit
    global_res = client.get("/api/v1/reconciliation/audit")
    assert global_res.status_code == status.HTTP_200_OK
    global_audit = global_res.json()
    assert global_audit["is_balanced"] is True
    assert global_audit["total_debits"] == global_audit["total_credits"]
    assert global_audit["discrepancy"] == 0


def test_reconciliation_detects_deliberate_tampering(client: TestClient, sample_accounts):
    alice = sample_accounts["alice"]

    # Directly tamper with Alice's materialized cache in the DB
    with TestingSessionLocal() as session:
        db_account = session.get(Account, alice.id)
        db_account.cached_balance = 999999
        session.commit()

    # Reconcile Alice
    res = client.get(f"/api/v1/reconciliation/accounts/{alice.id}")
    assert res.status_code == status.HTTP_200_OK
    audit = res.json()
    assert audit["is_reconciled"] is False
    assert audit["cached_balance"] == 999999
    assert audit["computed_balance"] == 0
    assert audit["discrepancy"] == 999999
