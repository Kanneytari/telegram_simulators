from pathlib import Path

path = Path('.github/scripts/refactor_nightshift_ui_vocabulary.py')
text = path.read_text(encoding='utf-8')
text = text.replace(
    "copy_path.write_text(\n    '''from __future__ import annotations",
    "copy_path.write_text(\n    r'''from __future__ import annotations",
    1,
)
text = text.replace(
    "(TESTS / \"test_ui_vocabulary.py\").write_text(\n    '''from __future__ import annotations",
    "(TESTS / \"test_ui_vocabulary.py\").write_text(\n    r'''from __future__ import annotations",
    1,
)
path.write_text(text, encoding='utf-8')
