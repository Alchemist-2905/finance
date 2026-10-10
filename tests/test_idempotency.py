from fastapi import status
from fastapi.testclient import TestClient


def test_idempotent_transfer_replay(client: TestClient, sample_accounts):
    clearing = sample_accounts["clearing"]
    alice = sample_accounts["alice"]
    bob = sample_accounts["bob"]

    # Fund Alice with $200 (20,000 cents)
    client.post("/api/v1/transactions", json={
        "description": "Seed Alice for Idempotency Test",
        "entries": [
            {"account_id": clearing.id, "amount": 20000, "direction": "DEBIT"},
            {"account_id": alice.id, "amount": 20000, "direction": "CREDIT"},
        ]
    })

    transfer_payload = {
        "source_account_id": alice.id,
        "destination_account_id": bob.id,
        "amount": 2500,  # $25.00
        "description": "Subscription charge with idempotency",
    }
    headers = {"Idempotency-Key": "idemp_sub_pay_9999"}

    # 1. Initial execution
    res1 = client.post("/api/v1/transactions/transfer", json=transfer_payload, headers=headers)
    assert res1.status_code == status.HTTP_201_CREATED
    txn1 = res1.json()
    assert txn1["idempotency_key"] == "idemp_sub_pay_9999"

    # Alice balance drops to 17500
    assert client.get(f"/api/v1/accounts/{alice.id}/balance").json()["balance_cents"] == 17500

    # 2. Network retry with identical idempotency key and payload
    res2 = client.post("/api/v1/transactions/transfer", json=transfer_payload, headers=headers)
    assert res2.status_code == status.HTTP_200_OK
    assert res2.headers.get("Idempotent-Replay") == "true"
    txn2 = res2.json()

    # Must return exact same transaction representation
    assert txn2["id"] == txn1["id"]

    # Invariant: Alice balance must NOT be debited a second time
    assert client.get(f"/api/v1/accounts/{alice.id}/balance").json()["balance_cents"] == 17500
    assert client.get(f"/api/v1/accounts/{bob.id}/balance").json()["balance_cents"] == 2500


def test_idempotency_payload_mismatch_rejected(client: TestClient, sample_accounts):
    clearing = sample_accounts["clearing"]
    alice = sample_accounts["alice"]
    bob = sample_accounts["bob"]

    # Fund Alice so initial request succeeds
    client.post("/api/v1/transactions", json={
        "description": "Seed Alice for Mismatch Test",
        "entries": [
            {"account_id": clearing.id, "amount": 10000, "direction": "DEBIT"},
            {"account_id": alice.id, "amount": 10000, "direction": "CREDIT"},
        ]
    })

    headers = {"Idempotency-Key": "idemp_reused_key_111"}
    initial_payload = {
        "source_account_id": alice.id,
        "destination_account_id": bob.id,
        "amount": 1000,
        "description": "Initial order payload",
    }
    res_init = client.post("/api/v1/transactions/transfer", json=initial_payload, headers=headers)
    assert res_init.status_code == status.HTTP_201_CREATED

    # Reusing same key with altered payload
    altered_payload = {
        "source_account_id": alice.id,
        "destination_account_id": bob.id,
        "amount": 5000,  # Modified amount
        "description": "Altered order payload",
    }
    res_mismatch = client.post("/api/v1/transactions/transfer", json=altered_payload, headers=headers)
    assert res_mismatch.status_code == 422
    data = res_mismatch.json()
    assert data["error"]["code"] == "idempotency_key_mismatch"
