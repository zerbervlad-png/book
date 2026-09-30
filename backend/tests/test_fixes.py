"""Regression tests for the audit round-2 fixes:
- refund after completed transfer is forbidden (money + goods double spend)
- dispute: only participants can open; refund resolution revokes the right
- queue capacity is enforced on join
- cancelled transfer deactivates its listing (no zombie listings)
- notification of another user returns 403
- one-time-code check-in by a stranger is forbidden
"""
from tests.conftest import (
    auth, future_starts_at, make_event, make_resource, register_and_get_token
)


def _setup(client, rtype="EVENT_QUEUE", **res_kwargs):
    org_token = register_and_get_token(client, "audit-org@x.io")
    client.post("/api/organizers", json={"name": "Audit Organizer"}, headers=auth(org_token))
    event = make_event(client, org_token, title="Audit Event")
    resource = make_resource(client, org_token, event["id"], rtype=rtype, **res_kwargs)
    return org_token, event, resource


def _join(client, token, resource_id):
    r = client.post(f"/api/queues/resources/{resource_id}/join", json={},
                    headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()["access_right"]


def _paid_completed_transfer(client, resource, price=500):
    seller = register_and_get_token(client, "fix-seller@x.io")
    buyer = register_and_get_token(client, "fix-buyer@x.io")
    right = _join(client, seller, resource["id"])
    listing = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": price}, headers=auth(seller)).json()
    transfer = client.post("/api/transfers/buy", json={
        "listing_id": listing["id"]}, headers=auth(buyer)).json()
    pay = client.post(f"/api/transfers/{transfer['id']}/pay", json={
        "idempotency_key": f"fix-key-{listing['id']}"}, headers=auth(buyer))
    assert pay.status_code == 201, pay.text
    return seller, buyer, right, listing, transfer


# --- FIX: refund after a completed transfer is forbidden ---
def test_refund_forbidden_after_completed_transfer(client):
    org_token, event, resource = _setup(client)
    seller, buyer, right, listing, transfer = _paid_completed_transfer(client, resource)
    tr = [t for t in client.get("/api/transfers/my", headers=auth(buyer)).json()
          if t["id"] == transfer["id"]][0]
    assert tr["status"] == "COMPLETED"

    payment = [p for p in client.get("/api/payments/my", headers=auth(buyer)).json()
               if p["transfer_id"] == transfer["id"]][0]
    r = client.post(f"/api/payments/{payment['id']}/refund", headers=auth(buyer))
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "REFUND_FORBIDDEN"


# --- FIX: only a participant can open a dispute ---
def test_dispute_requires_participant(client):
    org_token, event, resource = _setup(client)
    seller, buyer, right, listing, transfer = _paid_completed_transfer(client, resource)
    stranger = register_and_get_token(client, "fix-stranger@x.io")
    r = client.post("/api/disputes", json={
        "transfer_id": transfer["id"], "reason": "fraud",
        "description": "not mine"}, headers=auth(stranger))
    assert r.status_code == 403
    # buyer is a participant and may open
    r = client.post("/api/disputes", json={
        "transfer_id": transfer["id"], "reason": "fraud",
        "description": "seller scam"}, headers=auth(buyer))
    assert r.status_code == 201, r.text


# --- FIX: dispute refund resolution revokes the buyer's right ---
def test_dispute_refund_revokes_right(client):
    org_token, event, resource = _setup(client)
    seller, buyer, right, listing, transfer = _paid_completed_transfer(client, resource)
    r = client.post("/api/disputes", json={
        "transfer_id": transfer["id"], "reason": "fraud",
        "description": "seller scam"}, headers=auth(buyer))
    dispute = r.json()

    # admin resolves with refund
    admin = client.post("/api/auth/login", json={
        "email": "admin@access.marketplace",
        "password": "ChangeMe-Admin-2026!"}).json()["access_token"]
    r = client.post(f"/api/disputes/{dispute['id']}/resolve",
                    params={"action": "refund", "notes": "confirmed"},
                    headers=auth(admin))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "RESOLVED_REFUNDED"

    # buyer got the money back AND lost the right
    payment = [p for p in client.get("/api/payments/my", headers=auth(buyer)).json()
               if p["transfer_id"] == transfer["id"]][0]
    assert payment["status"] == "REFUNDED"
    my_rights = client.get("/api/access/my", headers=auth(buyer)).json()
    assert all(r_["status"] != "OWNED" for r_ in my_rights)


# --- FIX: queue join respects resource capacity ---
def test_queue_join_respects_capacity(client):
    org_token, event, resource = _setup(client, capacity=2)
    u1 = register_and_get_token(client, "cap-u1@x.io")
    u2 = register_and_get_token(client, "cap-u2@x.io")
    u3 = register_and_get_token(client, "cap-u3@x.io")
    assert client.post(f"/api/queues/resources/{resource['id']}/join", json={},
                       headers=auth(u1)).status_code == 201
    assert client.post(f"/api/queues/resources/{resource['id']}/join", json={},
                       headers=auth(u2)).status_code == 201
    r = client.post(f"/api/queues/resources/{resource['id']}/join", json={},
                    headers=auth(u3))
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "QUEUE_FULL"


# --- FIX: cancelled transfer deactivates its listing ---
def test_cancelled_transfer_deactivates_listing(client):
    org_token, event, resource = _setup(client)
    seller = register_and_get_token(client, "fix-seller@x.io")
    buyer = register_and_get_token(client, "fix-buyer@x.io")
    right = _join(client, seller, resource["id"])
    listing = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": 400}, headers=auth(seller)).json()
    transfer = client.post("/api/transfers/buy", json={
        "listing_id": listing["id"]}, headers=auth(buyer)).json()
    # cancel before payment completes the deal
    r = client.post(f"/api/transfers/{transfer['id']}/cancel", headers=auth(seller))
    assert r.status_code == 200, r.text
    listings = client.get("/api/transfers/listings", headers=auth(buyer)).json()
    assert all(l["id"] != listing["id"] for l in listings), \
        "cancelled transfer left an active (zombie) listing"
    # seller can re-list after cancel
    re_list = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": 500}, headers=auth(seller))
    assert re_list.status_code == 201, re_list.text


# --- FIX: another user's notification returns 403 ---
def test_notification_read_forbidden_for_stranger(client):
    user = register_and_get_token(client, "notif-user@x.io")
    notifications = client.get("/api/notifications", headers=auth(user)).json()
    if not notifications:
        # generate one by joining a queue
        org_token, event, resource = _setup(client)
        _join(client, user, resource["id"])
        notifications = client.get("/api/notifications", headers=auth(user)).json()
    notification = notifications[0]
    stranger = register_and_get_token(client, "notif-stranger@x.io")
    r = client.post(f"/api/notifications/{notification['id']}/read", headers=auth(stranger))
    assert r.status_code == 403
    r = client.post("/api/notifications/999999/read", headers=auth(user))
    assert r.status_code == 404


# --- FIX: imported event with a source_url becomes OFFICIAL (not REJECTED) ---
def test_imported_event_official_after_verification(client):
    user = register_and_get_token(client, "import-user@x.io")
    event = client.post("/api/events", json={
        "title": "Imported External Show", "starts_at": future_starts_at(),
        "city": "Moscow", "capacity": 100, "category": "CONCERT",
        "source_url": "https://example.com/official-event"},
        headers=auth(user)).json()
    assert event["source"] == "IMPORT"
    admin = client.post("/api/auth/login", json={
        "email": "admin@access.marketplace",
        "password": "ChangeMe-Admin-2026!"}).json()["access_token"]
    r = client.post(f"/api/events/{event['id']}/verify", headers=auth(admin))
    assert r.status_code == 200, r.text
    assert r.json()["verification_status"] == "OFFICIAL"


# --- FIX: one-time-code check-in by a stranger is forbidden ---
def test_otp_checkin_by_stranger_forbidden(client):
    org_token, event, resource = _setup(client)
    owner = register_and_get_token(client, "otp-owner@x.io")
    right = _join(client, owner, resource["id"])
    code = client.get(f"/api/access/{right['id']}/code", headers=auth(owner)).json()
    otp = code["one_time_code"]

    stranger = register_and_get_token(client, "otp-stranger@x.io")
    r = client.post("/api/checkins", json={
        "token": otp, "method": "CODE"}, headers=auth(stranger))
    assert r.status_code == 403

    # the owner can still check in with the same code
    r = client.post("/api/checkins", json={
        "token": otp, "method": "CODE"}, headers=auth(owner))
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "VALID"
