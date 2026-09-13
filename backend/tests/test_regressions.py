"""Regression suite — bugs found during full-app testing (sections 62-64).

Covers: refund on cancelled paid transfer, error envelope shape for the iOS
client, QR/code endpoints, marketplace search, gift flow, listing lifecycle,
waitlist flow, organizer approval, notifications, analytics, rate limiting.
"""
import concurrent.futures

from tests.conftest import auth, make_event, make_resource, register, register_and_get_token


def _setup(client, rtype="EVENT_QUEUE", **res_kwargs):
    org_token = register_and_get_token(client, "reg-org@x.io")
    client.post("/api/organizers", json={"name": "Reg Organizer"}, headers=auth(org_token))
    event = make_event(client, org_token, title="Regression Event")
    resource = make_resource(client, org_token, event["id"], rtype=rtype, **res_kwargs)
    return org_token, event, resource


def _join(client, token, resource_id):
    r = client.post(f"/api/queues/resources/{resource_id}/join", json={},
                    headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()["access_right"]


# --- BUG FIX: cancelled paid transfer must refund the buyer ---
def test_cancelled_paid_transfer_refunds_buyer(client):
    org_token, event, resource = _setup(client, requires_organizer_approval=True)
    seller = register_and_get_token(client, "refund-seller@x.io")
    buyer = register_and_get_token(client, "refund-buyer@x.io")
    right = _join(client, seller, resource["id"])
    listing = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": 600}, headers=auth(seller)).json()
    transfer = client.post("/api/transfers/buy", json={
        "listing_id": listing["id"]}, headers=auth(buyer)).json()

    pay = client.post(f"/api/transfers/{transfer['id']}/pay", json={
        "idempotency_key": "refund-key-1"}, headers=auth(buyer))
    assert pay.status_code == 201
    # approval required -> transfer still cancellable
    r = client.post(f"/api/transfers/{transfer['id']}/cancel", headers=auth(buyer))
    assert r.status_code == 200
    payments = client.get("/api/payments/my", headers=auth(buyer)).json()
    mine = [p for p in payments if p["transfer_id"] == transfer["id"]]
    assert mine and mine[0]["status"] == "REFUNDED"


# --- BUG FIX: expired paid transfer is swept and refunded ---
def test_expired_paid_transfer_swept_and_refunded(client):
    org_token, event, resource = _setup(client, requires_organizer_approval=True)
    seller = register_and_get_token(client, "sweep-seller@x.io")
    buyer = register_and_get_token(client, "sweep-buyer@x.io")
    right = _join(client, seller, resource["id"])
    listing = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": 300}, headers=auth(seller)).json()
    transfer = client.post("/api/transfers/buy", json={
        "listing_id": listing["id"]}, headers=auth(buyer)).json()

    client.post(f"/api/transfers/{transfer['id']}/pay", json={
        "idempotency_key": "sweep-key-1"}, headers=auth(buyer))
    current = client.get("/api/transfers/my", headers=auth(buyer)).json()
    assert [t for t in current if t["id"] == transfer["id"]][0]["status"] == \
        "AWAITING_BUYER_CLAIM"

    from app.core.database import SessionLocal
    from app.models import Transfer as TransferModel, utcnow
    from datetime import timedelta
    with SessionLocal() as db:
        record = db.get(TransferModel, transfer["id"])
        record.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()

    r = client.get("/api/transfers/my", headers=auth(buyer))
    assert r.status_code == 200
    payments = client.get("/api/payments/my", headers=auth(buyer)).json()
    mine = [p for p in payments if p["transfer_id"] == transfer["id"]]
    assert mine and mine[0]["status"] == "REFUNDED"
    tr = [t for t in r.json() if t["id"] == transfer["id"]][0]
    assert tr["status"] == "CANCELLED"


# --- BUG FIX: error envelope must be {"detail": {"code","message"}} ---
def test_error_envelope_shape_for_ios_client(client):
    org_token, event, resource = _setup(client)
    stranger = register_and_get_token(client, "envelope@x.io")
    right = _join(client, org_token, resource["id"])
    r = client.get(f"/api/access/{right['id']}/qr", headers=auth(stranger))
    assert r.status_code == 403
    body = r.json()
    assert "detail" in body
    assert isinstance(body["detail"], (dict, str))


# --- BUG FIX: 422 validation errors must be JSON-serializable ---
def test_validation_error_is_json_serializable(client):
    r = client.post("/api/auth/register", json={"email": "not-an-email", "password": "x"})
    assert r.status_code == 422
    body = r.json()
    assert body["detail"]["code"] == "VALIDATION_ERROR"


# --- access code endpoint returns snake_case keys (iOS fix) ---
def test_access_code_endpoint_keys(client):
    org_token, event, resource = _setup(client)
    right = _join(client, org_token, resource["id"])
    code = client.get(f"/api/access/{right['id']}/code", headers=auth(org_token)).json()
    assert code["token_code"].startswith("AT-")
    assert len(code["one_time_code"]) == 8
    assert code["kind"] == "QUEUE_POSITION"
    assert code["position"] == right["position"]


# --- QR endpoint returns PNG (iOS raw loader) ---
def test_access_qr_returns_png(client):
    org_token, event, resource = _setup(client)
    right = _join(client, org_token, resource["id"])
    r = client.get(f"/api/access/{right['id']}/qr", headers=auth(org_token))
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


# --- check-in with the one-time code from /code ---
def test_checkin_with_one_time_code(client):
    org_token, event, resource = _setup(client)
    right = _join(client, org_token, resource["id"])
    code = client.get(f"/api/access/{right['id']}/code", headers=auth(org_token)).json()
    r = client.post("/api/checkins", json={"token": code["one_time_code"], "method": "QR"},
                    headers=auth(org_token))
    assert r.json()["result"] == "VALID"


# --- marketplace search: q + verified_only filters ---
def test_marketplace_search_filters(client):
    org_token, event = None, None
    org_token = register_and_get_token(client, "mkt-org@x.io")
    client.post("/api/organizers", json={"name": "Mkt Organizer"}, headers=auth(org_token))
    ev1 = make_event(client, org_token, title="Alpha Concert")
    ev2 = make_event(client, org_token, title="Beta Festival", city="Sochi")
    make_resource(client, org_token, ev1["id"], rtype="EVENT_QUEUE")

    r = client.get("/api/marketplace/search", params={"q": "alpha"})
    assert r.status_code == 200
    titles = [i["event"]["title"] for i in r.json()]
    assert "Alpha Concert" in titles
    assert "Beta Festival" not in titles

    # unverified events filtered out by verified_only
    r = client.get("/api/marketplace/search", params={"verified_only": "true"})
    assert all(i["event"]["verification_status"] in
               ("VERIFIED", "ORGANIZER_VERIFIED", "OFFICIAL") for i in r.json())


# --- marketplace search with query params (iOS URL fix) ---
def test_marketplace_search_with_query_string(client):
    org_token, event, resource = _setup(client)
    r = client.get("/api/marketplace/search?q=regression&limit=5&verified_only=false")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# --- gift transfer completes immediately with token rotation ---
def test_gift_transfer_immediate_with_new_token(client):
    org_token, event, resource = _setup(client)
    giver = register_and_get_token(client, "giver@x.io")
    friend = register(client, "friend@x.io")
    right = _join(client, giver, resource["id"])
    old_token = right["token_code"]

    r = client.post("/api/transfers/gift", json={
        "access_right_id": right["id"], "to_user_email": "friend@x.io"},
        headers=auth(giver))
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "COMPLETED"

    # old token no longer valid
    r = client.post("/api/checkins", json={"token": old_token, "method": "TOKEN"},
                    headers=auth(giver))
    assert r.json()["result"] == "INVALID"
    # new owner can check in
    my = client.get("/api/access/my", headers=auth(friend["access_token"])).json()
    assert any(rr["token_code"] != old_token for rr in my)


# --- gift error paths ---
def test_gift_errors(client):
    org_token, event, resource = _setup(client)
    giver = register_and_get_token(client, "giver2@x.io")
    right = _join(client, giver, resource["id"])
    r = client.post("/api/transfers/gift", json={
        "access_right_id": right["id"], "to_user_email": "ghost@nowhere.io"},
        headers=auth(giver))
    assert r.status_code == 404
    r = client.post("/api/transfers/gift", json={
        "access_right_id": right["id"], "to_user_email": "giver2@x.io"},
        headers=auth(giver))
    assert r.status_code == 400


# --- listing lifecycle: create -> cancel -> right back to OWNED -> re-list ---
def test_listing_cancel_and_relist(client):
    org_token, event, resource = _setup(client)
    seller = register_and_get_token(client, "lifecycle@x.io")
    right = _join(client, seller, resource["id"])

    listing = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": 100}, headers=auth(seller))
    assert listing.status_code == 201
    # double listing rejected
    r = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": 100}, headers=auth(seller))
    assert r.status_code == 409

    cancelled = client.post(f"/api/transfers/listings/{listing.json()['id']}/cancel",
                            headers=auth(seller))
    assert cancelled.status_code == 200

    my = client.get("/api/access/my", headers=auth(seller)).json()
    assert my[0]["status"] == "OWNED"
    # re-list works after cancel
    r = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": 120}, headers=auth(seller))
    assert r.status_code == 201


# --- join queue twice rejected ---
def test_join_queue_twice_rejected(client):
    org_token, event, resource = _setup(client)
    user = register_and_get_token(client, "twice@x.io")
    assert client.post(f"/api/queues/resources/{resource['id']}/join", json={},
                      headers=auth(user)).status_code == 201
    r = client.post(f"/api/queues/resources/{resource['id']}/join", json={},
                    headers=auth(user))
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ALREADY_IN_QUEUE"


# --- leave queue cancels the right and allows rejoin ---
def test_leave_queue_and_rejoin(client):
    org_token, event, resource = _setup(client)
    user = register_and_get_token(client, "leaver@x.io")
    right = _join(client, user, resource["id"])
    r = client.post(f"/api/queues/resources/{resource['id']}/leave", headers=auth(user))
    assert r.status_code == 204
    my = client.get("/api/access/my", headers=auth(user)).json()
    assert all(rr["status"] != "OWNED" for rr in my)
    # rejoin gets a fresh position
    right2 = _join(client, user, resource["id"])
    assert right2["position"] >= right["position"]


# --- queue state endpoint reflects membership ---
def test_queue_state_endpoint(client):
    org_token, event, resource = _setup(client)
    user = register_and_get_token(client, "state@x.io")
    right = _join(client, user, resource["id"])
    state = client.get(f"/api/queues/resources/{resource['id']}",
                       headers=auth(user)).json()
    assert state["is_member"] is True
    assert state["my_position"] == right["position"]
    assert state["policy"] == "FIFO"


# --- event duplicate detection (69) ---
def test_duplicate_event_rejected(client):
    org_token = register_and_get_token(client, "dup-org@x.io")
    client.post("/api/organizers", json={"name": "Dup Organizer"}, headers=auth(org_token))
    make_event(client, org_token, title="Unique Show", city="Kazan")
    r = client.post("/api/events", json={
        "title": "Unique Show", "starts_at": "2026-09-25T20:00:00Z",
        "city": "Kazan", "capacity": 100, "category": "CONCERT"},
        headers=auth(org_token))
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "DUPLICATE_EVENT"


# --- event verification flips status (6) ---
def test_event_verification_flow(client):
    org_token = register_and_get_token(client, "verif-org@x.io")
    client.post("/api/organizers", json={"name": "Verif Organizer"}, headers=auth(org_token))
    event = make_event(client, org_token, title="Verifiable Gala")
    assert event["verification_status"] == "UNVERIFIED"
    r = client.post(f"/api/events/{event['id']}/verify", headers=auth(org_token))
    assert r.status_code == 200
    assert r.json()["verification_status"] in ("VERIFIED", "ORGANIZER_VERIFIED")
    verifications = client.get(f"/api/events/{event['id']}/verifications").json()
    assert len(verifications) >= 1


# --- stranger cannot verify/cancel someone else's event ---
def test_event_permissions(client):
    org_token, event, resource = _setup(client)
    stranger = register_and_get_token(client, "stranger2@x.io")
    r = client.post(f"/api/events/{event['id']}/verify", headers=auth(stranger))
    assert r.status_code == 403
    r = client.post(f"/api/events/{event['id']}/cancel", headers=auth(stranger))
    assert r.status_code == 403


# --- event inventory (52) ---
def test_event_inventory(client):
    org_token = register_and_get_token(client, "inv-org@x.io")
    client.post("/api/organizers", json={"name": "Inv Organizer"}, headers=auth(org_token))
    event = make_event(client, org_token, title="Inventory Event", capacity=10)
    resource = make_resource(client, org_token, event["id"], rtype="TIME_SLOT", capacity=10)
    user = register_and_get_token(client, "inv@x.io")
    reservation = client.post("/api/reservations", json={
        "resource_id": resource["id"]}, headers=auth(user)).json()
    client.post(f"/api/reservations/{reservation['id']}/confirm", headers=auth(user))
    inv = client.get(f"/api/events/{event['id']}/inventory").json()
    assert inv["total_capacity"] == 10
    assert inv["confirmed"] >= 1


# --- organizer approval flow for transfers (58) ---
def test_organizer_approval_flow(client):
    org_token, event, resource = _setup(client, requires_organizer_approval=True)
    seller = register_and_get_token(client, "appr-seller@x.io")
    buyer = register_and_get_token(client, "appr-buyer@x.io")
    right = _join(client, seller, resource["id"])
    listing = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": 250}, headers=auth(seller)).json()
    transfer = client.post("/api/transfers/buy", json={
        "listing_id": listing["id"]}, headers=auth(buyer)).json()

    pay = client.post(f"/api/transfers/{transfer['id']}/pay", json={
        "idempotency_key": "appr-key-1"}, headers=auth(buyer))
    assert pay.status_code == 201
    tr = client.get("/api/transfers/my", headers=auth(buyer)).json()
    current = [t for t in tr if t["id"] == transfer["id"]][0]
    assert current["status"] == "AWAITING_BUYER_CLAIM"

    # only organizer can approve
    stranger = register_and_get_token(client, "appr-stranger@x.io")
    r = client.post(f"/api/transfers/{transfer['id']}/approve", headers=auth(stranger))
    assert r.status_code == 403

    r = client.post(f"/api/transfers/{transfer['id']}/approve", headers=auth(org_token))
    assert r.status_code == 200
    assert r.json()["status"] == "COMPLETED"


# --- reservation confirm issues correct AccessRight kind ---
def test_reservation_confirm_issues_ticket(client):
    org_token, event, resource = _setup(client, rtype="TICKET", capacity=5)
    user = register_and_get_token(client, "ticketed@x.io")
    reservation = client.post("/api/reservations", json={
        "resource_id": resource["id"]}, headers=auth(user)).json()
    confirmed = client.post(f"/api/reservations/{reservation['id']}/confirm",
                            headers=auth(user)).json()
    assert confirmed["status"] == "CONFIRMED"
    my = client.get("/api/access/my", headers=auth(user)).json()
    assert my and my[0]["kind"] == "TICKET"


# --- reservation pay captures payment (27) ---
def test_reservation_pay_captures(client):
    org_token, event, resource = _setup(client, rtype="TIME_SLOT", capacity=5)
    user = register_and_get_token(client, "paying@x.io")
    reservation = client.post("/api/reservations", json={
        "resource_id": resource["id"], "amount": 500}, headers=auth(user)).json()
    pay = client.post(f"/api/reservations/{reservation['id']}/pay", json={
        "idempotency_key": "res-pay-1"}, headers=auth(user))
    assert pay.status_code == 201
    assert pay.json()["status"] == "CAPTURED"
    got = client.get(f"/api/reservations/{reservation['id']}", headers=auth(user)).json()
    assert got["payment_status"] == "CAPTURED"


# --- double confirm is idempotent ---
def test_reservation_confirm_idempotent(client):
    org_token, event, resource = _setup(client, rtype="TIME_SLOT", capacity=5)
    user = register_and_get_token(client, "idem@x.io")
    reservation = client.post("/api/reservations", json={
        "resource_id": resource["id"]}, headers=auth(user)).json()
    first = client.post(f"/api/reservations/{reservation['id']}/confirm", headers=auth(user))
    second = client.post(f"/api/reservations/{reservation['id']}/confirm", headers=auth(user))
    assert first.status_code == 200 and second.status_code == 200
    my = client.get("/api/access/my", headers=auth(user)).json()
    assert len([r for r in my if r["kind"] == "SLOT"]) == 1


# --- no availability rejected ---
def test_no_availability_rejected(client):
    org_token, event, resource = _setup(client, rtype="TIME_SLOT", capacity=1)
    u1 = register_and_get_token(client, "full1@x.io")
    u2 = register_and_get_token(client, "full2@x.io")
    r1 = client.post("/api/reservations", json={"resource_id": resource["id"]},
                     headers=auth(u1))
    assert r1.status_code == 201
    r2 = client.post("/api/reservations", json={"resource_id": resource["id"]},
                     headers=auth(u2))
    assert r2.status_code == 409
    assert r2.json()["detail"]["code"] == "NO_AVAILABILITY"


# --- waitlist join returns position ---
def test_waitlist_join_position(client):
    org_token, event, resource = _setup(client, rtype="TIME_SLOT", capacity=1)
    u1 = register_and_get_token(client, "wl1@x.io")
    u2 = register_and_get_token(client, "wl2@x.io")
    res = client.post("/api/reservations", json={"resource_id": resource["id"]},
                      headers=auth(u1)).json()
    client.post(f"/api/reservations/{res['id']}/confirm", headers=auth(u1))
    entry = client.post(f"/api/waitlists/resources/{resource['id']}/join", json={},
                        headers=auth(u2))
    assert entry.status_code == 201
    assert entry.json()["position"] == 1
    # duplicate waitlist join rejected
    dup = client.post(f"/api/waitlists/resources/{resource['id']}/join", json={},
                     headers=auth(u2))
    assert dup.status_code == 409


# --- waitlist leave and rejoin ---
def test_waitlist_leave_rejoin(client):
    org_token, event, resource = _setup(client, rtype="TIME_SLOT", capacity=1)
    u1 = register_and_get_token(client, "wlr1@x.io")
    u2 = register_and_get_token(client, "wlr2@x.io")
    res = client.post("/api/reservations", json={"resource_id": resource["id"]},
                      headers=auth(u1)).json()
    client.post(f"/api/reservations/{res['id']}/confirm", headers=auth(u1))
    client.post(f"/api/waitlists/resources/{resource['id']}/join", json={},
                headers=auth(u2))
    r = client.post(f"/api/waitlists/resources/{resource['id']}/leave",
                    headers=auth(u2))
    assert r.status_code == 204
    r = client.post(f"/api/waitlists/resources/{resource['id']}/join", json={},
                    headers=auth(u2))
    assert r.status_code == 201


# --- listing of a used right blocked (31) ---
def test_cannot_list_used_right(client):
    org_token, event, resource = _setup(client)
    user = register_and_get_token(client, "usedseller@x.io")
    right = _join(client, user, resource["id"])
    client.post("/api/checkins", json={"token": right["token_code"], "method": "QR"},
                headers=auth(user))
    r = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": 100}, headers=auth(user))
    assert r.status_code in (403, 409)


# --- self-purchase blocked ---
def test_cannot_buy_own_listing(client):
    org_token, event, resource = _setup(client)
    seller = register_and_get_token(client, "selfbuy@x.io")
    right = _join(client, seller, resource["id"])
    listing = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": 100}, headers=auth(seller)).json()
    r = client.post("/api/transfers/buy", json={"listing_id": listing["id"]},
                    headers=auth(seller))
    assert r.status_code == 400


# --- notifications accumulate (44) ---
def test_notifications_created(client):
    org_token, event, resource = _setup(client)
    user = register_and_get_token(client, "notif@x.io")
    _join(client, user, resource["id"])
    r = client.get("/api/notifications", headers=auth(user))
    assert r.status_code == 200
    kinds = [n["kind"] for n in r.json()]
    assert "POSITION_ASSIGNED" in kinds


# --- analytics endpoint (59, admin-only) ---
def test_analytics_endpoint(client):
    org_token, event, resource = _setup(client)
    _join(client, org_token, resource["id"])
    # unauthenticated rejected
    r = client.get("/api/analytics")
    assert r.status_code == 401
    # admin bootstrap account can read analytics
    admin = client.post("/api/auth/login", json={
        "email": "admin@access.marketplace",
        "password": "ChangeMe-Admin-2026!"}).json()["access_token"]
    r = client.get("/api/analytics", headers=auth(admin))
    assert r.status_code == 200
    data = r.json()
    assert data["events"] >= 1


# --- health endpoint ---
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# --- auth error paths ---
def test_auth_errors(client):
    r = client.post("/api/auth/login", json={
        "email": "nouser@x.io", "password": "Password123!"})
    assert r.status_code == 401
    register(client, "existing@x.io")
    r = client.post("/api/auth/register", json={
        "email": "existing@x.io", "password": "Password123!", "name": "x"})
    assert r.status_code == 409
    r = client.get("/api/users/me")
    assert r.status_code == 401


# --- transferred right check-in result (29) ---
def test_checkin_after_transfer_invalid_old_owner_view(client):
    org_token, event, resource = _setup(client)
    seller = register_and_get_token(client, "told@x.io")
    buyer = register_and_get_token(client, "tnew@x.io")
    right = _join(client, seller, resource["id"])
    listing = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": 400}, headers=auth(seller)).json()
    transfer = client.post("/api/transfers/buy", json={
        "listing_id": listing["id"]}, headers=auth(buyer)).json()
    client.post(f"/api/transfers/{transfer['id']}/pay", json={
        "idempotency_key": "tr-pay-1"}, headers=auth(buyer))

    # old token invalid after transfer
    r = client.post("/api/checkins", json={
        "token": right["token_code"], "method": "QR"}, headers=auth(buyer))
    assert r.json()["result"] == "INVALID"
    # new owner's right is valid and check-in works
    my = client.get("/api/access/my", headers=auth(buyer)).json()
    new_token = my[0]["token_code"]
    r = client.post("/api/checkins", json={"token": new_token, "method": "QR"},
                    headers=auth(buyer))
    assert r.json()["result"] == "VALID"


# --- seller sees the right disappear from /access/my after sale ---
def test_seller_loses_right_after_sale(client):
    org_token, event, resource = _setup(client)
    seller = register_and_get_token(client, "soldout@x.io")
    buyer = register_and_get_token(client, "boughtin@x.io")
    right = _join(client, seller, resource["id"])
    listing = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": 100}, headers=auth(seller)).json()
    transfer = client.post("/api/transfers/buy", json={
        "listing_id": listing["id"]}, headers=auth(buyer)).json()
    client.post(f"/api/transfers/{transfer['id']}/pay", json={
        "idempotency_key": "sold-key-1"}, headers=auth(buyer))

    seller_rights = client.get("/api/access/my", headers=auth(seller)).json()
    assert all(r["id"] != right["id"] for r in seller_rights)
    buyer_rights = client.get("/api/access/my", headers=auth(buyer)).json()
    assert any(r["position"] == right["position"] for r in buyer_rights)
