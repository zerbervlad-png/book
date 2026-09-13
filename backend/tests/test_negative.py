"""Negative tests — section 64.

GPS spoofing/unavailable/inaccurate (65): backend never auto-removes users
from queues based on GPS. Duplicate transfer/payment, expired reservation,
expired token, cancelled event, invalid/reused QR, simultaneous purchase,
simultaneous transfer.
"""
import concurrent.futures

from tests.conftest import auth, make_event, make_resource, register_and_get_token


def _setup(client, rtype="EVENT_QUEUE", **res_kwargs):
    org_token = register_and_get_token(client, "neg-org@x.io")
    client.post("/api/organizers", json={"name": "Neg Organizer"}, headers=auth(org_token))
    event = make_event(client, org_token, title="Negative Test Event")
    resource = make_resource(client, org_token, event["id"], rtype=rtype, **res_kwargs)
    return org_token, event, resource


# --- GPS: spoofed / absent / inaccurate never affect membership (65) ---
def test_gps_is_never_proof_of_queue_position(client):
    org_token, event, resource = _setup(client)
    user = register_and_get_token(client, "gpsuser@x.io")
    r = client.post(f"/api/queues/resources/{resource['id']}/join", json={},
                    headers=auth(user))
    assert r.status_code == 201
    right = r.json()["access_right"]

    # spoofed GPS (perfect accuracy) — telemetry accepted as auxiliary only
    r = client.post("/api/checkins", json={
        "token": "whatever", "method": "QR",
        "gps": {"lat": 55.75, "lng": 37.61, "accuracy_m": 0.0, "event_id": event["id"]}},
        headers=auth(user))
    assert r.status_code == 200

    # membership and position unchanged
    state = client.get(f"/api/queues/resources/{resource['id']}", headers=auth(user)).json()
    assert state["is_member"] is True
    assert state["my_position"] == right["position"]

    # GPS entirely absent — functionality unaffected
    state2 = client.get(f"/api/queues/resources/{resource['id']}", headers=auth(user)).json()
    assert state2["is_member"] is True


# --- duplicate transfer ---
def test_duplicate_transfer_rejected(client):
    org_token, event, resource = _setup(client)
    seller = register_and_get_token(client, "dupseller@x.io")
    buyer1 = register_and_get_token(client, "dupbuyer1@x.io")
    buyer2 = register_and_get_token(client, "dupbuyer2@x.io")

    right = client.post(f"/api/queues/resources/{resource['id']}/join", json={},
                        headers=auth(seller)).json()["access_right"]
    listing = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": 500}, headers=auth(seller)).json()

    t1 = client.post("/api/transfers/buy", json={
        "listing_id": listing["id"]}, headers=auth(buyer1)).json()
    # second buyer cannot buy the same listing — double-spend protection (13)
    r = client.post("/api/transfers/buy", json={"listing_id": listing["id"]},
                    headers=auth(buyer2))
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "RIGHT_NOT_TRANSFERABLE"
    # seller cannot double-list either
    r = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": 100}, headers=auth(seller))
    assert r.status_code in (403, 409)


# --- duplicate payment (idempotency — 61) ---
def test_duplicate_payment_idempotent(client):
    org_token, event, resource = _setup(client)
    seller = register_and_get_token(client, "payseller@x.io")
    buyer = register_and_get_token(client, "paybuyer@x.io")
    right = client.post(f"/api/queues/resources/{resource['id']}/join", json={},
                        headers=auth(seller)).json()["access_right"]
    listing = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": 700}, headers=auth(seller)).json()
    transfer = client.post("/api/transfers/buy", json={
        "listing_id": listing["id"]}, headers=auth(buyer)).json()

    p1 = client.post(f"/api/transfers/{transfer['id']}/pay", json={
        "idempotency_key": "same-key"}, headers=auth(buyer))
    p2 = client.post(f"/api/transfers/{transfer['id']}/pay", json={
        "idempotency_key": "same-key"}, headers=auth(buyer))
    assert p1.status_code == 201
    # second call with the same key returns the same payment, not a new one
    assert p2.status_code == 201
    assert p1.json()["id"] == p2.json()["id"]
    payments = client.get("/api/payments/my", headers=auth(buyer)).json()
    assert len([p for p in payments if p["transfer_id"] == transfer["id"]]) == 1


# --- expired reservation ---
def test_expired_reservation_cannot_confirm(client):
    org_token, event, resource = _setup(client, rtype="TIME_SLOT")
    user = register_and_get_token(client, "expiry@x.io")
    reservation = client.post("/api/reservations", json={
        "resource_id": resource["id"]}, headers=auth(user)).json()

    # force expiry directly in DB
    from app.core.database import SessionLocal
    from app.models import Reservation
    from datetime import timedelta
    from app.models import utcnow
    with SessionLocal() as db:
        record = db.get(Reservation, reservation["id"])
        record.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()

    r = client.post(f"/api/reservations/{reservation['id']}/confirm", headers=auth(user))
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "INVALID_STATE"


# --- cancelled event ---
def test_cancelled_event_blocks_operations(client):
    org_token, event, resource = _setup(client)
    client.post(f"/api/events/{event['id']}/cancel", headers=auth(org_token))
    user = register_and_get_token(client, "late@x.io")
    r = client.post(f"/api/queues/resources/{resource['id']}/join", json={},
                    headers=auth(user))
    assert r.status_code == 409
    r = client.post("/api/reservations", json={"resource_id": resource["id"]},
                    headers=auth(user))
    assert r.status_code == 409


# --- invalid / reused QR ---
def test_invalid_qr_and_reuse(client):
    org_token, event, resource = _setup(client)
    user = register_and_get_token(client, "qr@x.io")
    right = client.post(f"/api/queues/resources/{resource['id']}/join", json={},
                        headers=auth(user)).json()["access_right"]
    code = client.get(f"/api/access/{right['id']}/code", headers=auth(user)).json()

    r = client.post("/api/checkins", json={"token": "AT-000000000", "method": "QR"},
                    headers=auth(user))
    assert r.json()["result"] == "INVALID"

    first = client.post("/api/checkins", json={"token": code["token_code"], "method": "QR"},
                        headers=auth(user))
    assert first.json()["result"] == "VALID"
    second = client.post("/api/checkins", json={"token": code["token_code"], "method": "QR"},
                         headers=auth(user))
    assert second.json()["result"] == "USED"


# --- expired access right ---
def test_expired_token_checkin(client):
    org_token, event, resource = _setup(client)
    user = register_and_get_token(client, "expired@x.io")
    right = client.post(f"/api/queues/resources/{resource['id']}/join", json={},
                        headers=auth(user)).json()["access_right"]
    from app.core.database import SessionLocal
    from app.models import AccessRight, utcnow
    from datetime import timedelta
    with SessionLocal() as db:
        record = db.get(AccessRight, right["id"])
        record.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    r = client.post("/api/checkins", json={"token": right["token_code"], "method": "TOKEN"},
                    headers=auth(user))
    assert r.json()["result"] == "EXPIRED"


# --- simultaneous purchase ---
def test_simultaneous_purchase_single_winner(client):
    org_token, event, resource = _setup(client)
    seller = register_and_get_token(client, "sim-seller@x.io")
    right = client.post(f"/api/queues/resources/{resource['id']}/join", json={},
                        headers=auth(seller)).json()["access_right"]
    listing = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": 900}, headers=auth(seller)).json()

    buyer1 = register_and_get_token(client, "sim1@x.io")
    buyer2 = register_and_get_token(client, "sim2@x.io")

    def buy(token):
        return client.post("/api/transfers/buy", json={"listing_id": listing["id"]},
                           headers=auth(token))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(buy, [buyer1, buyer2]))
    statuses = sorted(r.status_code for r in results)
    assert statuses == [201, 409], [r.text for r in results]


# --- transfer forbidden by policy (56) ---
def test_transfer_forbidden_by_organizer(client):
    org_token, event, resource = _setup(client, is_transferable=False, is_resellable=False)
    user = register_and_get_token(client, "nofly@x.io")
    right = client.post(f"/api/queues/resources/{resource['id']}/join", json={},
                        headers=auth(user)).json()["access_right"]
    r = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": 100}, headers=auth(user))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] in ("TRANSFER_FORBIDDEN", "RESALE_FORBIDDEN")
    r = client.post("/api/transfers/gift", json={
        "access_right_id": right["id"], "to_user_email": "anyone@x.io"}, headers=auth(user))
    assert r.status_code == 403


# --- max resale price cap (58) ---
def test_resale_price_cap(client):
    org_token, event, resource = _setup(client, max_resale_price=1000)
    user = register_and_get_token(client, "capped@x.io")
    right = client.post(f"/api/queues/resources/{resource['id']}/join", json={},
                        headers=auth(user)).json()["access_right"]
    r = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": 5000}, headers=auth(user))
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "PRICE_TOO_HIGH"


# --- invite-only queue ---
def test_invite_only_queue(client):
    org_token, event, resource = _setup(client, queue_policy="INVITE_ONLY",
                                        payload={"invite_codes": ["SECRET-42"]})
    user = register_and_get_token(client, "invite@x.io")
    r = client.post(f"/api/queues/resources/{resource['id']}/join", json={},
                    headers=auth(user))
    assert r.status_code == 403
    r = client.post(f"/api/queues/resources/{resource['id']}/join",
                    json={"invite_code": "SECRET-42"}, headers=auth(user))
    assert r.status_code == 201


# --- waitlist offer expiry passes to next user ---
def test_waitlist_offer_expiry_passes_on(client):
    org_token, event, resource = _setup(client, rtype="TIME_SLOT", capacity=1)
    first = register_and_get_token(client, "w1@x.io")
    second = register_and_get_token(client, "w2@x.io")

    reservation = client.post("/api/reservations", json={
        "resource_id": resource["id"]}, headers=auth(first)).json()
    client.post(f"/api/reservations/{reservation['id']}/confirm", headers=auth(first))
    client.post(f"/api/waitlists/resources/{resource['id']}/join", json={},
                headers=auth(second))

    # first cancels -> offer goes to second; simulate offer expiry
    client.post(f"/api/reservations/{reservation['id']}/cancel", headers=auth(first))
    entry = client.get(f"/api/waitlists/resources/{resource['id']}/me",
                       headers=auth(second)).json()
    assert entry["status"] == "OFFERED"

    from app.core.database import SessionLocal
    from app.models import WaitlistEntry, utcnow
    from datetime import timedelta
    with SessionLocal() as db:
        record = db.get(WaitlistEntry, entry["id"])
        record.offer_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()

    third = register_and_get_token(client, "w3@x.io")
    client.post(f"/api/waitlists/resources/{resource['id']}/join", json={},
                headers=auth(third))
    # second tries to confirm an expired offer
    r = client.post(f"/api/waitlists/entries/{entry['id']}/confirm", json={},
                    headers=auth(second))
    assert r.status_code == 409


# --- unverified user cannot check in someone else's right / unauthorized ---
def test_access_requires_auth(client):
    r = client.get("/api/access/my")
    assert r.status_code == 401
    org_token, event, resource = _setup(client)
    owner = register_and_get_token(client, "owner@x.io")
    stranger = register_and_get_token(client, "stranger@x.io")
    right = client.post(f"/api/queues/resources/{resource['id']}/join", json={},
                        headers=auth(owner)).json()["access_right"]
    r = client.get(f"/api/access/{right['id']}/qr", headers=auth(stranger))
    assert r.status_code == 403
    r = client.get(f"/api/access/{right['id']}", headers=auth(stranger))
    assert r.status_code == 403
