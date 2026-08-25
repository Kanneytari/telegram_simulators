# Telegram Simulators

Репозиторий независимых текстовых игр-симуляторов для Telegram. Каждая игра находится в собственной папке, имеет свой entrypoint, конфигурацию, SQLite-базу и тесты.

## Игры

- `career_simulator/` — карьерный симулятор «Карьерист».
- `wasteland_rpg/` — постапокалиптическая RPG «Контур».
- `wasteland_settlement_strategy/` — draft стратегии про управление Приютом-7; одновременно reference-сценарий для будущего `simulation_engine`.
- `shadow_market_simulator/` — асинхронный экономический симулятор NIGHTSHIFT.

Инструкции по запуску и устройство конкретной игры находятся в её `README.md`.

## Общий стек

- Python 3.12+
- aiogram 3.x
- SQLite3
- python-dotenv
- pytest

Игры не используют общую БД и не зависят друг от друга во время выполнения. Экспериментальные draft-проекты могут начинаться с headless runtime и подключать Telegram/SQLite после проверки базового игрового цикла.

## Структура

```text
telegram_simulators/
├── career_simulator/
├── wasteland_rpg/
├── wasteland_settlement_strategy/
├── shadow_market_simulator/
└── docs/
    └── PROJECT_RULES.md
```

Общие правила репозитория описаны в `docs/PROJECT_RULES.md`. Архитектура и игровые механики NIGHTSHIFT документируются отдельно внутри `shadow_market_simulator/docs/`.
