# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.request import urlopen

from utils.quickdraw_cache import (
    DEFAULT_MAX_EXAMPLES_PER_CATEGORY,
    OFFICIAL_QUICKDRAW_CATEGORIES_URL,
    QUICKDRAW_CACHE_VERSION,
    quickdraw_category_filename,
    quickdraw_category_url,
    sanitize_quickdraw_entry,
    verify_quickdraw_cache,
)

logger = logging.getLogger("build_quickdraw_cache")


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def iter_ndjson(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                logger.debug("Skipping malformed JSON in %s at line %s.", path.name, line_number)
                continue
            if isinstance(payload, dict):
                yield line_number, payload


def detect_category_name(path: Path, payload: dict[str, Any]) -> str:
    word = str(payload.get("word") or payload.get("answer") or "").strip()
    if word:
        return word
    return path.stem.replace("_", " ").strip()


def reservoir_add(pool: list[dict[str, Any]], entry: dict[str, Any], *, seen_valid: int, max_examples: int, rng: random.Random) -> None:
    if len(pool) < max_examples:
        pool.append(entry)
        return
    replacement_index = rng.randint(0, seen_valid - 1)
    if replacement_index < max_examples:
        pool[replacement_index] = entry


def discover_local_raw_files(raw_dir: Path, *, category_limit: int | None = None) -> list[Path]:
    raw_files = sorted(raw_dir.glob("*.ndjson"))
    if category_limit is not None:
        return raw_files[: max(0, category_limit)]
    return raw_files


def fetch_official_category_list(*, timeout: float = 60.0) -> list[str]:
    with urlopen(OFFICIAL_QUICKDRAW_CATEGORIES_URL, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    categories = [line.strip() for line in body.splitlines() if line.strip()]
    unique_categories = list(dict.fromkeys(categories))
    logger.info("Quick Draw category discovery returned %s categories.", len(unique_categories))
    return unique_categories


def download_quickdraw_category_file(
    *,
    category: str,
    raw_dir: Path,
    dataset_source: str,
    force_redownload: bool,
    timeout: float = 120.0,
) -> tuple[str, bool]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    filename = quickdraw_category_filename(category)
    destination = raw_dir / filename
    if destination.exists() and not force_redownload:
        logger.debug("Quick Draw raw file already exists for category '%s': %s", category, destination)
        return str(destination), False
    url = quickdraw_category_url(category, dataset_source=dataset_source)
    temp_path = destination.with_suffix(".tmp")
    logger.info("Downloading Quick Draw %s category '%s' -> %s", dataset_source, category, destination.name)
    with urlopen(url, timeout=timeout) as response:
        with temp_path.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                handle.write(chunk)
    temp_path.replace(destination)
    return str(destination), True


def download_quickdraw_dataset(
    *,
    raw_dir: Path,
    dataset_source: str,
    download_all: bool,
    download_missing: bool,
    force_redownload: bool,
    category_limit: int | None,
) -> dict[str, Any]:
    summary = {
        "discovered": 0,
        "downloaded": 0,
        "skipped_existing": 0,
        "failed": 0,
        "failed_categories": [],
    }
    if not download_all and not download_missing:
        return summary

    raw_dir.mkdir(parents=True, exist_ok=True)
    categories = fetch_official_category_list()
    if category_limit is not None:
        categories = categories[: max(0, category_limit)]
    summary["discovered"] = len(categories)
    for index, category in enumerate(categories, start=1):
        logger.info("Quick Draw download progress: %s/%s - %s", index, len(categories), category)
        try:
            _, downloaded = download_quickdraw_category_file(
                category=category,
                raw_dir=raw_dir,
                dataset_source=dataset_source,
                force_redownload=force_redownload,
            )
        except Exception:
            summary["failed"] += 1
            summary["failed_categories"].append(category)
            logger.warning("Failed to download Quick Draw category '%s'. Continuing.", category, exc_info=True)
            continue
        if downloaded:
            summary["downloaded"] += 1
        else:
            summary["skipped_existing"] += 1
    logger.info(
        "Quick Draw download summary: discovered=%s downloaded=%s skipped_existing=%s failed=%s",
        summary["discovered"],
        summary["downloaded"],
        summary["skipped_existing"],
        summary["failed"],
    )
    return summary


def build_cache(
    *,
    raw_dir: Path,
    output_path: Path,
    max_examples_per_category: int,
    seed: int | None,
    category_limit: int | None,
    dataset_source: str,
) -> dict[str, Any]:
    if not raw_dir.exists():
        raise FileNotFoundError(f"Quick Draw raw directory was not found: {raw_dir}")
    raw_files = discover_local_raw_files(raw_dir, category_limit=category_limit)
    if not raw_files:
        raise FileNotFoundError(
            f"No .ndjson files were found in {raw_dir}. Download them first with --download-all."
        )

    rng = random.Random(seed)
    categories_payload: dict[str, list[dict[str, Any]]] = {}
    category_stats: list[dict[str, Any]] = []
    skipped_categories: list[str] = []
    total_selected = 0
    started_at = time.perf_counter()

    for raw_file in raw_files:
        selected_entries: list[dict[str, Any]] = []
        valid_seen = 0
        scanned_lines = 0
        category_name = raw_file.stem.replace("_", " ").strip()
        for scanned_lines, payload in iter_ndjson(raw_file):
            category_name = detect_category_name(raw_file, payload)
            sanitized = sanitize_quickdraw_entry(
                payload,
                fallback_answer=category_name,
                fallback_category=category_name,
                clue=f"It is related to {category_name}.",
            )
            if sanitized is None:
                continue
            valid_seen += 1
            reservoir_add(
                selected_entries,
                sanitized,
                seen_valid=valid_seen,
                max_examples=max_examples_per_category,
                rng=rng,
            )

        if selected_entries:
            categories_payload[category_name] = selected_entries
            total_selected += len(selected_entries)
        else:
            skipped_categories.append(category_name)

        category_stats.append(
            {
                "category": category_name,
                "filename": raw_file.name,
                "scanned_lines": scanned_lines,
                "valid_seen": valid_seen,
                "selected_examples": len(selected_entries),
            }
        )
        logger.info(
            "Quick Draw cache build: category='%s' file='%s' scanned_lines=%s valid=%s selected=%s",
            category_name,
            raw_file.name,
            scanned_lines,
            valid_seen,
            len(selected_entries),
        )

    payload = {
        "version": QUICKDRAW_CACHE_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(raw_dir),
        "dataset_source": dataset_source,
        "raw_file_count": len(raw_files),
        "category_count": len(categories_payload),
        "entry_count": total_selected,
        "max_examples_per_category": max_examples_per_category,
        "seed": seed,
        "categories": categories_payload,
        "category_stats": category_stats,
        "skipped_categories": skipped_categories,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(output_path)

    elapsed = time.perf_counter() - started_at
    logger.info(
        "Quick Draw cache build complete in %.2fs. raw_files=%s cached_categories=%s cached_entries=%s output=%s",
        elapsed,
        payload["raw_file_count"],
        payload["category_count"],
        payload["entry_count"],
        output_path,
    )
    if skipped_categories:
        logger.info("Quick Draw cache skipped %s categories with no valid drawable entries.", len(skipped_categories))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download full Quick Draw .ndjson category files and build a fast local runtime cache.",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/quickdraw_raw"),
        help="Directory for local Quick Draw .ndjson category files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/quickdraw_cache.json"),
        help="Destination cache JSON file for runtime loading.",
    )
    parser.add_argument(
        "--dataset-source",
        choices=("raw", "simplified"),
        default="raw",
        help="Which official Quick Draw .ndjson dataset to download. Both produce one file per category.",
    )
    parser.add_argument(
        "--download-all",
        action="store_true",
        help="Fetch the official category list and sync every category file into --raw-dir.",
    )
    parser.add_argument(
        "--download-missing",
        action="store_true",
        help="Fetch the official category list and download only categories missing from --raw-dir.",
    )
    parser.add_argument(
        "--force-redownload",
        action="store_true",
        help="Re-download category files even if they already exist locally.",
    )
    parser.add_argument(
        "--category-limit",
        type=int,
        default=None,
        help="Optional limit for testing a subset of categories during download/build.",
    )
    parser.add_argument(
        "--max-examples",
        type=int,
        default=DEFAULT_MAX_EXAMPLES_PER_CATEGORY,
        help="How many drawable examples to keep per category in the runtime cache.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional deterministic random seed for cache sampling.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Validate and print cache health without downloading or rebuilding.",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Download/sync .ndjson files and stop before cache building.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_logging(args.verbose)

    if args.verify_only:
        summary = verify_quickdraw_cache(args.output)
        logger.info("Quick Draw cache health: %s", summary)
        return 0

    if args.max_examples <= 0:
        raise ValueError("--max-examples must be greater than zero.")

    download_summary = download_quickdraw_dataset(
        raw_dir=args.raw_dir,
        dataset_source=args.dataset_source,
        download_all=args.download_all,
        download_missing=args.download_missing,
        force_redownload=args.force_redownload,
        category_limit=args.category_limit,
    )

    if args.download_only:
        logger.info(
            "Quick Draw download-only mode complete: downloaded=%s skipped_existing=%s failed=%s raw_dir=%s",
            download_summary["downloaded"],
            download_summary["skipped_existing"],
            download_summary["failed"],
            args.raw_dir,
        )
        return 0

    payload = build_cache(
        raw_dir=args.raw_dir,
        output_path=args.output,
        max_examples_per_category=args.max_examples,
        seed=args.seed,
        category_limit=args.category_limit,
        dataset_source=args.dataset_source,
    )

    logger.info(
        "Quick Draw pipeline ready: dataset_source=%s downloaded=%s skipped_existing=%s failed_downloads=%s cached_categories=%s cached_entries=%s",
        args.dataset_source,
        download_summary["downloaded"],
        download_summary["skipped_existing"],
        download_summary["failed"],
        payload["category_count"],
        payload["entry_count"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
