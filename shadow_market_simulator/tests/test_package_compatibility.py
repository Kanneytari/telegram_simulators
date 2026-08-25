from app.config import Settings as LegacySettings
from app.courier_idle import courier_idle_ready as legacy_courier_idle_ready
from app.courier_model import CourierBlueprint as LegacyCourierBlueprint
from app.db import Database as LegacyDatabase
from app.employee_rename import rename_employee as legacy_rename_employee
from app.global_packaging import GlobalPackagingGameService as LegacyPackagingService
from app.staff_idle import IdleAwareGameService as LegacyIdleAwareGameService
from app.commerce.packaging import GlobalPackagingGameService
from app.core.config import Settings
from app.core.database import Database
from app.staff.couriers.idle import courier_idle_ready
from app.staff.couriers.model import CourierBlueprint
from app.staff.idle import IdleAwareMixin
from app.staff.rename import rename_employee


def test_legacy_imports_are_thin_aliases_to_canonical_packages() -> None:
    assert LegacySettings is Settings
    assert LegacyDatabase is Database
    assert LegacyCourierBlueprint is CourierBlueprint
    assert legacy_courier_idle_ready is courier_idle_ready
    assert legacy_rename_employee is rename_employee
    assert LegacyIdleAwareGameService is IdleAwareMixin
    assert LegacyPackagingService is GlobalPackagingGameService
