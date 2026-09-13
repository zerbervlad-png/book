# Архитектура

## Соответствие разделам ТЗ

| Раздел ТЗ | Реализация |
|---|---|
| 2. Базовый процесс | `app/engines/*` — конвейер Availability → Reservation → Ownership → Transfer → Payment → Verification → CheckIn |
| 3. Типы ресурсов | `ResourceType` (PHYSICAL_QUEUE, EVENT_QUEUE, EVENT_REGISTRATION, WAITLIST, TIME_SLOT, TICKET, ACCESS_PASS) |
| 4–7. Event + верификация | `models/entities.Event`, `engines/verification.py` (Event Verification Engine) |
| 8–9. Очередь до начала, QueuePosition | `engines/queue_engine.py`, `AccessRight(kind=QUEUE_POSITION)` с позицией |
| 10. GPS не доказательство | `engines/fraud.record_gps_telemetry` — auxiliary-only; тест `test_gps_is_never_proof_of_queue_position` |
| 11–12. Токены | `AccessRight.token_code` (AT-…), one-time secret, `/access/{id}/qr`, `/access/{id}/code` |
| 13. Double spending | частичный уникальный индекс `uq_open_transfer_per_right` + пересоздание токена при передаче |
| 14–16. Передачи | `engines/transfer.py`: TRANSFER (gift) и RESALE — разные операции |
| 17. Waitlist | `engines/waitlist.py`: offer window → confirm → следующему |
| 18. Политики очереди | FIFO / RANDOMIZED / LOTTERY / PRIORITY / INVITE_ONLY / HYBRID |
| 19–22. Marketplace / discovery / карточка | `api/marketplace.py`, `api/events.py` |
| 23–24. Organizer + Rule Engine | `api/organizers.py`, `Resource` access-политики (раздел 55) |
| 25–27. Ownership / Reservation / Payment | `engines/reservation.py`, `engines/payment.py` (escrow ledger, provider-абстракция для PSP) |
| 28. Disputes | `api/disputes.py` |
| 29. Check-in | `engines/checkin.py`: QR/barcode/token/code/manual/API; результаты VALID/USED/EXPIRED/CANCELLED/INVALID/TRANSFERRED |
| 31. Антифрод | `engines/fraud.py` |
| 32–33. Audit | `engines/audit.py`, append-only `audit_events` |
| 35–36. Поиск, timezone | фильтры `api/events.search_events`, `Event.timezone_name`; naive-UTC конвенция |
| 38. API | роутеры по списку ТЗ |
| 39–40. Resource Adapter | новые типы = новый `ResourceType` + `kind`; core-логика не дублируется |
| 41–43. iOS | SwiftUI + MVVM + единый networking/auth, offline-деградация |
| 44. Notifications | таблица `notifications` + API |
| 46. User Journeys A–E | покрыты E2E-тестами |
| 47. MVP | Physical Queue, Event, Event Queue, Waitlist, Position, Transfer, Payment, Verification, QR, Check-in |
| 52. Inventory | `compute_event_inventory` — все значения считаются backend |
| 53–54. Статусы | enum `EventStatus`, `AccessRightStatus` |
| 56–58. Политики передачи | `is_transferable`, `is_resellable`, `max_resale_price`, `fee_percent`, approval |
| 59. Аналитика | `api/analytics.py` |
| 60–61. Безопасность, идемпотентность | JWT, PBKDF2, rate limit, `IdempotencyRecord` + `idempotency_key` |
| 62–65. Тесты | 20 тестов: E2E 1–5, негативные, GPS-кейсы, политики очередей |
| 67. Без mock | все критические операции — реальные server-side механизмы |
| 68–70. Источники, дедупликация | `EventSource`, `canonical_key` |
| 72–73. B2B, монетизация | роли organizer/admin, конфигурируемые комиссии |
| 78–79. Динамический UX | iOS строит UI из `resource.type` + политик ресурса |
| 83–90. Принципы | ядро — Access, не Queue; расширение через новые типы, без переписывания core |

## Payment Provider

`engines/payment.py` — реальный escrow-ledger (авторизация → захват → возврат) с
провайдерской абстракцией. Подключение внешнего PSP (Stripe/ЮKassa) — реализация
интерфейса authorize/capture/refund с пробросом webhook; бизнес-логика transfer
не меняется (раздел 71).

## Известные ограничения MVP

- SQLite + naive-UTC (для PostgreSQL нужен timezone-адаптер)
- Сборщики TTL (reservation/waitlist/transfer expiry) — ленивые, вызываются при
  запросах; в продакшене вынести в фоновый шедулер
- iOS-клиент собирается на macOS/Xcode (на этой Windows-машине верификация
  компиляцией невозможна)
