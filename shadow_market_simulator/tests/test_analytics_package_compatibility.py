from app.analytics.analytics_handlers import build_analytics_router
from app.analytics.analytics_log import (
    AnalyticsLogger,
    AnalyticsLoggingMiddleware,
    normalize_callback,
)
from app.analytics.business_analytics import (
    finance_text,
    normalize_period,
    overview_text,
    products_text,
)
from app.analytics_handlers import build_analytics_router as legacy_build_analytics_router
from app.analytics_log import AnalyticsLogger as LegacyAnalyticsLogger
from app.analytics_log import AnalyticsLoggingMiddleware as LegacyAnalyticsLoggingMiddleware
from app.analytics_log import normalize_callback as legacy_normalize_callback
from app.business_analytics import finance_text as legacy_finance_text
from app.business_analytics import normalize_period as legacy_normalize_period
from app.business_analytics import overview_text as legacy_overview_text
from app.business_analytics import products_text as legacy_products_text


def test_analytics_legacy_modules_are_thin_facades() -> None:
    assert legacy_build_analytics_router is build_analytics_router
    assert LegacyAnalyticsLogger is AnalyticsLogger
    assert LegacyAnalyticsLoggingMiddleware is AnalyticsLoggingMiddleware
    assert legacy_normalize_callback is normalize_callback
    assert legacy_normalize_period is normalize_period
    assert legacy_overview_text is overview_text
    assert legacy_products_text is products_text
    assert legacy_finance_text is finance_text
