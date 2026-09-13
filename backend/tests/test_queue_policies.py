"""Queue policy tests — section 18 (FIFO, randomized, lottery, priority, hybrid)."""
from app.engines.queue_engine import draw
from app.core.database import SessionLocal
from app.models import Queue


def _join(client, token, resource_id, **payload):
    return client.post(f"/api/queues/resources/{resource_id}/join", json=payload,
                       headers={"Authorization": f"Bearer {token}"})


def test_fifo_order(client):
    from tests.conftest import auth, make_event, make_resource, register_and_get_token
    org = register_and_get_token(client, "fifo-org@x.io")
    client.post("/api/organizers", json={"name": "FIFO Org"}, headers=auth(org))
    event = make_event(client, org, title="FIFO Event")
    resource = make_resource(client, org, event["id"], queue_policy="FIFO")
    tokens = [register_and_get_token(client, f"fifo-{i}@x.io") for i in range(3)]
    positions = []
    for token in tokens:
        r = _join(client, token, resource["id"])
        positions.append(r.json()["position"])
    assert positions == [1, 2, 3]


def test_lottery_draw_assigns_all(client):
    from tests.conftest import auth, make_event, make_resource, register_and_get_token
    org = register_and_get_token(client, "lot-org@x.io")
    client.post("/api/organizers", json={"name": "Lot Org"}, headers=auth(org))
    event = make_event(client, org, title="Lottery Event")
    resource = make_resource(client, org, event["id"], queue_policy="LOTTERY")
    for i in range(4):
        token = register_and_get_token(client, f"lot-{i}@x.io")
        r = _join(client, token, resource["id"])
        assert r.json()["access_right"] is None  # pending draw

    with SessionLocal() as db:
        queue = db.query(Queue).filter(Queue.resource_id == resource["id"]).first()
        assigned = draw(db, queue, seed=42)
        db.commit()
    assert assigned == 4
