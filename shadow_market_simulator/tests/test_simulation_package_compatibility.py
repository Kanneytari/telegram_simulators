from app.engine.simulation import (
    CLIENT_ALIASES,
    PRODUCTS,
    SUPPLIERS,
    SimulationEngine,
    TickResult,
    clamp,
    iso,
    parse_dt,
    utcnow,
)
from app.simulation import CLIENT_ALIASES as LegacyClientAliases
from app.simulation import PRODUCTS as LegacyProducts
from app.simulation import SUPPLIERS as LegacySuppliers
from app.simulation import SimulationEngine as LegacySimulationEngine
from app.simulation import TickResult as LegacyTickResult
from app.simulation import clamp as legacy_clamp
from app.simulation import iso as legacy_iso
from app.simulation import parse_dt as legacy_parse_dt
from app.simulation import utcnow as legacy_utcnow


def test_simulation_legacy_module_is_a_thin_facade() -> None:
    assert LegacySimulationEngine is SimulationEngine
    assert LegacyTickResult is TickResult
    assert LegacyProducts is PRODUCTS
    assert LegacySuppliers is SUPPLIERS
    assert LegacyClientAliases is CLIENT_ALIASES
    assert legacy_clamp is clamp
    assert legacy_iso is iso
    assert legacy_parse_dt is parse_dt
    assert legacy_utcnow is utcnow
