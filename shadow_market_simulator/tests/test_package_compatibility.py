from app.commerce.inventory import OperationsGameService, OperationsSimulationEngine
from app.commerce.packaging import GlobalPackagingGameService
from app.commerce.procurement import (
    MINIMUM_BATCH_SIZE,
    PROCUREMENT_BATCH_SIZES,
    ROTATION_MINUTES,
    VOLUME_DISCOUNTS,
    ProcurementMarketGameService,
    ProcurementMarketSimulationEngine,
)
from app.commerce.workflow import TASK_LABELS, WorkflowGameService, WorkflowSimulationEngine
from app.config import Settings as LegacySettings
from app.core.config import Settings
from app.core.database import Database
from app.courier_idle import courier_idle_ready as legacy_courier_idle_ready
from app.courier_model import CourierBlueprint as LegacyCourierBlueprint
from app.courier_recruitment import CourierRecruitmentService as LegacyCourierRecruitmentService
from app.db import Database as LegacyDatabase
from app.dispute_payments import DisputePaymentMixin as LegacyDisputePaymentMixin
from app.disputes.payments import DisputePaymentMixin
from app.employee_rename import rename_employee as legacy_rename_employee
from app.engine import NightshiftSimulationMixin, PlayerSimulationMixin
from app.global_packaging import GlobalPackagingGameService as LegacyPackagingService
from app.inbox.lifecycle import install_inbox_lifecycle
from app.inbox_lifecycle import install_inbox_lifecycle as legacy_install_inbox_lifecycle
from app.nightshift import NightshiftSimulationMixin as LegacyNightshiftSimulationMixin
from app.operations import OperationsGameService as LegacyOperationsGameService
from app.operations import OperationsSimulationEngine as LegacyOperationsSimulationEngine
from app.procurement_market import MINIMUM_BATCH_SIZE as LegacyMinimumBatchSize
from app.procurement_market import PROCUREMENT_BATCH_SIZES as LegacyProcurementBatchSizes
from app.procurement_market import ROTATION_MINUTES as LegacyRotationMinutes
from app.procurement_market import VOLUME_DISCOUNTS as LegacyVolumeDiscounts
from app.procurement_market import ProcurementMarketGameService as LegacyProcurementMarketGameService
from app.procurement_market import ProcurementMarketSimulationEngine as LegacyProcurementMarketSimulationEngine
from app.runtime import PlayerSimulationMixin as LegacyPlayerSimulationMixin
from app.staff.couriers.idle import courier_idle_ready
from app.staff.couriers.model import CourierBlueprint
from app.staff.couriers.recruitment import CourierRecruitmentService
from app.staff.idle import IdleAwareMixin
from app.staff.insights import StaffInsightGameService, StaffInsightSimulationEngine
from app.staff.rename import rename_employee
from app.staff_idle import IdleAwareGameService as LegacyIdleAwareGameService
from app.staff_insights import StaffInsightGameService as LegacyStaffInsightGameService
from app.staff_insights import StaffInsightSimulationEngine as LegacyStaffInsightSimulationEngine
from app.workflow import TASK_LABELS as LegacyTaskLabels
from app.workflow import WorkflowGameService as LegacyWorkflowGameService
from app.workflow import WorkflowSimulationEngine as LegacyWorkflowSimulationEngine


def test_legacy_imports_are_thin_aliases_to_canonical_packages() -> None:
    assert LegacySettings is Settings
    assert LegacyDatabase is Database
    assert LegacyCourierBlueprint is CourierBlueprint
    assert legacy_courier_idle_ready is courier_idle_ready
    assert legacy_rename_employee is rename_employee
    assert LegacyIdleAwareGameService is IdleAwareMixin
    assert LegacyPackagingService is GlobalPackagingGameService
    assert LegacyDisputePaymentMixin is DisputePaymentMixin
    assert legacy_install_inbox_lifecycle is install_inbox_lifecycle
    assert LegacyCourierRecruitmentService is CourierRecruitmentService
    assert LegacyNightshiftSimulationMixin is NightshiftSimulationMixin
    assert LegacyPlayerSimulationMixin is PlayerSimulationMixin
    assert LegacyOperationsGameService is OperationsGameService
    assert LegacyOperationsSimulationEngine is OperationsSimulationEngine
    assert LegacyWorkflowGameService is WorkflowGameService
    assert LegacyWorkflowSimulationEngine is WorkflowSimulationEngine
    assert LegacyTaskLabels is TASK_LABELS
    assert LegacyStaffInsightGameService is StaffInsightGameService
    assert LegacyStaffInsightSimulationEngine is StaffInsightSimulationEngine
    assert LegacyProcurementMarketGameService is ProcurementMarketGameService
    assert LegacyProcurementMarketSimulationEngine is ProcurementMarketSimulationEngine
    assert LegacyProcurementBatchSizes is PROCUREMENT_BATCH_SIZES
    assert LegacyVolumeDiscounts is VOLUME_DISCOUNTS
    assert LegacyMinimumBatchSize == MINIMUM_BATCH_SIZE
    assert LegacyRotationMinutes == ROTATION_MINUTES
