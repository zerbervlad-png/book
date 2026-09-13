"""E2E tests — section 63 (mandatory).

E2E 1: Event creation -> Verification -> Queue -> Position.
E2E 2: Position -> Listing -> Purchase -> Transfer.
E2E 3: Waitlist -> Available slot -> Reservation -> Confirmation.
E2E 4: Ticket -> Transfer -> Old token invalid -> New token valid.
E2E 5: Check-in -> Token used -> repeated entry denied.
"""
from tests.conftest import auth, make_event, make_resource, register, register_and_get_token


# ---------------- E2E 1 ----------------
def test_e2e_1_event_verification_queue_position(client):
    org_token = register_and_get_token(client, "org1@x.io")
    client.post("/api/organizers", json={"name": "Organizer One"}, headers=auth(org_token))
    event = make_event(client, org_token, title="Concert X — E2E1")
    # duplicate must be rejected (69)
    dup = client.post("/api/events", json={
        "title": "Concert X — E2E1", "starts_at": "2026-09-25T20:00:00Z",
        "city": "Moscow"}, headers=auth(org_token))
    assert dup.status_code == 409
    assert dup.json()["detail"]["code"] == "DUPLICATE_EVENT"

    # verify (organizer triggers engine)
    r = client.post(f"/api/events/{event['id']}/verify", headers=auth(org_token))
    assert r.status_code == 200, r.text
    assert r.json()["verification_status"] in ("VERIFIED", "ORGANIZER_VERIFIED")

    resource = make_resource(client, org_token, event["id"], rtype="EVENT_QUEUE")
    # queue opens BEFORE the event (section 8): user joins hours ahead
    user_token = register_and_get_token(client, "fan1@x.io")
    r = client.post(f"/api/queues/resources/{resource['id']}/join", json={},
                    headers=auth(user_token))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["position"] == 1
    assert body["access_right"]["kind"] == "QUEUE_POSITION"
    assert body["access_right"]["status"] == "OWNED"

    # event card contains everything required by section 22
    card = client.get(f"/api/events/{event['id']}").json()
    for field in ("title", "starts_at", "city", "verification_status", "status", "capacity"):
        assert field in card


# ---------------- E2E 2 ----------------
def test_e2e_2_position_listing_purchase_transfer(client):
    org_token = register_and_get_token(client, "org2@x.io")
    client.post("/api/organizers", json={"name": "Organizer Two"}, headers=auth(org_token))
    event = make_event(client, org_token, title="Festival Y")
    resource = make_resource(client, org_token, event["id"], rtype="EVENT_QUEUE")

    seller = register_and_get_token(client, "seller@x.io")
    buyer = register_and_get_token(client, "buyer@x.io")

    r = client.post(f"/api/queues/resources/{resource['id']}/join", json={},
                    headers=auth(seller))
    right = r.json()["access_right"]

    # list for 10 000 RUB (in minor units — 10000)
    r = client.post("/api/transfers/listings", json={
        "access_right_id": right["id"], "price": 10000}, headers=auth(seller))
    assert r.status_code == 201, r.text
    listing = r.json()
    assert listing["kind"] == "RESALE"

    # buyer purchases: initiate + pay
    r = client.post("/api/transfers/buy", json={
        "listing_id": listing["id"], "idempotency_key": "e2e2-buy-1"}, headers=auth(buyer))
    assert r.status_code == 201, r.text
    transfer = r.json()
    assert transfer["status"] == "AWAITING_PAYMENT"

    r = client.post(f"/api/transfers/{transfer['id']}/pay", json={
        "idempotency_key": "e2e2-pay-1"}, headers=auth(buyer))
    assert r.status_code == 201, r.text
    transfer = client.get(f"/api/transfers/my", headers=auth(buyer)).json()[0]
    assert transfer["status"] == "COMPLETED"

    # new owner is the buyer; old token invalidated (13)
    rights = client.get("/api/access/my", headers=auth(buyer)).json()
    mine = [x for x in rights if x["id"] == right["id"]][0]
    assert mine["owner_user_id"] == client.get("/api/users/me", headers=auth(buyer)).json()["id"]
    assert mine["token_code"] != right["token_code"]

    seller_rights = client.get("/api/access/my", headers=auth(seller)).json()
    assert all(x["id"] != right["id"] for x in seller_rights)


# ---------------- E2E 3 ----------------
def test_e2e_3_waitlist_slot_reservation_confirmation(client):
    org_token = register_and_get_token(client, "org3@x.io")
    client.post("/api/organizers", json={"name": "Organizer Three"}, headers=auth(org_token))
    event = make_event(client, org_token, title="Dinner Club", capacity=1)
    # TIME_SLOT resource with capacity 1 — sold out after first booking
    resource = make_resource(client, org_token, event["id"], rtype="TIME_SLOT", capacity=1)

    first = register_and_get_token(client, "first@x.io")
    second = register_and_get_token(client, "second@x.io")

    # first user books the only slot
    r = client.post("/api/reservations", json={"resource_id": resource["id"]},
                    headers=auth(first))
    assert r.status_code == 201, r.text
    reservation = r.json()
    r = client.post(f"/api/reservations/{reservation['id']}/confirm", headers=auth(first))
    assert r.status_code == 200
    assert r.json()["status"] == "CONFIRMED"

    # availability is now zero -> second user must go to waitlist
    r = client.post("/api/reservations", json={"resource_id": resource["id"]},
                    headers=auth(second))
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "NO_AVAILABILITY"

    r = client.post(f"/api/waitlists/resources/{resource['id']}/join", json={},
                    headers=auth(second))
    assert r.status_code == 201, r.text
    entry = r.json()
    assert entry["position"] == 1

    # first user cancels -> place frees -> waitlist offer created
    r = client.get("/api/reservations/my", headers=auth(first))
    reservation_id = r.json()[0]["id"]
    client.post(f"/api/reservations/{reservation_id}/cancel", headers=auth(first))

    r = client.get(f"/api/waitlists/resources/{resource['id']}/me", headers=auth(second))
    entry = r.json()
    assert entry["status"] == "OFFERED", entry

    # second user confirms within the window -> reservation
    r = client.post(f"/api/waitlists/entries/{entry['id']}/confirm", json={},
                    headers=auth(second))
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "HELD"
    r = client.post(f"/api/reservations/{r.json()['id']}/confirm", headers=auth(second))
    assert r.status_code == 200
    assert r.json()["status"] == "CONFIRMED"


# ---------------- E2E 4 ----------------
def test_e2e_4_ticket_transfer_old_invalid_new_valid(client):
    org_token = register_and_get_token(client, "org4@x.io")
    client.post("/api/organizers", json={"name": "Organizer Four"}, headers=auth(org_token))
    event = make_event(client, org_token, title="Stadium Show", capacity=1000)
    resource = make_resource(client, org_token, event["id"], rtype="TICKET", capacity=1000,
                             payload={"seat": "A-12"})

    holder = register_and_get_token(client, "holder@x.io")
    friend = register_and_get_token(client, "friend@x.io")

    r = client.post("/api/reservations", json={"resource_id": resource["id"]},
                    headers=auth(holder))
    reservation = r.json()
    client.post(f"/api/reservations/{reservation['id']}/confirm", headers=auth(holder))
    rights = client.get("/api/access/my", headers=auth(holder)).json()
    ticket = rights[0]
    assert ticket["kind"] == "TICKET"
    old_token = ticket["token_code"]

    # gift transfer (57: transfer without money)
    r = client.post("/api/transfers/gift", json={
        "access_right_id": ticket["id"], "to_user_email": "friend@x.io"},
        headers=auth(holder))
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "COMPLETED"

    # new owner's token differs and is valid for check-in
    new_rights = client.get("/api/access/my", headers=auth(friend)).json()
    new_ticket = [x for x in new_rights if x["id"] == ticket["id"]][0]
    assert new_ticket["token_code"] != old_token

    r = client.post("/api/checkins", json={"token": new_ticket["token_code"], "method": "QR"},
                    headers=auth(friend))
    assert r.json()["result"] == "VALID"

    # old token is invalid now (13, 16)
    r = client.post("/api/checkins", json={"token": old_token, "method": "QR"},
                    headers=auth(holder))
    assert r.json()["result"] == "INVALID"


# ---------------- E2E 5 ----------------
def test_e2e_5_checkin_token_used_reentry_denied(client):
    org_token = register_and_get_token(client, "org5@x.io")
    client.post("/api/organizers", json={"name": "Organizer Five"}, headers=auth(org_token))
    event = make_event(client, org_token, title="Club Night", capacity=500)
    resource = make_resource(client, org_token, event["id"], rtype="EVENT_QUEUE", capacity=500)

    user = register_and_get_token(client, "guest@x.io")
    r = client.post(f"/api/queues/resources/{resource['id']}/join", json={},
                    headers=auth(user))
    right = r.json()["access_right"]

    # one-time code check-in
    code = client.get(f"/api/access/{right['id']}/code", headers=auth(user)).json()
    otp = code["one_time_code"]
    r = client.post("/api/checkins", json={"token": otp, "method": "CODE"},
                    headers=auth(user))
    assert r.status_code == 200
    assert r.json()["result"] == "VALID"

    # repeated entry denied
    r = client.post("/api/checkins", json={"token": otp, "method": "CODE"},
                    headers=auth(user))
    assert r.json()["result"] in ("USED", "INVALID")

    r = client.post("/api/checkins", json={"token": code["token_code"], "method": "TOKEN"},
                    headers=auth(user))
    assert r.json()["result"] == "USED"
