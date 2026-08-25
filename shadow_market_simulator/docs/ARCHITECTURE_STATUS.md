# NIGHTSHIFT architecture refactor status

This file records the concrete state of the architecture-v2 migration. `ARCHITECTURE.md` remains the design direction; this file describes what is already canonical and what is intentionally transitional.

## Canonical packages

The following packages now own the real implementation:

- `app/core/` — configuration, database/schema boundary and base `GameService`;
- `app/engine/` — base simulation, per-player time semantics and timer scaling;
- `app/commerce/` — inventory/operations, workflow, procurement and packaging;
- `app/staff/` — recruitment, compensation, relationships, insights, idle semantics and employee helpers;
- `app/staff/couriers/` — courier model, recruitment, core simulation and management;
- `app/trust/` — customer trust/rating behavior;
- `app/disputes/` — dispute payment behavior;
- `app/analytics/` — event logging, business analytics and analytics handlers;
- `app/inbox/` — inbox lifecycle;
- `app/bot/` — Telegram middleware and notification runtime.

Legacy root compatibility facades have been removed. Production code and tests import canonical package paths directly.

## Runtime assembly

`app/main.py` is a thin entry point. Application construction lives in `app/bootstrap.py`; notification processing is separated into `app/bot/notifications.py`.

The production bootstrap already uses canonical package imports for the migrated core domains, including analytics and courier management.

## Simulation and service inheritance

The existing cooperative `SimulationEngine` / `GameService` inheritance staircase is frozen by `tests/test_architecture_guardrails.py`. Existing layers may be reduced or relocated, but new mechanics must not add another terminal inheritance layer.

Base simulation now lives in `app/engine/simulation.py`. Internal feature bridges point to that canonical module instead of round-tripping through the legacy root `app.simulation` facade.

## Runtime overlays

Runtime overlay debt is now zero.

Removed completely:

- `release_fixes.py`;
- `handoff_copy_update.py`;
- `product_ui_update.py`;
- `gameplay_updates.py`;
- `tutorial.py` as a runtime installer;
- `tutorial_runtime.py`;
- `tutorial_copy_update.py`.

Onboarding now lives in `app/tutorial/`. Tutorial state and flow are in `core.py`; cross-cutting first-cycle behavior is attached explicitly through static decorators in `hooks.py`. `app/bootstrap.py` does not install or mutate tutorial behavior at runtime.

No runtime overlay module is allowed by the architecture guardrail.

## Compatibility policy

The temporary root compatibility layer has been removed. Old import paths are intentionally unsupported inside this application; architecture guardrails prevent those facade modules from returning.

## Validation policy

Every migration checkpoint is validated by the NIGHTSHIFT CI workflow:

- Python compile check;
- full pytest suite;
- unused/import checks with ruff;
- fresh database and UI smoke test;
- stale contract/documentation audit.

The refactor is considered safe only when all of these checks are green on the current branch head.

## Remaining work

The architecture-v2 structural migration is complete for the active runtime. Future changes should extend the canonical feature packages directly rather than recreating root facades, runtime overlays, or one-class-per-feature inheritance layers.
