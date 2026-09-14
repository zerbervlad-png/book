"""Wallet top-up and deal chat (buyer ↔ seller communication)."""
import pytest

from tests.conftest import auth, make_event, make_resource, register, register_and_get_token


@pytest.fixture()
def deal(client):
    """A paid resale transfer: seller lists a position, buyer buys + pays."""
    seller = register_and_get_token(client, "chat-seller@x.io")
    buyer = register_and_get_token(client, "chat-buyer@x.io")
    event = make_event(client, seller, capacity=100)
    resource = make_resource(client, seller, event["id"], rtype="EVENT_QUEUE", capacity=100)
    client.post(f"/api/queues/resources/{resource['id']}/join", json={}, headers=auth(seller))
    right = client.get("/api/access/my", headers=auth(seller)).json()[0]
    listing = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": 500}, headers=auth(seller)).json()
    transfer = client.post("/api/transfers/buy", json={
        "listing_id": listing["id"], "idempotency_key": "chat-buy-1"},
        headers=auth(buyer)).json()
    pay = client.post(f"/api/transfers/{transfer['id']}/pay", json={
        "idempotency_key": "chat-pay-1"}, headers=auth(buyer))
    assert pay.status_code == 201, pay.text
    return {"seller": seller, "buyer": buyer, "transfer": transfer, "resource": resource}


# --- wallet ---
def test_topup_increases_balance(client):
    user = register_and_get_token(client, "wallet@x.io")
    r = client.post("/api/payments/topup", json={"amount": 1000}, headers=auth(user))
    assert r.status_code == 200
    assert r.json()["available"] == 1000
    again = client.post("/api/payments/topup", json={"amount": 500}, headers=auth(user))
    assert again.json()["available"] == 1500


def test_topup_rejects_invalid_amount(client):
    user = register_and_get_token(client, "wallet2@x.io")
    assert client.post("/api/payments/topup", json={"amount": 0},
                       headers=auth(user)).status_code == 400
    assert client.post("/api/payments/topup", json={"amount": -5},
                       headers=auth(user)).status_code == 400


def test_buyer_debited_seller_credited_after_purchase(client, deal):
    buyer_balance = client.get("/api/payments/balance", headers=auth(deal["buyer"])).json()
    seller_balance = client.get("/api/payments/balance", headers=auth(deal["seller"])).json()
    # buyer paid 500 from the demo auto-top-up wallet; the 5% platform fee
    # (25 ₽) is withheld from the seller's payout
    assert buyer_balance["available"] >= 0
    assert seller_balance["available"] == 475


# --- deal chat ---
def test_chat_between_buyer_and_seller(client, deal):
    buyer, seller, transfer = deal["buyer"], deal["seller"], deal["transfer"]
    r = client.post(f"/api/transfers/{transfer['id']}/messages", json={
        "body": "Привет! Купил твоё место. Куда подойти?"}, headers=auth(buyer))
    assert r.status_code == 201, r.text
    r = client.post(f"/api/transfers/{transfer['id']}/messages", json={
        "body": "Привет! Вход с торца здания, я в красной куртке, позиция 12"},
        headers=auth(seller))
    assert r.status_code == 201

    msgs = client.get(f"/api/transfers/{transfer['id']}/messages", headers=auth(buyer))
    assert msgs.status_code == 200
    bodies = [m["body"] for m in msgs.json()]
    assert any("Куда подойти" in b for b in bodies)
    assert any("красной куртке" in b for b in bodies)
    # chronological order
    ids = [m["id"] for m in msgs.json()]
    assert ids == sorted(ids)


def test_chat_incremental_fetch(client, deal):
    buyer, transfer = deal["buyer"], deal["transfer"]
    first = client.post(f"/api/transfers/{transfer['id']}/messages", json={
        "body": "msg 1"}, headers=auth(buyer)).json()
    client.post(f"/api/transfers/{transfer['id']}/messages", json={
        "body": "msg 2"}, headers=auth(buyer))
    only_new = client.get(
        f"/api/transfers/{transfer['id']}/messages?after_id={first['id']}",
        headers=auth(buyer))
    assert [m["body"] for m in only_new.json()] == ["msg 2"]


def test_chat_stranger_forbidden(client, deal):
    stranger = register_and_get_token(client, "chat-stranger@x.io")
    r = client.post(f"/api/transfers/{deal['transfer']['id']}/messages", json={
        "body": "hi"}, headers=auth(stranger))
    assert r.status_code == 403
    r = client.get(f"/api/transfers/{deal['transfer']['id']}/messages", headers=auth(stranger))
    assert r.status_code == 403


def test_chat_message_notifies_counterpart(client, deal):
    buyer, seller, transfer = deal["buyer"], deal["seller"], deal["transfer"]
    client.post(f"/api/transfers/{transfer['id']}/messages", json={
        "body": "куда подходить?"}, headers=auth(buyer))
    notes = client.get("/api/notifications", headers=auth(seller)).json()
    assert any(n["kind"] == "DEAL_MESSAGE" for n in notes)


def test_chat_empty_and_blank_rejected(client, deal):
    buyer, transfer = deal["buyer"], deal["transfer"]
    assert client.post(f"/api/transfers/{transfer['id']}/messages", json={
        "body": "   "}, headers=auth(buyer)).status_code == 422
    r = client.post(f"/api/transfers/{transfer['id']}/messages", json={
        "body": ""}, headers=auth(buyer))
    assert r.status_code == 422
