from __future__ import annotations

from .actions import AdvanceDay, StartExpedition, UpgradeBuilding
from .prototype_runtime import ManualClock, PrototypeEngine
from .scenario import bootstrap_state, make_demo_clock, settlement_scenario
from .views import residents_view, settlement_dashboard


def main() -> None:
    clock = ManualClock(make_demo_clock())
    engine = PrototypeEngine(
        scenario=settlement_scenario,
        state=bootstrap_state(),
        clock=clock,
        seed=7,
    )

    print(settlement_dashboard(engine.state))
    print("\n--- Отправляем Грача и Лиса в Ржавый пояс ---")
    print(
        engine.execute(
            StartExpedition("rust_belt", ("rook", "fox")),
            idempotency_key="demo:expedition:1",
        )
    )

    print("\n--- Параллельно улучшаем наблюдательную вышку ---")
    print(engine.execute(UpgradeBuilding("watchtower"), idempotency_key="demo:watchtower:1"))

    clock.advance(minutes=25)
    engine.run_due()
    print("\n--- После возвращения отряда ---")
    print(settlement_dashboard(engine.state))
    print(residents_view(engine.state))

    print("\n--- Следующий игровой день ---")
    print(engine.execute(AdvanceDay(), idempotency_key="demo:day:2"))
    print(settlement_dashboard(engine.state))


if __name__ == "__main__":
    main()
