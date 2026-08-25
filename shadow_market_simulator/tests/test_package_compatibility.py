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
from app.compensation import COMPENSATION_RANGES as LegacyCompensationRanges
from app.compensation import DEFAULT_POLICIES as LegacyDefaultPolicies
from app.compensation import CompensationGameService as LegacyCompensationGameService
from app.compensation import CompensationSimulationEngine as LegacyCompensationSimulationEngine
from app.compensation import _deposit_part as legacy_deposit_part
from app.compensation import _ensure_policy_conn as legacy_ensure_policy_conn
from app.compensation import _money_from_bps as legacy_money_from_bps
from app.compensation import _policy_conn as legacy_policy_conn
from app.config import Settings as LegacySettings
from app.core.config import Settings
from app.core.database import Database
from app.courier_core import CourierCoreGameService as LegacyCourierCoreGameService
from app.courier_core import CourierCoreSimulationEngine as LegacyCourierCoreSimulationEngine
from app.courier_idle import courier_idle_ready as legacy_courier_idle_ready
from app.courier_management import PHONE as LegacyPhone
from app.courier_management import TRANSPORT as LegacyTransport
from app.courier_management import CourierManagementGameService as LegacyCourierManagementGameService
from app.courier_management import CourierManagementSimulationEngine as LegacyCourierManagementSimulationEngine
from app.courier_model import CourierBlueprint as LegacyCourierBlueprint
from app.courier_recruitment import CourierRecruitmentService as LegacyCourierRecruitmentService
from app.customer_trust import CustomerTrustGameService as LegacyCustomerTrustGameService
from app.customer_trust import CustomerTrustSimulationEngine as LegacyCustomerTrustSimulationEngine
from app.customer_trust import _bayesian_rating as legacy_bayesian_rating
from app.customer_trust import premium_allowance as legacy_premium_allowance
from app.customer_trust import trust_band as legacy_trust_band
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
from app.staff.compensation import (
    COMPENSATION_RANGES,
    DEFAULT_POLICIES,
    CompensationGameService,
    CompensationSimulationEngine,
    _deposit_part,
    _ensure_policy_conn,
    _money_from_bps,
    _policy_conn,
)
from app.staff.couriers.core import CourierCoreGameService, CourierCoreSimulationEngine
from app.staff.couriers.idle import courier_idle_ready
from app.staff.couriers.management import PHONE, TRANSPORT, CourierManagementGameService, CourierManagementSimulationEngine
from app.staff.couriers.model import CourierBlueprint
from app.staff.couriers.recruitment import CourierRecruitmentService
from app.staff.idle import IdleAwareMixin
from app.staff.insights import StaffInsightGameService, StaffInsightSimulationEngine
from app.staff.relationships import (
    SALES_ACTIVITY_MULTIPLIER,
    StaffRelationshipGameService,
    StaffRelationshipSimulationEngine,
    _apply_overexposure_effect,
    _apply_relationship_delta,
)
from app.staff.rename import rename_employee
from app.staff_idle import IdleAwareGameService as LegacyIdleAwareGameService
from app.staff_insights import StaffInsightGameService as LegacyStaffInsightGameService
from app.staff_insights import StaffInsightSimulationEngine as LegacyStaffInsightSimulationEngine
from app.staff_relationships import SALES_ACTIVITY_MULTIPLIER as LegacySalesActivityMultiplier
from app.staff_relationships import StaffRelationshipGameService as LegacyStaffRelationshipGameService
from app.staff_relationships import StaffRelationshipSimulationEngine as LegacyStaffRelationshipSimulationEngine
from app.staff_relationships import _apply_overexposure_effect as legacy_apply_overexposure_effect
from app.staff_relationships import _apply_relationship_delta as legacy_apply_relationship_delta
from app.trust.customer import (
    CustomerTrustGameService,
    CustomerTrustSimulationEngine,
    _bayesian_rating,
    premium_allowance,
    trust_band,
)
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
    assert LegacyCompensationGameService is CompensationGameService
    assert LegacyCompensationSimulationEngine is CompensationSimulationEngine
    assert LegacyCompensationRanges is COMPENSATION_RANGES
    assert LegacyDefaultPolicies is DEFAULT_POLICIES
    assert legacy_deposit_part is _deposit_part
    assert legacy_ensure_policy_conn is _ensure_policy_conn
    assert legacy_money_from_bps is _money_from_bps
    assert legacy_policy_conn is _policy_conn
    assert LegacyStaffRelationshipGameService is StaffRelationshipGameService
    assert LegacyStaffRelationshipSimulationEngine is StaffRelationshipSimulationEngine
    assert LegacySalesActivityMultiplier == SALES_ACTIVITY_MULTIPLIER
    assert legacy_apply_overexposure_effect is _apply_overexposure_effect
    assert legacy_apply_relationship_delta is _apply_relationship_delta
    assert LegacyCustomerTrustGameService is CustomerTrustGameService
    assert LegacyCustomerTrustSimulationEngine is CustomerTrustSimulationEngine
    assert legacy_bayesian_rating is _bayesian_rating
    assert legacy_premium_allowance is premium_allowance
    assert legacy_trust_band is trust_band
    assert LegacyCourierCoreGameService is CourierCoreGameService
    assert LegacyCourierCoreSimulationEngine is CourierCoreSimulationEngine
    assert LegacyCourierManagementGameService is CourierManagementGameService
    assert LegacyCourierManagementSimulationEngine is CourierManagementSimulationEngine
    assert LegacyPhone is PHONE
    assert LegacyTransport is TRANSPORT
