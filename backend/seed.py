"""Seed demo data + test accounts (run: python seed.py).

Test accounts:
  Пользователь:  demo@access.marketplace / Demo1234pass!
  Организатор:   org@access.marketplace  / Org1234pass!
  Админ:         admin@access.marketplace / ChangeMe-Admin-2026!

Idempotent — safe to run multiple times.
"""
from fastapi.testclient import TestClient

from app.main import app

DEMO_EMAIL = "demo@access.marketplace"
DEMO_PASSWORD = "Demo1234pass!"
ORG_EMAIL = "org@access.marketplace"
ORG_PASSWORD = "Org1234pass!"


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def register(client, email, password, name):
    r = client.post("/api/auth/register", json={
        "email": email, "password": password, "name": name})
    assert r.status_code in (201, 409), r.text
    return r.json().get("access_token")


def login(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def make_event(client, token, **payload):
    body = {
        "title": payload["title"],
        "description": payload.get("description", ""),
        "starts_at": "2026-10-15T19:00:00Z",
        "city": payload.get("city", "Москва"),
        "capacity": payload.get("capacity", 5000),
        "category": payload.get("category", "CONCERT"),
    }
    r = client.post("/api/events", json=body, headers=auth(token))
    assert r.status_code in (201, 409), r.text
    return r.json()


def make_resource(client, token, event_id, rtype, name, capacity, **extra):
    body = {
        "event_id": event_id, "type": rtype, "name": name,
        "capacity": capacity, "queue_policy": "FIFO",
    }
    body.update(extra)
    r = client.post("/api/resources", json=body, headers=auth(token))
    assert r.status_code in (201, 409), r.text
    return r.json()


def main():
    with TestClient(app) as client:
        demo_token = register(client, DEMO_EMAIL, DEMO_PASSWORD, "Владислав Демо")
        org_token = register(client, ORG_EMAIL, ORG_PASSWORD, "Прайм Промоушн")
        if demo_token is None and org_token is None:
            # already seeded before — just make sure accounts work
            login(client, DEMO_EMAIL, DEMO_PASSWORD)
            login(client, ORG_EMAIL, ORG_PASSWORD)
            print("Демо-данные уже существуют — вход проверен.")
            return

        client.post("/api/organizers", json={"name": "Прайм Промоушн"},
                    headers=auth(org_token))

        # --- стартовый баланс демо-кошелька (демо-режим оплаты) ---
        client.post("/api/payments/topup", json={"amount": 10000},
                    headers=auth(demo_token))
        client.post("/api/payments/topup", json={"amount": 10000},
                    headers=auth(org_token))

        # --- Событие 1: рок-фестиваль (объект, вокруг которого существует очередь;
        #     приложение НЕ продаёт билеты на фестиваль — ТЗ, раздел 8) ---
        fest = make_event(client, org_token, title="Рок-фестиваль «Волга Fest»",
                          description="Два дня, три сцены, сорок групп. "
                                      "Электронная очередь вместо толпы у входа.",
                          city="Казань", capacity=30000, category="CONCERT")
        queue = make_resource(client, org_token, fest["id"], "EVENT_QUEUE",
                              "Общая очередь на территорию", 30000)
        fanzone = make_resource(client, org_token, fest["id"], "TIME_SLOT",
                                 "Фан-зона у главной сцены (слоты по 2 часа)",
                                 2000, price_base=1200)
        client.post(f"/api/events/{fest['id']}/verify", headers=auth(org_token))

        # --- Событие 2: стендап в баре ---
        standup = make_event(client, org_token, title="Stand-up вечер в «Бар Лофт»",
                             description="Микрофон, стул и полтора часа честного юмора. "
                                         "Бронируйте тайм-слот столика онлайн.",
                             city="Москва", capacity=60, category="SHOW")
        slots = make_resource(client, org_token, standup["id"], "TIME_SLOT",
                              "Столики (слот 20:00–22:00)", 20, price_base=1500)
        make_resource(client, org_token, standup["id"], "WAITLIST",
                      "Лист ожидания на отмены", 100)
        client.post(f"/api/events/{standup['id']}/verify", headers=auth(org_token))

        # --- Событие 3: ресторан с живой очередью ---
        rest = make_event(client, org_token, title="Джазовый вечер — ресторан «Кавказ»",
                          description="Живая очередь на 20 столиков с QR-входом. "
                                      "Никаких бумажных талонов.",
                          city="Санкт-Петербург", capacity=20, category="OTHER")
        make_resource(client, org_token, rest["id"], "PHYSICAL_QUEUE",
                      "Живая очередь (QR-вход)", 20)

        # --- Событие 4: IT-конференция ---
        conf = make_event(client, org_token, title="DevSphere 2026 — IT-конференция",
                          description="Три потока докладов, воркшопы и нетворкинг. "
                                      "Регистрация и слоты переговорок — онлайн.",
                          city="Москва", capacity=1500, category="CONFERENCE")
        make_resource(client, org_token, conf["id"], "EVENT_REGISTRATION",
                      "Регистрация участника", 1500, price_base=0)
        make_resource(client, org_token, conf["id"], "TIME_SLOT",
                      "Воркшопы (слоты по 90 минут)", 300, price_base=2500)

        # --- активность от демо-пользователя ---
        demo_token = demo_token or login(client, DEMO_EMAIL, DEMO_PASSWORD)
        r = client.post(f"/api/queues/resources/{queue['id']}/join", json={},
                        headers=auth(demo_token))
        if r.status_code == 201:
            print("Демо-пользователь встал в очередь на фестиваль:",
                  r.json()["access_right"]["position"])
        r = client.post("/api/reservations", json={"resource_id": slots["id"]},
                        headers=auth(demo_token))
        if r.status_code == 201:
            client.post(f"/api/reservations/{r.json()['id']}/confirm",
                        headers=auth(demo_token))

        # --- другой пользователь продаёт свою позицию — раздел «Предложения» ---
        bot_token = register(client, "bot@access.marketplace", "Bot1234pass!",
                             "Кирилл Перепродажа")
        if bot_token:
            r = client.post(f"/api/queues/resources/{queue['id']}/join", json={},
                            headers=auth(bot_token))
            if r.status_code == 201:
                right = r.json()["access_right"]
                client.post("/api/transfers/listings", json={
                    "access_right_id": right["id"], "price": 2900},
                    headers=auth(bot_token))
                print("Создано предложение о перепродаже позиции за 2900 руб.")

        # --- очередь, созданная обычным пользователем: АЗС (ТЗ, раздел 5) ---
        # источник USER_REQUEST, статус PENDING_VERIFICATION — до проверки
        r = client.post("/api/events", json={
            "title": "АЗС Газпромнефть — Ленинградское шоссе, 25",
            "description": "Живая очередь на заправку: колонки, мойка и магазин. "
                           "Занимайте место удалённо и передавайте его другим.",
            "starts_at": "2026-09-20T08:00:00Z",
            "city": "Москва", "address": "Ленинградское шоссе, 25",
            "capacity": 40, "category": "GAS_STATION",
        }, headers=auth(demo_token))
        if r.status_code == 201:
            gas_event = r.json()
            client.post("/api/resources", json={
                "event_id": gas_event["id"], "type": "PHYSICAL_QUEUE",
                "name": "Очередь на колонки", "capacity": 40,
                "queue_policy": "FIFO",
            }, headers=auth(demo_token))
            print("Создана пользовательская очередь на АЗС (ожидает проверки)")
        elif r.status_code == 409:
            print("Очередь на АЗС уже существует")

        print("Готово. Аккаунты:")
        print(f"  Пользователь: {DEMO_EMAIL} / {DEMO_PASSWORD}")
        print(f"  Организатор:  {ORG_EMAIL} / {ORG_PASSWORD}")


if __name__ == "__main__":
    main()
