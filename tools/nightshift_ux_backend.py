from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "shadow_market_simulator" / "app"


def read(path): return Path(path).read_text(encoding="utf-8")
def write(path, text): Path(path).write_text(text, encoding="utf-8")

def once(path, old, new):
    text = read(path)
    if text.count(old) != 1:
        raise RuntimeError(f"{path}: expected one match for {old[:70]!r}, got {text.count(old)}")
    write(path, text.replace(old, new, 1))

def section(path, start, end, new):
    text = read(path)
    i = text.find(start); j = text.find(end, i + len(start))
    if i < 0 or j < 0:
        raise RuntimeError(f"{path}: section not found {start!r} -> {end!r}")
    write(path, text[:i] + new.rstrip() + "\n\n" + text[j:])

def tail(path, start, new):
    text = read(path)
    i = text.find(start)
    if i < 0: raise RuntimeError(f"{path}: tail marker not found {start!r}")
    write(path, text[:i] + new.rstrip() + "\n")

# Fresh schema: current recruitment transport, immediate disputes, one-time tips.
schema = APP / "schema.sql"
text = read(schema)
text = text.replace(
    "    trait TEXT NOT NULL,\n    phone_level INTEGER NOT NULL DEFAULT 0 CHECK(phone_level BETWEEN 0 AND 2)\n);",
    "    trait TEXT NOT NULL,\n    transport_level INTEGER NOT NULL DEFAULT 0 CHECK(transport_level BETWEEN 0 AND 2),\n    phone_level INTEGER NOT NULL DEFAULT 0 CHECK(phone_level BETWEEN 0 AND 2)\n);",
    1,
)
text = text.replace("    courier_reply_pending TEXT,\n    courier_reply_due_at TEXT,\n", "", 1)
text = text.replace("    car_required INTEGER NOT NULL DEFAULT 0,", "    transport_required INTEGER NOT NULL DEFAULT 0 CHECK(transport_required BETWEEN 0 AND 2),")
marker = "CREATE TABLE procurement_market_state ("
if marker not in text: raise RuntimeError("schema marker missing")
text = text.replace(marker, r'''CREATE TABLE player_tips (
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    shown_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(player_id, code)
);

''' + marker, 1)
write(schema, text)

# Instant explanations: preserve the inheritance boundary, remove delayed state/timers.
write(APP / "delayed_disputes.py", r'''from __future__ import annotations

from .procurement_market import ProcurementMarketGameService, ProcurementMarketSimulationEngine


class DelayedDisputeSimulationEngine(ProcurementMarketSimulationEngine):
    """Current dispute simulation. Employee explanations are immediate."""


class DelayedDisputeGameService(ProcurementMarketGameService):
    """Current dispute service with immediate employee explanations."""
''')

# Recruitment model.
recruitment = APP / "recruitment.py"
text = read(recruitment)
text = text.replace('"courier": "Розничный сотрудник",', '"courier": "Закладчик",')
text = text.replace('"warehouse": "Оптовый сотрудник",', '"warehouse": "Складмен",')
text = text.replace('"car_required", "experience_required",', '"transport_required", "experience_required",')
text = text.replace(
    '                       SET role=?, min_deposit=?, updated_at=CURRENT_TIMESTAMP\n                       WHERE player_id=?""",\n                    (value, default_deposit, player_id),',
    '                       SET role=?, min_deposit=?, transport_required=0, updated_at=CURRENT_TIMESTAMP\n                       WHERE player_id=?""",\n                    (value, default_deposit, player_id),',
)
text = text.replace(
    '        if int(draft["car_required"]):\n            requirement_factor *= 0.58',
    '        transport_required = int(draft["transport_required"])\n        requirement_factor *= {0: 1.0, 1: 0.75, 2: 0.58}.get(transport_required, 1.0)',
)
text = text.replace('                       car_required, experience_required, expected_min, expected_max,', '                       transport_required, experience_required, expected_min, expected_max,')
text = text.replace('                    draft["car_required"], draft["experience_required"],', '                    draft["transport_required"], draft["experience_required"],')
text = text.replace('        car_required = bool(campaign["car_required"])', '        transport_required = int(campaign["transport_required"])')
text = text.replace('            + (0.02 if car_required else 0.0)', '            + (0.02 if transport_required >= 2 else 0.01 if transport_required == 1 else 0.0)')
text = text.replace('        has_car = 1 if car_required else int(self.rng.random() < channel.car_probability)', '        has_car = 1 if transport_required >= 2 else int(self.rng.random() < channel.car_probability)')
write(recruitment, text)

# Courier candidate transport is now explicit and survives hiring.
cr = APP / "courier_recruitment.py"
tail(cr, "    def _create_candidate(", r'''    def _create_candidate(self, conn, player_id: int, campaign, channel, now) -> None:
        if campaign["role"] != "courier":
            super()._create_candidate(conn, player_id, campaign, channel, now)
            return

        min_deposit = int(campaign["min_deposit"])
        transport_required = int(campaign["transport_required"])
        experience_required = bool(campaign["experience_required"])
        deposit_quality_bonus = clamp((min_deposit - 25_000) / 100_000.0 * 0.10, -0.05, 0.08)
        requirement_quality_bonus = (
            (0.02 if transport_required >= 2 else 0.01 if transport_required == 1 else 0.0)
            + (0.05 if experience_required else 0.0)
        )
        quality_bonus = channel.quality_bonus + deposit_quality_bonus + requirement_quality_bonus

        if experience_required:
            experience_level = self.rng.choice([1, 1, 2])
        elif channel.code == "forums":
            experience_level = self.rng.choice([0, 1, 1, 2])
        elif channel.code == "graffiti":
            experience_level = self.rng.choice([0, 0, 1, 1])
        else:
            experience_level = self.rng.choice([0, 0, 0, 1])

        blueprint = generate_courier_blueprint(self.rng, quality_bonus=quality_bonus, experience_level=experience_level)
        alias = self.rng.choice(["Гриф", "Луна", "Рысь", "Штрих", "Кедр", "Ноль", "Фаза", "Север", "Ток", "Сова", "Мята"]) + str(self.rng.randint(10, 99))

        if transport_required >= 2:
            transport_level = 2
        elif transport_required == 1:
            transport_level = 2 if self.rng.random() < channel.car_probability else 1
        else:
            roll = self.rng.random()
            if roll < channel.car_probability:
                transport_level = 2
            elif roll < min(0.92, channel.car_probability + 0.42):
                transport_level = 1
            else:
                transport_level = 0
        has_car = int(transport_level == 2)

        phone_roll = self.rng.random()
        if experience_level >= 2:
            phone_level = 0 if phone_roll < 0.15 else 1 if phone_roll < 0.78 else 2
        elif experience_level == 1:
            phone_level = 0 if phone_roll < 0.35 else 1 if phone_roll < 0.90 else 2
        else:
            phone_level = 0 if phone_roll < 0.55 else 1 if phone_roll < 0.95 else 2

        deposit_pool = (5_000, 10_000, 15_000, 25_000, 40_000, 60_000, 90_000, 100_000)
        available = [value for value in deposit_pool if value >= min_deposit]
        deposit = self.rng.choice(available) if available else min(100_000, max(min_deposit, 25_000))
        starting_loyalty = clamp(self.rng.uniform(0.48, 0.66) + experience_level * 0.015 + quality_bonus * 0.15, 0.38, 0.78)

        cur = conn.execute(
            """INSERT INTO candidates(
                   player_id, alias, role, deposit, has_car, reliability, attention, honesty,
                   loyalty, expires_at, campaign_id, source_channel, min_deposit, experience_level
               ) VALUES (?, ?, 'courier', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (player_id, alias, deposit, has_car, blueprint.pace, blueprint.precision, blueprint.integrity,
             starting_loyalty, iso(now + timedelta(hours=10 / self.effective_speed(player_id))),
             campaign["id"], channel.code, min_deposit, experience_level),
        )
        candidate_id = int(cur.lastrowid)
        conn.execute(
            """INSERT INTO courier_candidate_profiles(
                   candidate_id, pace, precision, resilience, integrity, trait, transport_level, phone_level
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (candidate_id, blueprint.pace, blueprint.precision, blueprint.resilience, blueprint.integrity,
             blueprint.trait, transport_level, phone_level),
        )''')

cm = APP / "courier_management.py"
text = read(cm)
text = text.replace('1: ("самокат", 25_000, 0.08)', '1: ("велосипед", 25_000, 0.08)')
text = text.replace('"SELECT phone_level FROM courier_candidate_profiles WHERE candidate_id=?"', '"SELECT transport_level, phone_level FROM courier_candidate_profiles WHERE candidate_id=?"')
text = text.replace('                    2 if int(candidate["has_car"]) else 0,\n                    int(profile["phone_level"]) if profile else 0,', '                    int(profile["transport_level"]) if profile else (2 if int(candidate["has_car"]) else 0),\n                    int(profile["phone_level"]) if profile else 0,')
text = text.replace('return "🔴", "на пределе"', 'return "🔴", "перегружен"')
text = text.replace('return "🟢", "в порядке"', 'return "🟢", "в норме"')
write(cm, text)

# Purchase result and current terminology.
pm = APP / "procurement_market.py"
text = read(pm)
text = text.replace("Оптовый сотрудник больше недоступен.", "Складмен больше недоступен.")
text = text.replace("f\"Приём партии {offer['product_title']}\"", "f\"Получение партии {offer['product_title']}\"")
old = r'''        return (
            f"Партия куплена за <b>{total:,} ₽</b>.\n\n"
            f"Ответственный: <b>{employee['alias']}</b>\n"
            "Статус: получает партию\n"
            "Оплата будет начислена после успешной передачи товара рознице."
            f"{risk}"
        )'''
new = r'''        return (
            f"✅ Куплено: {offer['product_title']} · {offer['quantity']} ед. за <b>{total:,} ₽</b>.\n\n"
            f"Складмен {employee['alias']} получает партию.\n"
            "После получения её можно будет передать закладчикам.\n"
            "Оплата складмену будет начислена после успешной передачи товара."
            f"{risk}"
        )'''
if old not in text: raise RuntimeError("procurement success block missing")
write(pm, text.replace(old, new, 1))

wf = APP / "workflow.py"
text = read(wf)
for old, new in {
    "Оптовый сотрудник больше недоступен.": "Складмен больше недоступен.",
    "Розничный сотрудник недоступен.": "Закладчик недоступен.",
    "Статус: принимает партию": "Статус: получает партию",
    "Оплата за работу будет начислена после передачи товара рознице.": "Оплата за работу будет начислена после передачи товара закладчику.",
    "После получения у сотрудника": "После получения у закладчика",
    "автоматически начнёт подготовку позиций": "автоматически начнёт подготовку товара к витрине",
    'role_title = "оптовый" if new_role == "warehouse" else "розничный"': 'role_title = "складмен" if new_role == "warehouse" else "закладчик"',
}.items(): text = text.replace(old, new)
write(wf, text)

game = APP / "game.py"
text = read(game).replace('"courier": "Розничный сотрудник",', '"courier": "Закладчик",').replace('"warehouse": "Оптовый сотрудник",', '"warehouse": "Складмен",')
write(game, text)

# Bicycle terminology everywhere in NIGHTSHIFT source/docs/tests.
for path in (ROOT / "shadow_market_simulator").rglob("*"):
    if path.suffix in {".py", ".md"}:
        value = read(path)
        updated = value.replace("самокат", "велосипед").replace("Самокат", "Велосипед")
        if updated != value: write(path, updated)

print("backend UX transform ok")
