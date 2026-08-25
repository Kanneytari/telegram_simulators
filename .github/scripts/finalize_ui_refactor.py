from pathlib import Path

root = Path('shadow_market_simulator')

init_path = root / 'app/tutorial/__init__.py'
text = init_path.read_text(encoding='utf-8')
text = text.replace(
    'from .copy import instruction\n',
    'from .copy import instruction as instruction\n',
)
init_path.write_text(text, encoding='utf-8')

hooks_path = root / 'app/tutorial/hooks.py'
text = hooks_path.read_text(encoding='utf-8')
text = text.replace(
    "'<b>🤝 Поставщики</b>\\n\\n'",
    "f'<b>{SUPPLIERS.label}</b>\\n\\n'",
)
text = text.replace(
    "'<b>🤝 Поставщики</b>\\n\\nДоступных предложений нет.'",
    "f'<b>{SUPPLIERS.label}</b>\\n\\nДоступных предложений нет.'",
)
hooks_path.write_text(text, encoding='utf-8')

updates_path = root / 'tests/test_zz_gameplay_updates.py'
text = updates_path.read_text(encoding='utf-8')
text = text.replace(
    'from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup\n\n',
    '',
)
updates_path.write_text(text, encoding='utf-8')
