# NIGHTSHIFT: состояние архитектуры v2

Архитектура v2 завершена и находится в `main`. Этот файл фиксирует фактическое состояние проекта после структурного рефакторинга.

## Канонические пакеты

Реальная реализация находится в feature-пакетах:

- `app/core/` — конфигурация, database/schema boundary и базовый `GameService`;
- `app/engine/` — базовая симуляция, персональное игровое время и таймеры;
- `app/commerce/` — inventory/operations, workflow, procurement и packaging;
- `app/staff/` — recruitment, compensation, relationships, insights и idle-семантика;
- `app/staff/couriers/` — courier model, recruitment, core simulation и management;
- `app/trust/` — customer trust/rating behavior;
- `app/disputes/` — dispute payment behavior;
- `app/analytics/` — event logging, business analytics и analytics handlers;
- `app/inbox/` — lifecycle входящих сообщений;
- `app/bot/` — Telegram middleware и notification runtime;
- `app/tutorial/` — onboarding state/flow и гарантии первого цикла.

Старые root compatibility-facades удалены. Production-код и тесты используют канонические package-paths напрямую.

## Корень `app/`

В корне остаются только assembly/UI-модули:

- `main.py`;
- `bootstrap.py`;
- `ui_admin.py`;
- `ui_commerce.py`;
- `ui_common.py`;
- `ui_disputes.py`;
- `ui_navigation.py`;
- `ui_staff.py`;
- `ui_staff_handlers.py`;
- `__init__.py`.

Архитектурный guardrail запрещает расширять этот список доменными модулями.

## Runtime assembly

`app/main.py` — минимальная точка входа. Сборка приложения выполняется в `app/bootstrap.py`. Фоновая обработка уведомлений находится в `app/bot/notifications.py`.

Bootstrap использует только канонические package-imports.

## Runtime overlays

Runtime overlay debt: **0**.

Полностью удалены:

- `release_fixes.py`;
- `handoff_copy_update.py`;
- `product_ui_update.py`;
- `gameplay_updates.py`;
- старый `tutorial.py` как runtime installer;
- `tutorial_runtime.py`;
- `tutorial_copy_update.py`.

`LEGACY_OVERLAY_MODULES` пуст.

Tutorial находится в `app/tutorial/`; bootstrap только явно включает tutorial capability для production `Database`. Методы и renderer'ы при старте приложения не подменяются.

## Compatibility layer

Временный root compatibility-слой удалён полностью. Старые внутренние import-paths намеренно не поддерживаются.

Повторное появление facade-файлов должно рассматриваться как архитектурная регрессия, а не как допустимый способ совместимости.

## Наследование

Существующая cooperative MRO-цепочка `SimulationEngine` / `GameService` ещё присутствует в активной реализации, но заморожена guardrail-тестом. Её можно сокращать; новые feature-слои поверх неё добавлять нельзя без отдельного архитектурного обоснования.

Новые механики должны предпочитать feature services, композицию и lifecycle hooks.

## Проверка

Финальное состояние architecture v2 прошло NIGHTSHIFT CI:

- Python compile check;
- полный pytest suite;
- ruff import/name checks;
- fresh SQLite database + UI smoke;
- stale contract/documentation audit;
- architecture guardrails.

## Статус

Структурная миграция завершена. Отдельного архитектурного migration backlog больше нет.

Дальнейшие изменения должны развивать канонические feature-пакеты напрямую и не возвращать root facades, runtime overlays или новый inheritance-layer на каждую механику.
