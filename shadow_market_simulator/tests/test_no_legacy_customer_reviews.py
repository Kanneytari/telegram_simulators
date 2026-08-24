from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _python_sources():
    return sorted(APP_DIR.glob("*.py"))


def test_legacy_text_review_system_is_gone():
    forbidden = (
        "FROM reviews",
        "INTO reviews",
        "UPDATE reviews",
        "create_review_for_order",
        "_create_review(",
        "product_reviews(",
        "employee_reviews(",
        "customer_expectations",
        "delivery_feedback_analytics",
    )
    offenders = []
    for path in _python_sources():
        text = path.read_text(encoding="utf-8")
        hits = [token for token in forbidden if token in text]
        if hits:
            offenders.append(f"{path.name}: {', '.join(hits)}")
    assert not offenders, "Legacy review code remains:\n" + "\n".join(offenders)


def test_schema_does_not_use_runtime_column_migrations():
    offenders = []
    for path in _python_sources():
        text = path.read_text(encoding="utf-8")
        if "_ensure_column" in text:
            offenders.append(path.name)
    assert not offenders, "Runtime column migration code remains: " + ", ".join(offenders)
