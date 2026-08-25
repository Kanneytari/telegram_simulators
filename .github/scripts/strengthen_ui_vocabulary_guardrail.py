from pathlib import Path

path = Path('shadow_market_simulator/tests/test_ui_vocabulary.py')
text = path.read_text(encoding='utf-8')
needle = '''            if name != "InlineKeyboardButton":
                continue
            text_kw = next((kw.value for kw in node.keywords if kw.arg == "text"), None)
'''
replacement = '''            line = f"{source_path.relative_to(APP)}:{getattr(node, 'lineno', '?')}"
            if name == "nav_row":
                first_arg = node.args[0] if node.args else None
                if isinstance(first_arg, ast.Constant) and first_arg.value in canonical_callbacks:
                    offenders.append(
                        f"{line} raw canonical nav callback={first_arg.value!r}; use UiItem"
                    )
                continue
            if name != "InlineKeyboardButton":
                continue
            text_kw = next((kw.value for kw in node.keywords if kw.arg == "text"), None)
'''
if needle not in text:
    raise SystemExit('guardrail insertion anchor not found')
text = text.replace(needle, replacement, 1)
text = text.replace(
    '            line = f"{source_path.relative_to(APP)}:{getattr(node, \'lineno\', \'?\')}"\n'
    '            if isinstance(text_kw, ast.Constant)',
    '            if isinstance(text_kw, ast.Constant)',
    1,
)
path.write_text(text, encoding='utf-8')
