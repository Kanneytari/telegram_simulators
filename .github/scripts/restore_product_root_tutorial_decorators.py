from pathlib import Path

path = Path('shadow_market_simulator/app/ui_commerce.py')
text = path.read_text(encoding='utf-8')
needle = '\nasync def render_product_root(target: Message, db, game, player_id: int, *, flash: str | None = None) -> None:\n'
replacement = (
    '\n@tutorial_hooks.handoff_product_root\n'
    '@tutorial_hooks.affordable_empty_product_root\n'
    '@tutorial_hooks.soft_product_root\n'
    'async def render_product_root(target: Message, db, game, player_id: int, *, flash: str | None = None) -> None:\n'
)
if needle not in text:
    raise SystemExit('undecorated render_product_root not found')
text = text.replace(needle, replacement, 1)
path.write_text(text, encoding='utf-8')
