"""Tests for the queue-marketplace rework (ТЗ доработка):
- commission quote before purchase (разделы 2, 3, 9);
- user-created queues (раздел 5) and creator resource permission;
- event reports / жалобы на фейковые очереди (раздел 6).
"""
import pytest

from tests.conftest import auth, make_event, make_resource, register_and_get_token


@pytest.fixture()
def seller_buyer_queue(client):
    """Seller joins a queue and lists the place for 1000; returns ids."""
    org = register_and_get_token(client, "org@deals.example.com")
    event = make_event(client, org, title="Фестиваль «Тест»")
    resource = make_resource(client, org, event["id"], "EVENT_QUEUE", 100)
    seller = register_and_get_token(client, "seller@deals.example.com")
    r = client.post(f"/api/queues/resources/{resource['id']}/join", json={},
                    headers=auth(seller))
    assert r.status_code == 201, r.text
    right = r.json()["access_right"]
    r = client.post("/api/transfers/listings",
                    json={"access_right_id": right["id"], "price": 1000},
                    headers=auth(seller))
    assert r.status_code == 201, r.text
    return {"event": event, "resource": resource, "seller": seller,
            "right": right, "listing": r.json()}


def test_quote_shows_price_and_commission_before_purchase(client, seller_buyer_queue):
    """Покупатель видит цену и комиссию ДО оплаты (ТЗ 3, 9)."""
    quote = client.get(f"/api/transfers/listings/{seller_buyer_queue['listing']['id']}/quote",
                       headers=auth(register_and_get_token(client, "buyer@deals.example.com")))
    assert quote.status_code == 200, quote.text
    body = quote.json()
    assert body["price"] == 1000
    assert body["buyer_total"] == 1000          # fee withheld from the seller
    assert body["fee_amount"] == 50             # default 5%
    assert body["seller_payout"] == 950
    assert body["deal_window_seconds"] > 0


def test_marketplace_listings_include_quote(client, seller_buyer_queue):
    items = client.get("/api/marketplace/listings").json()
    mine = [i for i in items if i["listing"]["id"] == seller_buyer_queue["listing"]["id"]]
    assert mine, "listing not surfaced on marketplace"
    assert mine[0]["quote"]["price"] == 1000
    assert mine[0]["quote"]["fee_amount"] == 50


def test_user_can_create_queue_around_any_object(client):
    """Раздел 5: пользователь сам создаёт очередь (АЗС) и добавляет к ней ресурс."""
    user = register_and_get_token(client, "creator@deals.example.com")
    r = client.post("/api/events", json={
        "title": "АЗС Газпромнефть — Ленинградское шоссе, 25",
        "starts_at": "2026-09-20T08:00:00Z",
        "city": "Москва", "address": "Ленинградское шоссе, 25",
        "capacity": 40, "category": "GAS_STATION",
    }, headers=auth(user))
    assert r.status_code == 201, r.text
    event = r.json()
    assert event["source"] == "USER_REQUEST"
    assert event["status"] == "PENDING_VERIFICATION"

    # author may attach a queue resource to their own event
    r = client.post("/api/resources", json={
        "event_id": event["id"], "type": "PHYSICAL_QUEUE",
        "name": "Очередь на колонки", "capacity": 40, "queue_policy": "FIFO",
    }, headers=auth(user))
    assert r.status_code == 201, r.text

    # duplicate protection (раздел 6)
    r = client.post("/api/events", json={
        "title": "АЗС Газпромнефть — Ленинградское шоссе, 25",
        "starts_at": "2026-09-20T08:00:00Z",
        "city": "Москва", "capacity": 40, "category": "GAS_STATION",
    }, headers=auth(user))
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "DUPLICATE_EVENT"

    # another user cannot add resources to someone else's event
    other = register_and_get_token(client, "other@deals.example.com")
    r = client.post("/api/resources", json={
        "event_id": event["id"], "type": "PHYSICAL_QUEUE",
        "name": "Чужая очередь", "capacity": 10,
    }, headers=auth(other))
    assert r.status_code == 403


def test_report_fake_queue(client):
    """Раздел 6: жалоба на некорректную очередь."""
    creator = register_and_get_token(client, "q-author@deals.example.com")
    event = make_event(client, creator, title="Фейк-очередь у дома")
    reporter = register_and_get_token(client, "reporter@deals.example.com")

    r = client.post(f"/api/events/{event['id']}/report",
                    json={"reason": "FAKE_OBJECT", "description": "АЗС здесь нет"},
                    headers=auth(reporter))
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "OPEN"

    # duplicate report by the same user is rejected
    r = client.post(f"/api/events/{event['id']}/report",
                    json={"reason": "FAKE_OBJECT"}, headers=auth(reporter))
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ALREADY_REPORTED"

    # cannot report your own queue
    r = client.post(f"/api/events/{event['id']}/report",
                    json={"reason": "SPAM"}, headers=auth(creator))
    assert r.status_code == 400

    # admin moderation queue lists the report; regular users cannot
    admin_r = client.post("/api/auth/login", json={
        "email": "admin@access.marketplace", "password": "ChangeMe-Admin-2026!"})
    admin_token = admin_r.json()["access_token"]
    r = client.get("/api/events/reports/open", headers=auth(admin_token))
    assert r.status_code == 200
    assert any(rep["event_id"] == event["id"] for rep in r.json())
    r = client.get("/api/events/reports/open", headers=auth(reporter))
    assert r.status_code == 403


def test_full_seller_to_buyer_deal_with_commission(client, seller_buyer_queue):
    """Полный путь продавец → покупатель (ТЗ 2): buy → pay → место передано."""
    buyer = register_and_get_token(client, "deal-buyer@deals.example.com")
    listing_id = seller_buyer_queue["listing"]["id"]
    right_id = seller_buyer_queue["right"]["id"]

    transfer = client.post("/api/transfers/buy",
                          json={"listing_id": listing_id,
                                "idempotency_key": "deal-key-1"},
                          headers=auth(buyer))
    assert transfer.status_code == 201, transfer.text
    assert transfer.json()["status"] == "AWAITING_PAYMENT"

    payment = client.post(f"/api/transfers/{transfer.json()['id']}/pay",
                          json={"idempotency_key": "pay-key-1"},
                          headers=auth(buyer))
    assert payment.status_code == 201, payment.text
    body = payment.json()
    assert body["amount"] == 1000
    assert body["fee_amount"] == 50
    assert body["status"] == "CAPTURED"

    # место закрепилось за покупателем
    rights = client.get("/api/access/my", headers=auth(buyer)).json()
    assert any(r["id"] == right_id and r["status"] == "OWNED" for r in rights)
    # продавец больше не владеет местом
    seller_rights = client.get("/api/access/my",
                               headers=auth(seller_buyer_queue["seller"])).json()
    assert not any(r["id"] == right_id and r["status"] == "OWNED" for r in seller_rights)

    # история сделки доступна обеим сторонам (ТЗ 12)
    my = client.get("/api/transfers/my", headers=auth(buyer)).json()
    assert any(t["id"] == transfer.json()["id"] and t["status"] == "COMPLETED" for t in my)
