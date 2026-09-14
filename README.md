# Universal Access & Reservation Marketplace

Реализация единого технического задания «Universal Access, Reservation, Queue & Event
Marketplace»: платформа ограниченного права доступа, где **очередь — лишь один из Access
Models** (разделы 1, 74, 80, 87 ТЗ), доработанная до **маркетплейса мест в очередях**:
пользователь может найти/создать очередь, занять место, передать или продать его
другому пользователю с escrow-расчётом и комиссией сервиса.

```
RESOURCE → EVENT/CONTEXT → ACCESS → AVAILABILITY → RESERVATION → OWNERSHIP
         → TRANSFER → PAYMENT → VERIFICATION → CHECK-IN/ACCESS
```

## Состав

| Папка | Что это |
|---|---|
| `backend/` | FastAPI + SQLAlchemy. Полная доменная модель ТЗ (раздел 76), движки, API (раздел 38), тесты (разделы 62–65) |
| `ios/` | SwiftUI-клиент: MVVM, async/await, единый networking/auth layer, динамический UX (разделы 41–43, 78–79) |
| `docs/` | Архитектурная документация |
| `setup.sh` | One-command macOS setup: backend + Xcode-проект + запуск |

## Быстрый старт на Mac (одна команда)

```bash
git clone https://github.com/zerbervlad-png/book.git && cd book && bash setup.sh
```

Скрипт сам: поставит Homebrew/XcodeGen (если нет), создаст venv бэкенда,
определит IP Mac и пропишет его в iOS-приложение, запустит бэкенд в отдельном
окне Terminal, сгенерирует `AccessMarketplace.xcodeproj` и откроет его в Xcode.
Дальше в Xcode: выбрать **iPhone 15 Pro Max** (симулятор) или своё устройство → ⌘R.
Для реального iPhone: тот же Wi-Fi, что у Mac, и включённый Developer Mode.

## Ключевые архитектурные решения (по ТЗ)

- **AccessRight** — универсальный цифровой токен (`AT-xxxxxxxxx`, разделы 9, 12, 50):
  позиция в очереди, билет, слот, waitlist-приоритет и access pass — это AccessRight
  разного `kind`. Один конвейер Ownership/Transfer/Payment/CheckIn для всех типов (39, 40).
- **GPS ≠ Proof of Queue Position** (раздел 10): телеметрия хранится только как
  auxiliary-сигнал и не влияет на членство в очереди.
- **Защита от double spending** (раздел 13): частичный уникальный индекс в БД гарантирует
  не более одного открытого Transfer на право; при передаче выпускается новый токен,
  старый инвалидируется.
- **Идемпотентность** (раздел 61): `idempotency_key` на платежах и transfer.
- **Event Verification Engine** (раздел 7): отдельный модуль проверки мероприятий,
  canonical key для дедупликации (69–70).
- **Queue Engine** (раздел 18): FIFO, RANDOMIZED, LOTTERY, PRIORITY, INVITE_ONLY, HYBRID.
- **Backend — единственный источник истины** (раздел 42): iOS не принимает
  критических решений локально.
- **Audit log** (разделы 32–33): append-only журнал всех значимых операций.

## Backend

### Запуск

```bash
cd backend
pip install fastapi "uvicorn[standard]" sqlalchemy pydantic pyjwt qrcode pillow email-validator pytest httpx
uvicorn app.main:app --reload
# Swagger: http://localhost:8000/docs
```

Админ-аккаунт создаётся при старте: `admin@access.marketplace` / `ChangeMe-Admin-2026!`
(смените в продакшене).

### Тесты

```bash
cd backend
python -m pytest tests -q
```

20 тестов, включая обязательные E2E (раздел 63) и негативные сценарии (раздел 64):
duplicate transfer/payment, expired reservation/token, cancelled event, invalid/reused
QR, simultaneous purchase/transfer, GPS-spoof, offline-поведение клиента.

### API (раздел 38)

`/api/auth` · `/users` · `/organizers` · `/events` (+verify/cancel/inventory) ·
`/resources` (+availability) · `/queues` · `/waitlists` · `/access` (+qr/code) ·
`/reservations` · `/transfers` (+listings/buy/gift/pay/approve) · `/payments` ·
`/checkins` · `/disputes` · `/marketplace` · `/notifications` · `/analytics` · `/health`

### Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `AM_DATABASE_URL` | `sqlite:///./access_marketplace.db` | строка подключения SQLAlchemy |
| `AM_JWT_SECRET` | dev-значение | секрет JWT (обязательно задайте в production — фиксированный, иначе токены слетают при рестарте) |
| `AM_ADMIN_EMAIL` / `AM_ADMIN_PASSWORD` | `admin@access.marketplace` / `ChangeMe-Admin-2026!` | учётка bootstrap-админа (всегда переопределяйте в production) |
| `AM_CORS_ORIGINS` | `*` | разрешённые CORS-источники через запятую; при `*` credentials отключены |
| `AM_RESERVATION_TTL` | 900 | TTL резерва, сек |
| `AM_WAITLIST_OFFER_TTL` | 1800 | окно подтверждения waitlist-оффера |
| `AM_PLATFORM_FEE` | 5 | комиссия платформы, % |

**Конвенция времени**: все timestamp хранятся как naive-UTC (SQLite теряет tzinfo).
Для PostgreSQL добавьте фиксированный timezone-адаптер.

## iOS

Требования: Xcode 15+, iOS 17. Откройте новый проект iOS App `AccessMarketplace`,
добавьте все `.swift` из `ios/AccessMarketplace/`, укажите `NSCameraUsageDescription`
(сканер QR) и, опционально, `NSLocationWhenInUseUsageDescription` (GPS — только
auxiliary, раздел 10). `APIClient.baseURL` направьте на развёрнутый backend.

Отвечает Apple-требованиям: Dynamic Type, Dark Mode, safe areas, accessibility
(раздел 66). Сборка возможна только на macOS/Xcode.

## Демо-сценарий (раздел 15)

```
10:00  User A вступает в очередь на Concert X → позиция #148 (AccessRight AT-…)
12:00  User A выставляет позицию на marketplace (цена + комиссия видны покупателю)
13:15  User B покупает: блокировка → PAYMENT → VERIFICATION → TOKEN LOCK
13:16  Позиция #148 → User B; токен A инвалидирован, B получил новый
18:00  User B приходит на мероприятие
18:05  QR check-in (одноразовый код)
20:00  Event
```

## Сделка «продавец → покупатель» (доработка)

```
Продавец:  Моё место → «Передать место» → Продать (цена) / Даром → Выставить
Покупатель: Маркет → «Передают и продают» → карточка места (цена, комиссия,
            окно сделки) → «Купить место» → подтверждение → расчёт (escrow)
            → место закрепляется за покупателем, новый токен в «Мой доступ»
Отмена:    любой участник до завершения → автоматический refund;
           истечение окна сделки (TTL) → блокировка снимается, место возвращается
```

Комиссия настраивается: `AM_PLATFORM_FEE` (по умолчанию 5 %) и `fee_percent`
на уровне ресурса. Обоснование выбора модели — `docs/monetization.md`.
