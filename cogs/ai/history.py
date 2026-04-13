from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)


class HistoryManager:

    def __init__(self, context_file: Path, history_limit: int) -> None:
        self._context_file = context_file
        self._history_limit = history_limit
        self._histories: Dict[int, List[dict]] = {}

    def get_history(self, channel_id: int) -> List[dict]:
        return self._histories.setdefault(channel_id, [])

    def trim(self, history: List[dict]) -> None:
        if len(history) > self._history_limit:
            del history[: -self._history_limit]

    def snapshot(self) -> Dict[str, List[dict]]:
        snapshot: Dict[str, List[dict]] = {}

        for channel_id, history in self._histories.items():
            if history:
                snapshot[str(channel_id)] = history

        return snapshot

    def load(self) -> None:

        if not self._context_file.exists():
            return

        try:
            data = json.loads(self._context_file.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to load chat history")
            return

        if not isinstance(data, dict):
            return

        for channel_id, history in data.items():

            try:
                channel_id = int(channel_id)
            except Exception:
                continue

            if isinstance(history, list):
                self._histories[channel_id] = history[-self._history_limit :]

    async def persist(self) -> None:

        snapshot = self.snapshot()

        def write():
            self._context_file.write_text(
                json.dumps(snapshot, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        try:
            await asyncio.to_thread(write)
        except Exception:
            logger.exception("Failed to save chat history")