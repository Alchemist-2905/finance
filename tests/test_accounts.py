from fastapi import status
from fastapi.testclient import TestClient


def test_create_account_success(client: TestClient):
    payload = {
        "name": "Customer Charlie Wallet",
        "account_type": "LIABILITY",
        "currency": "usd",  # should be auto-uppercased
        "allow_negative_balance": False,
    }
    response = client.post("/api/v1/accounts", json=payload)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["name"] == "Customer Charlie Wallet"
    assert data["account_type"] == "LIABILITY"
    assert data["currency"] == "USD"
    assert data["cached_balance"] == 0
    assert data["id"].startswith("acc_")


def test_get_account_balance(client: TestClient, sample_accounts):
    alice = sample_accounts["alice"]
    response = client.get(f"/api/v1/accounts/{alice.id}/balance")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["account_id"] == alice.id
    assert data["balance_cents"] == 0
    assert "0.00 USD" in data["formatted_balance"]


def test_get_nonexistent_account_returns_404(client: TestClient):
    response = client.get("/api/v1/accounts/acc_nonexistent99999999")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    data = response.json()
    assert data["error"]["code"] == "account_not_found"


def test_list_accounts(client: TestClient, sample_accounts):
    response = client.get("/api/v1/accounts")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) >= 4
    account_ids = [acc["id"] for acc in data]
    assert sample_accounts["alice"].id in account_ids
