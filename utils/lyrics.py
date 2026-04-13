import os
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional, Tuple

import lyricsgenius

_genius_client = None


def get_genius_client():
    global _genius_client
    if _genius_client is not None:
        return _genius_client

    token = os.getenv("GENIUS_ACCESS_TOKEN")
    if not token:
        return None

    genius = lyricsgenius.Genius(token)
    genius.verbose = False
    genius.remove_section_headers = True
    genius.skip_non_songs = True
    genius.excluded_terms = ["(Remix)", "(Live)"]
    genius.timeout = 10
    genius.retries = 2

    _genius_client = genius
    return _genius_client


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )


def _norm(text: Optional[str]) -> str:
    if not text:
        return ""

    text = text.strip().lower()
    text = _strip_accents(text)

    text = re.sub(
        r"\((official|lyrics?|lyric video|audio|video|hd|mv|visualizer|remaster(ed)?)[^)]*\)",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\[(official|lyrics?|lyric video|audio|video|hd|mv|visualizer|remaster(ed)?)[^\]]*\]",
        "",
        text,
        flags=re.I,
    )

    text = re.sub(r"\bfeat\.?\b", "ft", text, flags=re.I)
    text = re.sub(r"\bft\.?\b", "ft", text, flags=re.I)
    text = re.sub(r"\bwith lyrics\b", "", text, flags=re.I)
    text = re.sub(r"\bofficial video\b", "", text, flags=re.I)
    text = re.sub(r"\bofficial audio\b", "", text, flags=re.I)
    text = re.sub(r"\blyric video\b", "", text, flags=re.I)
    text = re.sub(r"\bvisualizer\b", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -")


def _split_artist_title(raw_title: str, fallback_artist: Optional[str]) -> Tuple[str, Optional[str]]:
    cleaned = _norm(raw_title)
    fallback_artist = _norm(fallback_artist) if fallback_artist else None

    if " - " in cleaned:
        left, right = cleaned.split(" - ", 1)
        if left and right:
            return right.strip(), left.strip()

    return cleaned, fallback_artist


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _score_hit(
    wanted_title: str,
    wanted_artist: Optional[str],
    found_title: Optional[str],
    found_artist: Optional[str],
) -> float:
    title_score = _similarity(wanted_title, found_title or "")
    artist_score = _similarity(wanted_artist or "", found_artist or "") if wanted_artist else 0.5

    score = title_score * 0.78 + artist_score * 0.22

    wanted_title_n = _norm(wanted_title)
    found_title_n = _norm(found_title or "")
    wanted_artist_n = _norm(wanted_artist or "")
    found_artist_n = _norm(found_artist or "")

    if wanted_title_n and wanted_title_n in found_title_n:
        score += 0.08
    if wanted_artist_n and wanted_artist_n in found_artist_n:
        score += 0.05

    return score


def _candidate_queries(title: str, artist: Optional[str]) -> list[tuple[str, Optional[str]]]:
    clean_title, clean_artist = _split_artist_title(title, artist)

    queries: list[tuple[str, Optional[str]]] = [
        (clean_title, clean_artist),
        (clean_title, None),
    ]

    if clean_artist and " ft " in clean_artist:
        queries.append((clean_title, clean_artist.split(" ft ", 1)[0].strip()))

    # raw normalized fallback
    raw_norm = _norm(title)
    if raw_norm != clean_title:
        queries.append((raw_norm, clean_artist))
        queries.append((raw_norm, None))

    # title-only after removing artist-like left side if still present
    if " - " in raw_norm:
        left, right = raw_norm.split(" - ", 1)
        if right.strip():
            queries.append((right.strip(), clean_artist))
            queries.append((right.strip(), None))

    deduped = []
    seen = set()
    for q in queries:
        key = (q[0] or "", q[1] or "")
        if key in seen or not q[0]:
            continue
        seen.add(key)
        deduped.append(q)

    return deduped


def _search_best_song(genius, title: str, artist: Optional[str]):
    best_song = None
    best_score = 0.0

    for q_title, q_artist in _candidate_queries(title, artist):
        try:
            song = genius.search_song(title=q_title, artist=q_artist)
        except Exception:
            continue

        if not song:
            continue

        found_title = getattr(song, "title", "")
        found_artist = getattr(song, "artist", "")

        score = _score_hit(
            wanted_title=q_title,
            wanted_artist=q_artist,
            found_title=found_title,
            found_artist=found_artist,
        )

        if score > best_score:
            best_score = score
            best_song = song

    if best_score < 0.58:
        return None

    return best_song


def fetch_lyrics(title: str, artist: Optional[str] = None) -> Optional[str]:
    genius = get_genius_client()
    if genius is None:
        return None

    try:
        song = _search_best_song(genius, title, artist)
        if not song or not song.lyrics:
            return None

        lyrics = song.lyrics.strip()
        lyrics = re.sub(r"\d*Embed$", "", lyrics).strip()

        return lyrics or None
    except Exception:
        return None