"""Top-level: HTTP API end-to-end (in-process)."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app(":memory:", train_in_background=False))


def test_health_and_catalog(client):
    assert client.get("/api/health").json()["ml_ready"]
    assert len(client.get("/api/catalog/cards").json()) == 20
    assert client.get("/api/catalog/cards/nope").status_code == 404


def test_wallet_crud_and_validation(client):
    client.post("/api/demo/reset")
    assert client.post("/api/wallet", json={"card_id": "nope"}).status_code == 422
    assert client.post("/api/wallet", json={"card_id": "axis_atlas", "last4": "12"}).status_code == 422
    c = client.post("/api/wallet", json={"card_id": "axis_atlas", "points_balance": 1000}).json()
    assert c["points_value"] > 0
    assert client.patch(f"/api/wallet/{c['id']}", json={"points_balance": 2000}).json()["points_balance"] == 2000
    assert client.delete(f"/api/wallet/{c['id']}").status_code == 204
    assert client.get("/api/wallet").json() == []


def test_full_demo_flow(client):
    s = client.post("/api/demo/seed").json()
    assert s["cards"] == 4 and s["transactions"] > 100 and s["anomalies"] >= 1
    d = client.get("/api/dashboard").json()
    assert d["cards"] == 4 and d["points_value"]["best"] > 0 and len(d["trend"]) == 6
    r = client.post("/api/recommend/best-card", json={"amount": 2000, "query": "flight tickets"}).json()
    assert r["category"] == "travel_flights" and r["best"]["name"] == "Atlas"
    assert client.post("/api/recommend/discover", json={}).json()["recommendations"]
    assert client.get("/api/recommend/compare?ids=axis_atlas,hdfc_infinia").json()["cards"]
    assert client.get("/api/recommend/compare?ids=axis_atlas").status_code == 422
    assert client.get("/api/redeem").json()["totals"]["best"] > 0
    assert client.get("/api/milestones").json()
    ins = client.get("/api/insights").json()
    assert ins["forecast"]["total"]["point"] > 0 and ins["anomalies"]
    assert client.get("/api/offers?wallet_only=true").json()


def test_transactions_and_feedback(client):
    t = client.post("/api/transactions", json={"amount": 350, "description": "Sri Sai Medicals"}).json()
    assert t["category"] == "health"
    assert client.post("/api/transactions", json={"amount": -5, "description": "x"}).status_code == 422
    p = client.patch(f"/api/transactions/{t['id']}", json={"category": "others"}).json()
    assert p["category"] == "others"
    assert client.get("/api/ml/status").json()["feedback_examples"] >= 1


def test_settings(client):
    assert client.put("/api/settings", json={"value_mode": "bogus"}).status_code == 422
    assert client.put("/api/settings", json={"value_mode": "cash"}).json()["value_mode"] == "cash"
    client.put("/api/settings", json={"value_mode": "best"})


@pytest.mark.parametrize("msg,intent", [
    ("hi", "greeting"), ("which card for swiggy 800", "best_card"), ("how much are my points worth", "points_value"),
    ("I need 60000 krisflyer miles", "goal"), ("atlas vs infinia", "compare"), ("suggest a new card", "discover"),
    ("missed savings", "missed"), ("any unusual transactions", "anomaly"),
])
def test_assistant(client, msg, intent):
    r = client.post("/api/assistant/chat", json={"message": msg}).json()
    assert r["intent"] == intent and r["text"]


def test_assistant_follow_up_context(client):
    client.post("/api/assistant/chat", json={"message": "which card for amazon 1000"})
    r = client.post("/api/assistant/chat", json={"message": "what about 8000"}).json()
    assert r["intent"] == "best_card" and r["data"]["amount"] == 8000 and r["data"]["merchant"] == "amazon"
