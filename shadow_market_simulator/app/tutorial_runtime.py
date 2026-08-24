from __future__ import annotations


def apply_tutorial_runtime_fixes() -> None:
    """Compatibility hook kept for startup order.

    Tutorial behavior now lives in app.tutorial and only adds guidance/protection.
    It must not filter offers, replace normal navigation, or hide player actions.
    """
    return None
