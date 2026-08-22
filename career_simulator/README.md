# Карьерист

Telegram-симулятор карьеры. Игрок начинает стажёром и растёт за счёт реального навыка, репутации, заметности и связей, одновременно управляя стрессом и дедлайнами.

## Стек

- Python 3.12+
- aiogram 3
- SQLite (`sqlite3`, без ORM)
- python-dotenv

LLM в базовую версию не встроена: основной игровой цикл должен быть дешёвым, детерминированным и тестируемым. Позже LLM можно добавить для редких сюжетных событий, не связывая с ней игровую экономику.

## Запуск

```bash
cd career_simulator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

В `.env` нужно указать токен от BotFather:

```text
BOT_TOKEN=...
```

Запуск:

```bash
python3 -m app.main
```

## Тесты

```bash
python3 -m unittest discover -s tests -v
```

## Структура

```text
career_simulator/
├── app/
│   ├── config.py       # конфигурация
│   ├── content.py      # ранги, события, проекты, покупки
│   ├── db.py           # схема SQLite
│   ├── game.py         # игровая логика
│   ├── handlers.py     # Telegram-хендлеры
│   ├── keyboards.py    # inline-кнопки
│   └── main.py         # точка входа
├── docs/
│   ├── GAME_DESIGN.md
│   └── DATA_MODEL.md
└── tests/
```

Главное правило архитектуры: Telegram ничего не решает сам. Хендлеры только принимают нажатия и вызывают `GameService`; баланс и правила находятся в игровом слое.
