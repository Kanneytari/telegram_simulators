from __future__ import annotations

from collections import OrderedDict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery


_ONE_SHOT_CALLBACK_PREFIXES = (
    "team:allocdo:",
    "team:roleconfirm:",
    "team:upgradedo:",
)


class OneShotCallbackMiddleware(BaseMiddleware):
    """Suppress duplicate delivery of successful confirmation callbacks."""

    def __init__(self, max_entries: int = 4096) -> None:
        self.max_entries = max(128, int(max_entries))
        self._seen: OrderedDict[tuple[int, int, str], None] = OrderedDict()

    @staticmethod
    def _is_one_shot(data: str | None) -> bool:
        value = data or ""
        return any(value.startswith(prefix) for prefix in _ONE_SHOT_CALLBACK_PREFIXES)

    async def __call__(self, handler, event, data):
        if not isinstance(event, CallbackQuery) or not self._is_one_shot(event.data):
            return await handler(event, data)

        message_id = int(event.message.message_id) if event.message else 0
        key = (int(event.from_user.id), message_id, str(event.data))
        if key in self._seen:
            try:
                await event.answer("Действие уже обработано.")
            except Exception:
                pass
            return None

        self._seen[key] = None
        self._seen.move_to_end(key)
        while len(self._seen) > self.max_entries:
            self._seen.popitem(last=False)
        try:
            return await handler(event, data)
        except Exception:
            self._seen.pop(key, None)
            raise
