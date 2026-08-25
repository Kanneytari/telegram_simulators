from pathlib import Path

ROOT = Path('shadow_market_simulator')

vocabulary_path = ROOT / 'app/presentation/vocabulary.py'
text = vocabulary_path.read_text(encoding='utf-8')
anchor = 'RECRUIT = UiItem("🔎 Нанять", "team:recruit")\n'
if anchor not in text:
    raise SystemExit('RECRUIT vocabulary anchor not found')
text = text.replace(anchor, anchor + 'HIRE = UiItem("✅ Нанять", "team:hire")\n', 1)
vocabulary_path.write_text(text, encoding='utf-8')

handlers_path = ROOT / 'app/ui_staff_handlers.py'
text = handlers_path.read_text(encoding='utf-8')
import_anchor = 'from app.presentation.vocabulary import '
lines = text.splitlines()
for index, line in enumerate(lines):
    if line.startswith(import_anchor):
        names = {part.strip() for part in line[len(import_anchor):].split(',') if part.strip()}
        names.update({'HIRE', 'button'})
        lines[index] = import_anchor + ', '.join(sorted(names))
        break
else:
    lines.insert(2, import_anchor + 'HIRE, button')
text = '\n'.join(lines) + ('\n' if text.endswith('\n') else '')
text = text.replace(
    'InlineKeyboardButton(text="Нанять", callback_data=f"team:hire:{candidate_id}")',
    'button(HIRE, callback_data=f"team:hire:{candidate_id}")',
)
handlers_path.write_text(text, encoding='utf-8')
