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

Large legacy files in the root of `app/` that correspond to these domains are compatibility facades. New production code must import the canonical package path, not add behavior to those facades.

## Runtime assembly

`app/main.py` is a thin entry point. Application construction lives in `app/bootstrap.py`; notification processing is separated into `app/bot/notifications.py`.

The production bootstrap already uses canonical package imports for the migrated core domains, including analytics and courier management.

## Simulation and service inheritance

The existing cooperative `SimulationEngine` / `GameService` inheritance staircase is frozen by `tests/test_architecture_guardrails.py`. Existing layers may be reduced or relocated, but new mechanics must not add another terminal inheritance layer.

Base simulation now lives in `app/engine/simulation.py`. Internal feature bridges point to that canonical module instead of round-tripping through the legacy root `app.simulation` facade.

## Runtime overlays

The old release/update overlay layer has been reduced substantially:

Removed completely:

- `release_fixes.py`;
- `handoff_copy_update.py`;
- `product_ui_update.py`.

`gameplay_updates.py` no longer owns commerce UI behavior. Its remaining runtime responsibility is limited to the final batch renderer / handoff presentation compatibility path and the associated handoff task copy. This is intentionally retained until it can be removed without rewriting the large staff router through an unsafe whole-file API replacement.

Tutorial overlays (`tutorial.py`, `tutorial_runtime.py`, `tutorial_copy_update.py`) remain the largest migration debt. They combine onboarding state, first-run protection, copy and UI guidance. They should be migrated as one isolated follow-up rather than partially rewritten during an otherwise behavior-preserving architecture change.

No new overlay module is allowed by the architecture guardrail; the exact legacy set can only shrink.

## Compatibility policy

Legacy import paths are kept only where existing tests or external code can still depend on them. Compatibility tests assert object identity between old and canonical imports for migrated domains.

A compatibility facade must not become a second source of business behavior. New code goes directly into feature packages.

## Validation policy

Every migration checkpoint is validated by the NIGHTSHIFT CI workflow:

- Python compile check;
- full pytest suite;
- unused/import checks with ruff;
- fresh database and UI smoke test;
- stale contract/documentation audit.

The refactor is considered safe only when all of these checks are green on the current branch head.

## Remaining work

Before declaring architecture-v2 migration complete:

1. keep the branch green while finalizing documentation and compatibility boundaries;
2. migrate/remove the tutorial overlay as a dedicated follow-up block;
3. remove the last `gameplay_updates.py` presentation hook when the staff UI router can be edited safely and covered by direct renderer regression tests;
4. remove compatibility facades only after no production/tests depend on their legacy paths.

These remaining items are architecture cleanup, not new gameplay mechanics.
