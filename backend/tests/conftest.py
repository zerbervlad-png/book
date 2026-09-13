"""Shared fixtures."""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

_tmp = tempfile.mkdtemp(prefix="am-test-")
os.environ["AM_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ.setdefault("AM_JWT_SECRET", "test-secret-" + "x" * 56)

from app.core.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)


def register(client, email, password="Password123!", name=None):
    r = client.post("/api/auth/register", json={
        "email": email, "password": password, "name": name or email.split("@")[0]})
    assert r.status_code == 201, r.text
    return r.json()


def register_and_get_token(client, email, **kw):
    return register(client, email, **kw)["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def make_event(client, token, title="Concert X", city="Moscow",
               capacity=10000, **extra):
    payload = {
        "title": title,
        "starts_at": "2026-09-25T20:00:00Z",
        "city": city,
        "capacity": capacity,
        "category": "CONCERT",
    }
    payload.update(extra)
    r = client.post("/api/events", json=payload, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def make_resource(client, token, event_id, rtype="EVENT_QUEUE", capacity=10000, **extra):
    payload = {
        "event_id": event_id,
        "type": rtype,
        "name": f"{rtype} resource",
        "capacity": capacity,
        "queue_policy": "FIFO",
    }
    payload.update(extra)
    r = client.post("/api/resources", json=payload, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()
