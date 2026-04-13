# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import quote

logger = logging.getLogger(__name__)

QUICKDRAW_CACHE_VERSION = 2
DEFAULT_MAX_EXAMPLES_PER_CATEGORY = 5
DEFAULT_CATEGORY_ATTEMPT_LIMIT = 8
DEFAULT_SAMPLE_ATTEMPT_LIMIT = 8
DEFAULT_MAX_STROKES = 128
DEFAULT_MAX_POINTS = 4096
OFFICIAL_QUICKDRAW_CATEGORIES_URL = "https://raw.githubusercontent.com/googlecreativelab/quickdraw-dataset/master/categories.txt"
OFFICIAL_QUICKDRAW_RAW_URL_TEMPLATE = "https://storage.googleapis.com/quickdraw_dataset/full/raw/{category}.ndjson"
OFFICIAL_QUICKDRAW_SIMPLIFIED_URL_TEMPLATE = "https://storage.googleapis.com/quickdraw_dataset/full/simplified/{category}.ndjson"


def normalize_quickdraw_lookup(text: str) -> str:
    lowered = str(text or "").strip().lower()
    lowered = re.sub(r"[_\-\s]+", " ", lowered)
    lowered = re.sub(r"[^a-z0-9\s]", "", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def quickdraw_category_filename(category: str) -> str:
    cleaned = str(category or "").strip()
    cleaned = re.sub(r'[<>:"/\\\\|?*]+', "_", cleaned)
    cleaned = cleaned.rstrip(" .")
    return f"{cleaned or 'unknown'}.ndjson"


def quickdraw_category_url(category: str, *, dataset_source: str = "raw") -> str:
    encoded = quote(str(category or "").strip(), safe="")
    if dataset_source == "simplified":
        return OFFICIAL_QUICKDRAW_SIMPLIFIED_URL_TEMPLATE.format(category=encoded)
    return OFFICIAL_QUICKDRAW_RAW_URL_TEMPLATE.format(category=encoded)


def normalize_quickdraw_strokes(drawing: Any) -> list[list[tuple[float, float]]]:
    normalized: list[list[tuple[float, float]]] = []
    if not isinstance(drawing, list):
        return normalized
    for raw_stroke in drawing:
        if not isinstance(raw_stroke, (list, tuple)) or len(raw_stroke) < 2:
            continue
        raw_x, raw_y = raw_stroke[0], raw_stroke[1]
        if not isinstance(raw_x, (list, tuple)) or not isinstance(raw_y, (list, tuple)):
            continue
        points: list[tuple[float, float]] = []
        for x_value, y_value in zip(raw_x, raw_y):
            try:
                points.append((float(x_value), float(y_value)))
            except (TypeError, ValueError):
                continue
        if points:
            normalized.append(points)
    return normalized


def quickdraw_entry_is_drawable(
    entry: dict[str, Any],
    *,
    max_strokes: int = DEFAULT_MAX_STROKES,
    max_points: int = DEFAULT_MAX_POINTS,
) -> bool:
    drawing = entry.get("drawing")
    strokes = normalize_quickdraw_strokes(drawing)
    if not strokes:
        return False
    if len(strokes) > max_strokes:
        return False
    total_points = sum(len(stroke) for stroke in strokes)
    if total_points < 2 or total_points > max_points:
        return False
    if not any(len(stroke) >= 2 for stroke in strokes):
        return False
    all_x = [point[0] for stroke in strokes for point in stroke]
    all_y = [point[1] for stroke in strokes for point in stroke]
    if not all_x or not all_y:
        return False
    if max(all_x) == min(all_x) and max(all_y) == min(all_y):
        return False
    return True


def sanitize_quickdraw_entry(
    entry: dict[str, Any],
    *,
    fallback_answer: Optional[str] = None,
    fallback_category: Optional[str] = None,
    clue: Optional[str] = None,
) -> dict[str, Any] | None:
    answer = str(entry.get("answer") or entry.get("word") or fallback_answer or "").strip()
    category = str(entry.get("category") or entry.get("word") or fallback_category or answer).strip()
    if not answer or not category:
        return None
    candidate = {
        "answer": answer,
        "category": category,
        "drawing": entry.get("drawing"),
        "clue": str(entry.get("clue") or clue or f"It is related to {answer}."),
        "aliases": [str(alias).strip() for alias in (entry.get("aliases") or []) if str(alias).strip()],
    }
    if not quickdraw_entry_is_drawable(candidate):
        return None
    return candidate


@dataclass(slots=True)
class QuickDrawCacheStats:
    version: int
    built_at: str
    category_count: int
    entry_count: int
    cache_path: Path
    dataset_source: str = "unknown"
    source_dir: str = ""


class QuickDrawCacheManager:
    def __init__(
        self,
        *,
        cache_path: Path,
        fallback_entries: Sequence[dict[str, Any]],
        random_seed: Optional[int] = None,
    ) -> None:
        self.cache_path = Path(cache_path)
        self._fallback_entries = [dict(entry) for entry in fallback_entries]
        self._rng = random.Random(random_seed)
        self._loaded = False
        self._cache_data: dict[str, list[dict[str, Any]]] = {}
        self._stats = QuickDrawCacheStats(
            version=QUICKDRAW_CACHE_VERSION,
            built_at="unknown",
            category_count=0,
            entry_count=0,
            cache_path=self.cache_path,
        )

    @property
    def stats(self) -> QuickDrawCacheStats:
        if not self._loaded:
            self.load()
        return self._stats

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.cache_path.exists():
            logger.warning("Quick Draw cache file not found at %s. Runtime will use safe fallback drawings.", self.cache_path)
            return
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Quick Draw cache at %s could not be read. Runtime will use fallback drawings.", self.cache_path, exc_info=True)
            return
        if not isinstance(payload, dict):
            logger.warning("Quick Draw cache at %s has an invalid structure.", self.cache_path)
            return
        version = int(payload.get("version", 0))
        if version != QUICKDRAW_CACHE_VERSION:
            logger.warning(
                "Quick Draw cache version mismatch at %s. Expected %s, got %s.",
                self.cache_path,
                QUICKDRAW_CACHE_VERSION,
                version,
            )
        raw_categories = payload.get("categories")
        prepared_categories: dict[str, list[dict[str, Any]]] = {}
        if isinstance(raw_categories, dict):
            for raw_category, raw_entries in raw_categories.items():
                category = str(raw_category).strip()
                if not category or not isinstance(raw_entries, list):
                    continue
                sanitized_entries = [
                    sanitized
                    for sanitized in (
                        sanitize_quickdraw_entry(
                            dict(entry),
                            fallback_answer=category,
                            fallback_category=category,
                        )
                        for entry in raw_entries
                        if isinstance(entry, dict)
                    )
                    if sanitized is not None
                ]
                if sanitized_entries:
                    prepared_categories[category] = sanitized_entries
        self._cache_data = prepared_categories
        self._stats = QuickDrawCacheStats(
            version=version or QUICKDRAW_CACHE_VERSION,
            built_at=str(payload.get("built_at") or "unknown"),
            category_count=len(prepared_categories),
            entry_count=sum(len(entries) for entries in prepared_categories.values()),
            cache_path=self.cache_path,
            dataset_source=str(payload.get("dataset_source") or "unknown"),
            source_dir=str(payload.get("source_dir") or ""),
        )
        logger.info(
            "Quick Draw cache loaded from %s with %s categories and %s cached entries.",
            self.cache_path,
            self._stats.category_count,
            self._stats.entry_count,
        )

    def categories(self) -> list[str]:
        if not self._loaded:
            self.load()
        if self._cache_data:
            return list(self._cache_data.keys())
        fallback_categories = sorted(
            {
                sanitize_quickdraw_entry(entry, fallback_answer=str(entry.get("answer") or ""))["category"]
                for entry in self._fallback_entries
                if sanitize_quickdraw_entry(entry, fallback_answer=str(entry.get("answer") or "")) is not None
            }
        )
        return fallback_categories

    def get_entries_for_category(self, category: str) -> list[dict[str, Any]]:
        if not self._loaded:
            self.load()
        normalized = normalize_quickdraw_lookup(category)
        if not normalized:
            return []
        for stored_category, entries in self._cache_data.items():
            if normalize_quickdraw_lookup(stored_category) == normalized:
                return [dict(entry) for entry in entries]
        return [
            dict(entry)
            for entry in self._fallback_entries
            if (
                sanitize_quickdraw_entry(entry, fallback_answer=str(entry.get("answer") or "")) is not None
                and normalize_quickdraw_lookup(str(entry.get("category") or entry.get("answer") or "")) == normalized
            )
        ]

    def choose_entry(
        self,
        *,
        preferred_category: Optional[str] = None,
        category_attempt_limit: int = DEFAULT_CATEGORY_ATTEMPT_LIMIT,
        sample_attempt_limit: int = DEFAULT_SAMPLE_ATTEMPT_LIMIT,
    ) -> dict[str, Any]:
        if not self._loaded:
            self.load()
        category_names = self.categories()
        if not category_names:
            raise RuntimeError("Quick Draw cache is empty and no fallback entries are available.")
        ordered_categories: list[str] = []
        if preferred_category:
            preferred_entries = self.get_entries_for_category(preferred_category)
            if preferred_entries:
                ordered_categories.append(preferred_entries[0]["category"])
        remaining_categories = [category for category in category_names if category not in ordered_categories]
        self._rng.shuffle(remaining_categories)
        ordered_categories.extend(remaining_categories[: max(0, category_attempt_limit - len(ordered_categories))])
        for category in ordered_categories:
            entries = self.get_entries_for_category(category)
            if not entries:
                continue
            self._rng.shuffle(entries)
            for entry in entries[:sample_attempt_limit]:
                sanitized = sanitize_quickdraw_entry(entry, fallback_answer=category, fallback_category=category)
                if sanitized is not None:
                    logger.info(
                        "Quick Draw cache selected category='%s' answer='%s'.",
                        sanitized["category"],
                        sanitized["answer"],
                    )
                    return sanitized
        fallback_pool = [
            sanitized
            for sanitized in (
                sanitize_quickdraw_entry(entry, fallback_answer=str(entry.get("answer") or ""))
                for entry in self._fallback_entries
            )
            if sanitized is not None
        ]
        if not fallback_pool:
            raise RuntimeError("Quick Draw cache is unusable and no fallback entries are drawable.")
        chosen = dict(self._rng.choice(fallback_pool))
        logger.warning("Quick Draw cache fell back to built-in entry '%s'.", chosen["answer"])
        return chosen

    def health_summary(self) -> dict[str, Any]:
        stats = self.stats
        return {
            "cache_path": str(stats.cache_path),
            "version": stats.version,
            "built_at": stats.built_at,
            "category_count": stats.category_count,
            "entry_count": stats.entry_count,
            "dataset_source": stats.dataset_source,
            "source_dir": stats.source_dir,
            "has_runtime_cache": bool(self._cache_data),
            "has_fallback_entries": bool(self._fallback_entries),
        }


def verify_quickdraw_cache(cache_path: Path) -> dict[str, Any]:
    manager = QuickDrawCacheManager(cache_path=cache_path, fallback_entries=())
    manager.load()
    return manager.health_summary()
