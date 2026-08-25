from pathlib import Path


def test_storefront_packaging_buttons_do_not_reuse_storefront_emoji() -> None:
    source = Path("app/ui_commerce.py").read_text(encoding="utf-8")
    assert 'text=f"×{listing[\'pack_size\']} · {money(listing[\'price\'])} · доступно {int(listing[\'positions\'])}"' in source
    assert 'text=f"🏷 ×{listing[\'pack_size\']}' not in source
    assert 'rows.append(nav_row(STOREFRONT))' in source
