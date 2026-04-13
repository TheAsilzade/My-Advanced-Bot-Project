from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from dataclasses import dataclass, field
import difflib
import logging
import re
import time
from typing import Any, Optional, TYPE_CHECKING, Iterable

import discord
from discord.ext import commands

from config import CHATBOT_CHANNEL_ID, CHATBOT_CHANNEL_IDS

try:
    import argostranslate.translate as _argos_translate
except ImportError:
    _argos_translate = None

if TYPE_CHECKING:
    from cogs.community_cog import Community
    from cogs.music_cog import Music

logger = logging.getLogger(__name__)
TURKISH_HINT_CHARS = "çğıöşüİıÇĞÖŞÜ"


def tr_to_en(text: str) -> str:
    if _argos_translate is None:
        raise RuntimeError("Argos Translate is not available.")
    return _argos_translate.translate(text, "tr", "en")


def _looks_turkish_text(text: str) -> bool:
    return any(char in text for char in TURKISH_HINT_CHARS)


def _looks_like_media_urlish(text: str) -> bool:
    lowered = (text or "").strip().lower()
    if lowered.startswith(("http://", "https://", "www.")):
        return True
    return any(domain in lowered for domain in ("youtube.com", "youtu.be", "soundcloud.com", "on.soundcloud.com"))


@dataclass(slots=True)
class IntentResult:
    name: str
    arg: Optional[str] = None
    confidence: float = 0.0
    start: int = -1
    end: int = -1
    meta: dict = field(default_factory=dict)


class RaizelChatCog(commands.Cog):
    """
    Upgraded natural-language intent layer for the music bot.

    Goal:
    - Keep the original music cog functions untouched.
    - Make the message understanding layer much stronger.
    - Support more human phrasing, light fuzzy matching, compound actions,
      and better extraction for play / volume / loop / seek style commands.
    """

    COMMAND_ALIASES: dict[str, tuple[str, ...]] = {
        "join": (
            "join",
            "join vc",
            "join voice",
            "join voice call",
            "join voice channel",
            "join my vc",
            "join my voice",
            "join the vc",
            "join the voice",
            "join the call",
            "come to vc",
            "come to voice",
            "come in vc",
            "come in voice",
            "hop in vc",
            "hop in voice",
            "hop into vc",
            "hop into voice",
            "enter vc",
            "enter voice",
            "summon",
            "get in vc",
            "get in voice",
        ),
        "leave": (
            "leave",
            "leave vc",
            "leave voice",
            "leave call",
            "disconnect",
            "disconnect vc",
            "disconnect voice",
            "dc",
            "get out of vc",
            "get out of voice",
            "exit vc",
            "exit voice",
        ),
        "previous": (
            "previous",
            "previous song",
            "previous track",
            "last song",
            "last track",
            "play previous",
            "play previous song",
            "play previous track",
            "play the previous song",
            "play the previous track",
            "play the last song",
            "play the last track",
            "replay previous song",
            "replay last song",
            "go back to previous song",
            "go back to the previous song",
            "go back to last song",
            "play it again",
        ),
        "skip": (
            "skip",
            "next",
            "next song",
            "next track",
            "skip song",
            "skip track",
            "skip this",
            "skip this song",
            "skip this track",
            "go next",
            "play next",
        ),
        "pause": (
            "pause",
            "pause music",
            "pause song",
            "pause playback",
            "pause the music",
            "pause the song",
            "hold on",
            "hold music",
            "stop for a sec",
        ),
        "resume": (
            "resume",
            "resume music",
            "resume playback",
            "unpause",
            "continue",
            "continue music",
            "continue playback",
            "resume it",
            "keep going",
        ),
        "stop": (
            "stop",
            "stop music",
            "stop playback",
            "stop the music",
            "clear queue",
            "clear the queue",
            "stop and clear",
            "end playback",
        ),
        "queue": (
            "queue",
            "show queue",
            "show the queue",
            "what is in the queue",
            "whats in the queue",
            "what s in the queue",
            "playlist",
            "now playing",
            "what is playing",
            "what s playing",
            "what's playing",
            "current track",
            "current song",
            "show current song",
        ),
        "shuffle": (
            "shuffle",
            "shuffle queue",
            "shuffle the queue",
            "mix the queue",
            "randomize queue",
            "randomise queue",
        ),
        "lyrics": (
            "lyrics",
            "show lyrics",
            "send lyrics",
            "song lyrics",
            "current lyrics",
            "lyrics for this",
            "lyrics for this song",
            "lyrics for this track",
            "show me the lyrics",
            "give me the lyrics",
            "what are the lyrics",
            "what is the lyrics",
        ),
    }

    PLAY_PREFIXES: tuple[str, ...] = (
        "play ",
        "pls play ",
        "please play ",
        "can you play ",
        "could you play ",
        "would you play ",
        "find and play ",
        "search and play ",
        "put on ",
        "queue up ",
        "queue ",
        "start playing ",
        "start ",
        "add ",
        "jit play ",
        "jit, play ",
        "jit put on ",
        "jit, put on ",
        "jit queue ",
        "jit, queue ",
        "play me ",
    )

    TURKISH_PLAY_PREFIXES: tuple[str, ...] = (
        "bir şarkı aç ",
        "şarkı aç ",
        "şunu çal ",
        "oynat ",
        "çal ",
        "aç ",
    )

    LYRICS_PREFIXES: tuple[str, ...] = (
        "lyrics ",
        "show lyrics ",
        "send lyrics ",
        "find lyrics ",
        "get lyrics ",
        "lyrics for ",
        "show lyrics for ",
        "send lyrics for ",
        "get lyrics for ",
        "find lyrics for ",
    )

    HELP_KEYWORDS: tuple[str, ...] = (
        "help",
        "commands",
        "komutlar",
        "yard\u0131m",
        "yardim",
    )

    PROFILE_KEYWORDS: tuple[str, ...] = (
        "profile",
        "rank",
        "xp",
        "level",
        "profil",
        "seviye",
    )

    PROFILE_LEADERBOARD_KEYWORDS: tuple[str, ...] = (
        "leaderboard",
        "topxp",
        "s\u0131ralama",
        "siralama",
        "liderlik",
    )

    AVATAR_KEYWORDS: tuple[str, ...] = (
        "avatar",
        "pfp",
        "pp",
        "profilfoto",
    )

    BANNER_KEYWORDS: tuple[str, ...] = (
        "banner",
        "afi\u015f",
        "afis",
    )

    USERINFO_KEYWORDS: tuple[str, ...] = (
        "userinfo",
        "user info",
        "kullan\u0131c\u0131bilgi",
        "kullanicibilgi",
    )

    TRANSLATE_PREFIXES: tuple[str, ...] = (
        "translate ",
        "tr ",
        "\u00e7evir ",
        "cevir ",
    )

    REWRITE_PREFIXES: tuple[str, ...] = (
        "rewrite ",
        "d\u00fczelt ",
        "duzelt ",
        "yenidenyaz ",
        "yeniden yaz ",
    )

    EXPLAIN_PREFIXES: tuple[str, ...] = (
        "explain ",
        "a\u00e7\u0131kla ",
        "acikla ",
        "basitanlat ",
        "basit anlat ",
    )

    ECONOMY_BALANCE_KEYWORDS: tuple[str, ...] = (
        "balance",
        "bal",
        "wallet",
        "money",
        "cash",
    )

    ECONOMY_RICHEST_KEYWORDS: tuple[str, ...] = (
        "richest",
        "topmoney",
        "moneylb",
    )

    ECONOMY_EXTRA_ACTION_KEYWORDS: tuple[str, ...] = (
        "freelance",
        "craft",
        "repair",
        "patrol",
    )

    GAMBLE_KEYWORDS: tuple[str, ...] = (
        "gamble",
        "bet",
        "coinflipbet",
    )

    BLACKJACK_KEYWORDS: tuple[str, ...] = (
        "blackjack",
        "bj",
    )

    SLOT_KEYWORDS: tuple[str, ...] = (
        "slots",
        "slot",
        "spin",
    )

    JOBS_KEYWORDS: tuple[str, ...] = (
        "jobs",
        "professions",
    )

    CURRENT_JOB_KEYWORDS: tuple[str, ...] = (
        "myjob",
        "currentjob",
    )

    JOB_UPGRADE_KEYWORDS: tuple[str, ...] = (
        "job upgrade",
        "level job",
        "upgrade job",
        "profession upgrade",
    )

    ACHIEVEMENT_KEYWORDS: tuple[str, ...] = (
        "achievements",
        "achivements",
        "achievement",
        "badges",
        "medals",
    )

    QUEST_KEYWORDS: tuple[str, ...] = (
        "quests",
        "missions",
        "dailyquests",
        "dailies",
        "quest",
    )

    INCOME_KEYWORDS: tuple[str, ...] = (
        "income",
        "passive",
        "property",
    )

    COLLECT_KEYWORDS: tuple[str, ...] = (
        "collect",
    )

    NOW_PLAYING_KEYWORDS: tuple[str, ...] = (
        "nowplaying",
        "now playing",
        "np",
        "current song",
        "what is playing",
        "what's playing",
        "what s playing",
        "\u015fimdi \u00e7alan",
        "simdi calan",
        "\u015fu an ne \u00e7al\u0131yor",
        "su an ne caliyor",
    )

    CLEAR_QUEUE_KEYWORDS: tuple[str, ...] = (
        "clearqueue",
        "clear queue",
        "queue clear",
        "clear list",
        "kuyru\u011fu temizle",
        "kuyrugu temizle",
        "s\u0131ray\u0131 temizle",
        "sirayi temizle",
    )

    HISTORY_KEYWORDS: tuple[str, ...] = (
        "history",
        "songs",
        "played",
        "ge\u00e7mi\u015f",
        "gecmis",
    )

    HISTORY_SELF_KEYWORDS: tuple[str, ...] = (
        "history me",
        "my history",
        "ge\u00e7mi\u015fim",
        "gecmisim",
        "\u015fark\u0131lar\u0131m",
        "sarkilarim",
    )

    MOST_PLAYED_KEYWORDS: tuple[str, ...] = (
        "mostplayed",
        "topplayed",
        "favorites",
        "favourites",
        "en \u00e7ok a\u00e7\u0131lanlar",
        "en cok acilanlar",
        "en \u00e7ok dinlenenler",
        "en cok dinlenenler",
    )

    MOST_PLAYED_SELF_KEYWORDS: tuple[str, ...] = (
        "mostplayed me",
        "topplayed me",
        "my mostplayed",
        "my favorites",
        "my favourites",
        "favorilerim",
        "en \u00e7ok \u00e7ald\u0131klar\u0131m",
        "en cok caldiklarim",
    )

    PLAYLIST_PLAY_PREFIXES: tuple[str, ...] = (
        "playlist ",
        "playlist play ",
        "liste oynat ",
        "\u00e7alma listesi ",
        "calma listesi ",
    )

    FILTER_CLEAR_KEYWORDS: tuple[str, ...] = (
        "filter off",
        "filters off",
        "reset filters",
        "clear filters",
        "filtreleri temizle",
        "filtreleri sıfırla",
        "filtreleri sifirla",
        "filtre kapat",
        "filtreleri kapat",
    )

    FILTER_SHOW_KEYWORDS: tuple[str, ...] = (
        "show filters",
        "current filters",
        "show current filters",
        "aktif filtreler",
        "filtreleri göster",
        "filtreleri goster",
    )

    FILTER_SIMPLE_ALIASES: dict[str, tuple[str, ...]] = {
        "bassboost": ("bassboost", "bass boost", "bassboost a\u00e7", "bassboost ac", "bass boost a\u00e7", "bass boost ac"),
        "slow": ("slow", "slow a\u00e7", "slow ac"),
        "reverb": ("reverb", "reverb a\u00e7", "reverb ac"),
        "echo": ("echo", "echo a\u00e7", "echo ac", "yank\u0131", "yank\u0131 a\u00e7", "yank\u0131 ac", "yanki", "yanki a\u00e7", "yanki ac"),
        "karaoke": ("karaoke", "karaoke a\u00e7", "karaoke ac"),
        "flanger": ("flanger",),
        "phaser": ("phaser",),
        "chorus": ("chorus",),
        "distortion": ("distortion",),
        "mono": ("mono",),
        "compressor": ("compressor",),
        "gate": ("gate",),
        "earrape": ("earrape",),
        "vaporwave": ("vaporwave",),
        "lofi": ("lofi",),
        "deep": ("deep",),
        "telephone": ("telephone",),
        "megaphone": ("megaphone",),
        "robot": ("robot", "robot a\u00e7", "robot ac"),
        "underwater": ("underwater",),
        "8d": ("8d", "8 d"),
    }

    FILTER_OFF_ALIASES: dict[str, tuple[str, ...]] = {
        "nightcore": ("nightcore off", "nightcore kapat"),
        "bassboost": ("bassboost off", "bass boost off", "bassboost kapat"),
        "slow": ("slow off", "slow kapat"),
        "speed": ("speed off", "speed kapat"),
        "pitch": ("pitch off", "pitch kapat"),
        "reverb": ("reverb off", "reverb kapat"),
        "echo": ("echo off", "echo kapat", "yank\u0131 kapat", "yanki kapat"),
        "karaoke": ("karaoke off", "karaoke kapat"),
        "tremolo": ("tremolo off", "tremolo kapat"),
        "vibrato": ("vibrato off", "vibrato kapat"),
        "flanger": ("flanger off", "flanger kapat"),
        "phaser": ("phaser off", "phaser kapat"),
        "chorus": ("chorus off", "chorus kapat"),
        "distortion": ("distortion off", "distortion kapat"),
        "lowpass": ("lowpass off", "lowpass kapat"),
        "highpass": ("highpass off", "highpass kapat"),
        "equalizer": ("equalizer off", "equalizer kapat"),
        "mono": ("mono off", "mono kapat"),
        "stereo_widen": ("stereo widen off", "stereo widen kapat"),
        "compressor": ("compressor off", "compressor kapat"),
        "gate": ("gate off", "gate kapat"),
        "volume_filter": ("volume off", "filter volume off", "effect volume off"),
        "earrape": ("earrape off", "earrape kapat"),
        "vaporwave": ("vaporwave off", "vaporwave kapat"),
        "lofi": ("lofi off", "lofi kapat"),
        "deep": ("deep off", "deep kapat"),
        "telephone": ("telephone off", "telephone kapat"),
        "megaphone": ("megaphone off", "megaphone kapat"),
        "robot": ("robot off", "robot kapat"),
        "underwater": ("underwater off", "underwater kapat"),
        "8d": ("8d off", "8 d off", "8d kapat"),
    }

    NUMBER_WORDS: dict[str, int] = {
        "zero": 0,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "fifteen": 15,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
        "nineteen": 19,
        "twenty": 20,
        "thirty": 30,
        "forty": 40,
        "fifty": 50,
        "sixty": 60,
        "seventy": 70,
        "eighty": 80,
        "ninety": 90,
        "hundred": 100,
        "max": 100,
        "maximum": 100,
        "full": 100,
        "half": 50,
        "quarter": 25,
    }

    COMMAND_KEYWORDS: dict[str, tuple[str, ...]] = {
        "join": ("join", "voice", "vc", "call", "summon", "come"),
        "leave": ("leave", "disconnect", "dc", "exit", "out"),
        "previous": ("previous", "last", "again", "back"),
        "skip": ("skip", "next"),
        "pause": ("pause", "hold"),
        "resume": ("resume", "continue", "unpause"),
        "stop": ("stop", "clear", "end"),
        "queue": ("queue", "playlist", "playing", "current"),
        "shuffle": ("shuffle", "mix", "randomize", "randomise"),
        "lyrics": ("lyrics",),
    }

    NEGATION_WORDS: tuple[str, ...] = (
        "dont",
        "don't",
        "do not",
        "not",
        "never",
        "no need",
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    @property
    def music_cog(self) -> Optional["Music"]:
        return self.bot.get_cog("Music")

    @property
    def community_cog(self) -> Optional["Community"]:
        return self.bot.get_cog("Community")

    # ---------------------------------------------------------------------
    # Normalization / text helpers
    # ---------------------------------------------------------------------
    def _normalize_text(self, text: str) -> str:
        text = (text or "").lower().strip()
        text = text.replace("â€™", "'")
        text = text.replace("pls", "please")
        text = text.replace(" u ", " you ")
        text = text.replace(" w/ ", " with ")
        text = text.replace("&", " and ")
        text = self._replace_number_words(text)
        text = re.sub(r"[^\w\s:/.%+\-']", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _replace_number_words(self, text: str) -> str:
        text = re.sub(r"\bseventy\s+five\b", "75", text, flags=re.IGNORECASE)
        text = re.sub(r"\bseventy\s+five\s+percent\b", "75 percent", text, flags=re.IGNORECASE)
        text = re.sub(r"\bfifty\s+five\b", "55", text, flags=re.IGNORECASE)
        text = re.sub(r"\bsixty\s+five\b", "65", text, flags=re.IGNORECASE)
        text = re.sub(r"\bforty\s+five\b", "45", text, flags=re.IGNORECASE)
        text = re.sub(r"\bthirty\s+five\b", "35", text, flags=re.IGNORECASE)
        text = re.sub(r"\btwenty\s+five\b", "25", text, flags=re.IGNORECASE)
        text = re.sub(r"\bninety\s+five\b", "95", text, flags=re.IGNORECASE)
        text = re.sub(r"\beighty\s+five\b", "85", text, flags=re.IGNORECASE)

        for word, value in sorted(self.NUMBER_WORDS.items(), key=lambda item: len(item[0]), reverse=True):
            text = re.sub(rf"\b{re.escape(word)}\b", str(value), text, flags=re.IGNORECASE)
        return text

    def _tokenize(self, text: str) -> list[str]:
        return [token for token in self._normalize_text(text).split() if token]

    def _seconds_to_timestamp(self, total_seconds: int) -> str:
        total_seconds = max(0, int(total_seconds))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    def _find_phrase_position(self, text: str, phrases: Iterable[str]) -> int:
        lowered = self._normalize_text(text)
        positions: list[int] = []
        for phrase in phrases:
            idx = lowered.find(self._normalize_text(phrase))
            if idx != -1:
                positions.append(idx)
        return min(positions) if positions else -1

    def _has_negation_near(self, text: str, phrase: str, window: int = 18) -> bool:
        normalized = self._normalize_text(text)
        phrase = self._normalize_text(phrase)
        idx = normalized.find(phrase)
        if idx == -1:
            return False
        left = normalized[max(0, idx - window):idx]
        return any(neg in left for neg in self.NEGATION_WORDS)

    def _phrase_similarity(self, a: str, b: str) -> float:
        return difflib.SequenceMatcher(None, a, b).ratio()

    # ---------------------------------------------------------------------
    # Play extraction
    # ---------------------------------------------------------------------
    def _clean_music_query(self, query: str) -> str:
        query = query.strip()
        lower = query.lower()

        noise_phrases = [
            " and keep the sound at ",
            " and keep sound at ",
            " and keep volume at ",
            " and keep the volume at ",
            " and set volume to ",
            " and set the volume to ",
            " and volume ",
            " and keep it loop ",
            " and keep it looping ",
            " and loop it ",
            " and repeat it ",
            " and put it on loop ",
            " and keep it in loop ",
            " and shuffle the queue ",
            " keep the sound at ",
            " keep sound at ",
            " keep volume at ",
            " keep the volume at ",
            " set volume to ",
            " set the volume to ",
        ]

        for phrase in noise_phrases:
            idx = lower.find(phrase)
            if idx != -1:
                query = query[:idx]
                lower = query.lower()
                break

        query = re.sub(
            r"\b(?:at|to)\s+\d{1,3}\s*(?:%|percent)\b",
            "",
            query,
            flags=re.IGNORECASE,
        )
        query = re.sub(
            r"\b(?:and\s+)?(?:keep|set|put)\s+(?:it|this|the song|the track)\s+(?:on\s+)?loop\b",
            "",
            query,
            flags=re.IGNORECASE,
        )
        query = re.sub(
            r"\b(?:and\s+)?repeat\s+(?:it|this|this song|the song|the track)\b",
            "",
            query,
            flags=re.IGNORECASE,
        )
        query = re.sub(
            r"\b(?:and\s+)?(?:shuffle|mix|randomize|randomise)\s+(?:the\s+)?queue\b",
            "",
            query,
            flags=re.IGNORECASE,
        )
        query = re.sub(
            r"\b(?:and\s+)?(?:skip\s+to|jump\s+to|go\s+to|seek\s+to)\s+\d{1,2}:\d{1,2}(?::\d{1,2})?\b",
            "",
            query,
            flags=re.IGNORECASE,
        )
        query = re.sub(
            r"\b(?:and\s+)?(?:skip\s+to|jump\s+to|go\s+to|seek\s+to)\s+\d+\b",
            "",
            query,
            flags=re.IGNORECASE,
        )
        query = re.sub(
            r"^(a song called as|a song called|song called as|song called|the song|track called)\s+",
            "",
            query,
            flags=re.IGNORECASE,
        )
        query = re.sub(r"^(please|pls|hey|yo)\s+", "", query, flags=re.IGNORECASE)
        query = re.sub(r"\s+for me$", "", query, flags=re.IGNORECASE)

        return query.strip(" ?!.,:")

    def _extract_turkish_play_query_fast(self, text: str) -> Optional[str]:
        raw = text.lstrip()
        lower = raw.lower()

        for prefix in self.TURKISH_PLAY_PREFIXES:
            if lower.startswith(prefix):
                return raw[len(prefix):].strip()

        bare_prefixes = tuple(prefix.rstrip() for prefix in self.TURKISH_PLAY_PREFIXES)
        for prefix in bare_prefixes:
            if lower.strip() == prefix:
                return ""

        return None

    def _extract_playback_mode_command_fast(self, text: str) -> Optional[IntentResult]:
        raw = (text or "").strip()
        if not raw:
            return None

        lowered = raw.lower()
        nightcore_match = re.fullmatch(r"nightcore(?:\s+(\d+(?:[.,]\d+)?))?", lowered)
        if nightcore_match:
            meta: dict = {}
            speed_raw = nightcore_match.group(1)
            if speed_raw:
                try:
                    meta["playback_rate"] = float(speed_raw.replace(",", "."))
                except ValueError:
                    meta = {}
            return IntentResult("playback_preset", arg="nightcore", confidence=0.99, start=0, meta=meta)

        return None

    def _extract_help_command_fast(self, text: str) -> Optional[IntentResult]:
        normalized = self._normalize_text(text)
        for keyword in self.HELP_KEYWORDS:
            keyword_n = self._normalize_text(keyword)
            if normalized == keyword_n:
                return IntentResult("help", confidence=0.99, start=0)
            if normalized.startswith(f"{keyword_n} "):
                return IntentResult("help", arg=normalized[len(keyword_n):].strip(), confidence=0.99, start=0)
        return None

    def _extract_now_playing_command_fast(self, text: str) -> Optional[IntentResult]:
        normalized = self._normalize_text(text)
        for keyword in self.NOW_PLAYING_KEYWORDS:
            if normalized == self._normalize_text(keyword):
                return IntentResult("now_playing", confidence=0.99, start=0)
        return None

    def _extract_clear_queue_command_fast(self, text: str) -> Optional[IntentResult]:
        normalized = self._normalize_text(text)
        for keyword in self.CLEAR_QUEUE_KEYWORDS:
            if normalized == self._normalize_text(keyword):
                return IntentResult("clear_queue", confidence=0.99, start=0)
        return None

    def _extract_playlist_play_query_fast(self, text: str) -> Optional[str]:
        raw = (text or "").strip()
        if not raw:
            return None

        lowered = raw.lower().strip()
        for prefix in self.PLAYLIST_PLAY_PREFIXES:
            if lowered.startswith(prefix):
                query = raw[len(prefix):].strip()
                if query and _looks_like_media_urlish(query):
                    return query
        return None

    def _extract_user_history_style_intent_from_message(
        self,
        message: discord.Message,
        *,
        intent_name: str,
        keywords: tuple[str, ...],
        self_keywords: tuple[str, ...],
    ) -> Optional[IntentResult]:
        raw = (message.content or "").strip()
        if not raw:
            return None

        mentionless = raw
        for user in message.mentions:
            mentionless = mentionless.replace(f"<@{user.id}>", " ")
            mentionless = mentionless.replace(f"<@!{user.id}>", " ")

        normalized = self._normalize_text(mentionless)
        if not normalized:
            return None

        def matches_keyword(keyword: str) -> bool:
            keyword_n = self._normalize_text(keyword)
            return normalized == keyword_n or normalized.startswith(f"{keyword_n} ")

        is_primary = any(matches_keyword(keyword) for keyword in keywords)
        is_self_primary = any(matches_keyword(keyword) for keyword in self_keywords)
        if not is_primary and not is_self_primary:
            return None

        page = 1
        match = re.search(r"\b(?:page|sayfa)\s+(\d+)\b", normalized)
        if match:
            page = max(1, int(match.group(1)))
        else:
            trailing = re.search(r"\b(\d+)\b\s*$", normalized)
            if trailing:
                page = max(1, int(trailing.group(1)))

        target_user = message.author if is_self_primary or not message.mentions else message.mentions[0]
        return IntentResult(
            intent_name,
            confidence=0.99,
            start=0,
            meta={"target_user": target_user, "page": page},
        )

    def _extract_history_intent_from_message(self, message: discord.Message) -> Optional[IntentResult]:
        return self._extract_user_history_style_intent_from_message(
            message,
            intent_name="history",
            keywords=self.HISTORY_KEYWORDS,
            self_keywords=self.HISTORY_SELF_KEYWORDS,
        )

    def _extract_most_played_intent_from_message(self, message: discord.Message) -> Optional[IntentResult]:
        return self._extract_user_history_style_intent_from_message(
            message,
            intent_name="most_played",
            keywords=self.MOST_PLAYED_KEYWORDS,
            self_keywords=self.MOST_PLAYED_SELF_KEYWORDS,
        )

    def _strip_mentions_from_message_text(self, message: discord.Message) -> str:
        raw = (message.content or "").strip()
        cleaned = raw
        for user in message.mentions:
            cleaned = cleaned.replace(f"<@{user.id}>", " ")
            cleaned = cleaned.replace(f"<@!{user.id}>", " ")
        return cleaned

    def _extract_page_from_normalized(self, normalized: str) -> int:
        match = re.search(r"\b(?:page|sayfa)\s+(\d+)\b", normalized)
        if match:
            return max(1, int(match.group(1)))
        trailing = re.search(r"\b(\d+)\b\s*$", normalized)
        if trailing:
            return max(1, int(trailing.group(1)))
        return 1

    def _extract_targeted_exact_intent_from_message(
        self,
        message: discord.Message,
        *,
        intent_name: str,
        keywords: tuple[str, ...],
        default_to_author: bool = True,
        include_page: bool = False,
    ) -> Optional[IntentResult]:
        mentionless = self._strip_mentions_from_message_text(message)
        normalized = self._normalize_text(mentionless)
        if not normalized:
            return None

        for keyword in keywords:
            keyword_n = self._normalize_text(keyword)
            if normalized == keyword_n or normalized.startswith(f"{keyword_n} "):
                meta: dict[str, Any] = {}
                if default_to_author:
                    meta["target_user"] = message.mentions[0] if message.mentions else message.author
                elif message.mentions:
                    meta["target_user"] = message.mentions[0]
                if include_page:
                    meta["page"] = self._extract_page_from_normalized(normalized)
                return IntentResult(intent_name, confidence=0.99, start=0, meta=meta)
        return None

    def _extract_prefixed_community_intent(
        self,
        message: discord.Message,
        *,
        intent_name: str,
        prefixes: tuple[str, ...],
    ) -> Optional[IntentResult]:
        raw = (message.content or "").strip()
        lowered = raw.lower()
        for prefix in prefixes:
            if lowered.startswith(prefix):
                return IntentResult(
                    intent_name,
                    arg=raw[len(prefix):].strip(),
                    confidence=0.99,
                    start=0,
                )
        return None

    def _extract_community_intent_from_message(self, message: discord.Message) -> Optional[IntentResult]:
        intent = self._extract_targeted_exact_intent_from_message(
            message,
            intent_name="profile",
            keywords=self.PROFILE_KEYWORDS,
        )
        if intent is not None:
            return intent

        intent = self._extract_targeted_exact_intent_from_message(
            message,
            intent_name="xp_leaderboard",
            keywords=self.PROFILE_LEADERBOARD_KEYWORDS,
            default_to_author=False,
            include_page=True,
        )
        if intent is not None:
            return intent

        intent = self._extract_targeted_exact_intent_from_message(
            message,
            intent_name="avatar",
            keywords=self.AVATAR_KEYWORDS,
        )
        if intent is not None:
            return intent

        intent = self._extract_targeted_exact_intent_from_message(
            message,
            intent_name="banner",
            keywords=self.BANNER_KEYWORDS,
        )
        if intent is not None:
            return intent

        intent = self._extract_targeted_exact_intent_from_message(
            message,
            intent_name="userinfo",
            keywords=self.USERINFO_KEYWORDS,
        )
        if intent is not None:
            return intent

        intent = self._extract_prefixed_community_intent(
            message,
            intent_name="translate",
            prefixes=self.TRANSLATE_PREFIXES,
        )
        if intent is not None:
            return intent

        intent = self._extract_prefixed_community_intent(
            message,
            intent_name="rewrite",
            prefixes=self.REWRITE_PREFIXES,
        )
        if intent is not None:
            return intent

        intent = self._extract_prefixed_community_intent(
            message,
            intent_name="explain",
            prefixes=self.EXPLAIN_PREFIXES,
        )
        if intent is not None:
            return intent

        intent = self._extract_targeted_exact_intent_from_message(
            message,
            intent_name="balance",
            keywords=self.ECONOMY_BALANCE_KEYWORDS,
        )
        if intent is not None:
            return intent

        intent = self._extract_targeted_exact_intent_from_message(
            message,
            intent_name="richest",
            keywords=self.ECONOMY_RICHEST_KEYWORDS,
            default_to_author=False,
            include_page=True,
        )
        if intent is not None:
            return intent

        normalized = self._normalize_text(self._strip_mentions_from_message_text(message))
        raw = (message.content or "").strip()

        if normalized in {"ping", "uptime", "mystats", "dungeonstats", "casinostats", "jobstats", "winrate", "lossrate", "mostused", "playtime", "accept", "decline", "divorce", "love"}:
            mapping = {
                "ping": "ping",
                "uptime": "uptime",
                "mystats": "mystats",
                "dungeonstats": "dungeonstats",
                "casinostats": "casinostats",
                "jobstats": "jobstats",
                "winrate": "winrate",
                "lossrate": "lossrate",
                "mostused": "mostused",
                "playtime": "playtime",
                "accept": "accept_marriage",
                "decline": "decline_marriage",
                "divorce": "divorce",
                "love": "love",
            }
            return IntentResult(mapping[normalized], confidence=0.99, start=0)

        if normalized in {"spouse", "marriage", "marriageprofile"}:
            mapping = {
                "spouse": "spouse",
                "marriage": "marriage",
                "marriageprofile": "marriageprofile",
            }
            return IntentResult(
                mapping[normalized],
                confidence=0.99,
                start=0,
                meta={"target_user": message.mentions[0] if message.mentions else message.author},
            )

        leaderboard_match = re.match(r"^(topdungeon|topgamblers|topwins|toplosses)(?:\s+(\d+))?$", normalized, flags=re.IGNORECASE)
        if leaderboard_match:
            return IntentResult(
                leaderboard_match.group(1).lower(),
                confidence=0.99,
                start=0,
                meta={"page": int(leaderboard_match.group(2) or 1)},
            )

        if normalized == "notes list":
            return IntentResult("notes_list", confidence=0.99, start=0)

        notes_add_match = re.match(r"^notes\s+add\s+(.+)$", raw, flags=re.IGNORECASE)
        if notes_add_match:
            return IntentResult("notes_add", arg=notes_add_match.group(1).strip(), confidence=0.99, start=0)

        notes_delete_match = re.match(r"^notes\s+delete\s+(\d+)$", raw, flags=re.IGNORECASE)
        if notes_delete_match:
            return IntentResult(
                "notes_delete",
                confidence=0.99,
                start=0,
                meta={"note_id": int(notes_delete_match.group(1))},
            )

        calc_match = re.match(r"^calc\s+(.+)$", raw, flags=re.IGNORECASE)
        if calc_match:
            return IntentResult("calc", arg=calc_match.group(1).strip(), confidence=0.99, start=0)

        timer_match = re.match(r"^timer\s+(.+)$", raw, flags=re.IGNORECASE)
        if timer_match:
            return IntentResult("timer", arg=timer_match.group(1).strip(), confidence=0.99, start=0)

        remind_match = re.match(r"^remind\s+(.+)$", raw, flags=re.IGNORECASE)
        if remind_match:
            return IntentResult("remind", arg=remind_match.group(1).strip(), confidence=0.99, start=0)

        if normalized.startswith("summarize "):
            return IntentResult("summarize", arg=raw[len("summarize "):].strip(), confidence=0.99, start=0)

        if normalized.startswith("keywords "):
            return IntentResult("keywords", arg=raw[len("keywords "):].strip(), confidence=0.99, start=0)

        if normalized.startswith("fix "):
            return IntentResult("fix", arg=raw[len("fix "):].strip(), confidence=0.99, start=0)

        if normalized.startswith("shorten "):
            return IntentResult("shorten", arg=raw[len("shorten "):].strip(), confidence=0.99, start=0)

        if normalized.startswith("expand "):
            return IntentResult("expand", arg=raw[len("expand "):].strip(), confidence=0.99, start=0)

        tone_match = re.match(r"^tone\s+(casual|formal)\s+(.+)$", raw, flags=re.IGNORECASE)
        if tone_match:
            return IntentResult(
                "tone",
                confidence=0.99,
                start=0,
                meta={"mode": tone_match.group(1).lower()},
                arg=tone_match.group(2).strip(),
            )

        if re.match(r"^(?:marry|propose)\b", raw, flags=re.IGNORECASE):
            return IntentResult(
                "marry" if normalized.startswith("marry") else "propose",
                confidence=0.99,
                start=0,
                meta={"target_user": message.mentions[0] if message.mentions else None},
            )

        if normalized in self.JOBS_KEYWORDS:
            return IntentResult("jobs", confidence=0.99, start=0)

        if normalized in self.CURRENT_JOB_KEYWORDS:
            return IntentResult("current_job", confidence=0.99, start=0)

        if normalized in self.JOB_UPGRADE_KEYWORDS:
            return IntentResult("job_upgrade", confidence=0.99, start=0)

        if normalized in self.ACHIEVEMENT_KEYWORDS:
            return IntentResult("achievements", confidence=0.99, start=0)

        if normalized in self.QUEST_KEYWORDS:
            return IntentResult("quests", confidence=0.99, start=0)

        if normalized in self.INCOME_KEYWORDS:
            return IntentResult("income", confidence=0.99, start=0)

        if normalized in self.COLLECT_KEYWORDS:
            return IntentResult("collect", confidence=0.99, start=0)

        choose_job_match = re.match(r"^choosejob\s+(.+)$", raw, flags=re.IGNORECASE)
        if choose_job_match:
            return IntentResult("choose_job", arg=choose_job_match.group(1).strip(), confidence=0.99, start=0)

        job_choose_match = re.match(r"^job\s+choose\s+(.+)$", raw, flags=re.IGNORECASE)
        if job_choose_match:
            return IntentResult("choose_job", arg=job_choose_match.group(1).strip(), confidence=0.99, start=0)

        job_upgrade_match = re.match(r"^job\s+upgrade$", raw, flags=re.IGNORECASE)
        if job_upgrade_match:
            return IntentResult("job_upgrade", confidence=0.99, start=0)

        direct_job_match = re.match(r"^job\s+(.+)$", raw, flags=re.IGNORECASE)
        if direct_job_match:
            return IntentResult("choose_job", arg=direct_job_match.group(1).strip(), confidence=0.99, start=0)

        if normalized in {"work", "beg", "quiz", "mathquiz", "daily", "dailyreward", "shop", "store", "market", "shopview", "inventory", "inv", "sellall", "sell all", "earn", "quickearn", "workpanel", "jobs panel", "drawgame", "hangman", "wordchain", "chainword", "trivia", "trivia start", "quizgame", "hint", "reveal", "enddrawgame"}:
            mapping = {
                "work": "work",
                "beg": "beg",
                "quiz": "quiz",
                "mathquiz": "quiz",
                "daily": "daily",
                "dailyreward": "daily",
                "shop": "shop",
                "store": "shop",
                "market": "shop",
                "shopview": "shopview",
                "inventory": "inventory",
                "inv": "inventory",
                "sellall": "sellall",
                "sell all": "sellall",
                "earn": "quick_earn",
                "quickearn": "quick_earn",
                "workpanel": "quick_earn",
                "jobs panel": "quick_earn",
                "drawgame": "drawgame",
                "hangman": "hangman",
                "wordchain": "wordchain",
                "chainword": "wordchain",
                "trivia": "trivia",
                "trivia start": "trivia",
                "quizgame": "trivia",
                "hint": "drawgame_hint",
                "reveal": "enddrawgame",
                "enddrawgame": "enddrawgame",
            }
            return IntentResult(mapping[normalized], confidence=0.99, start=0)

        if normalized in {"pets", "petshop", "mypet", "unequippet", "feedpet", "petinfo"}:
            mapping = {
                "pets": "pets",
                "petshop": "petshop",
                "mypet": "mypet",
                "unequippet": "unequippet",
                "feedpet": "feedpet",
                "petinfo": "petinfo",
            }
            return IntentResult(mapping[normalized], confidence=0.99, start=0)

        if normalized in self.ECONOMY_EXTRA_ACTION_KEYWORDS:
            return IntentResult(normalized, confidence=0.99, start=0)

        if normalized.startswith("answer "):
            return IntentResult("answer_quiz", arg=raw[len("answer "):].strip(), confidence=0.99, start=0)

        if normalized.startswith("buypet "):
            return IntentResult("buypet", arg=raw[len("buypet "):].strip(), confidence=0.99, start=0)

        if normalized.startswith("equippet "):
            return IntentResult("equippet", arg=raw[len("equippet "):].strip(), confidence=0.99, start=0)

        if normalized.startswith("buy "):
            return IntentResult("buy", arg=raw[len("buy "):].strip(), confidence=0.99, start=0)

        if normalized.startswith("sell "):
            return IntentResult("sell", arg=raw[len("sell "):].strip(), confidence=0.99, start=0)

        if normalized.startswith("use "):
            return IntentResult("use_item", arg=raw[len("use "):].strip(), confidence=0.99, start=0)

        if normalized in {"fish", "hunt", "search", "mine", "deliver", "scavenge"}:
            return IntentResult(normalized, confidence=0.99, start=0)

        gamble_match = re.match(r"^(?:gamble|bet|coinflipbet)\s+(\d+)$", raw, flags=re.IGNORECASE)
        if gamble_match:
            return IntentResult(
                "gamble",
                confidence=0.99,
                start=0,
                meta={"amount": int(gamble_match.group(1))},
            )

        blackjack_pvp_match = re.match(r"^(?:blackjack|bj)\b.+\b(\d+)$", raw, flags=re.IGNORECASE)
        if blackjack_pvp_match and message.mentions:
            return IntentResult(
                "blackjack",
                confidence=0.99,
                start=0,
                meta={
                    "amount": int(blackjack_pvp_match.group(1)),
                    "target_user": message.mentions[0],
                },
            )

        blackjack_match = re.match(r"^(?:blackjack|bj)\s+(\d+)$", raw, flags=re.IGNORECASE)
        if blackjack_match:
            return IntentResult(
                "blackjack",
                confidence=0.99,
                start=0,
                meta={"amount": int(blackjack_match.group(1))},
            )

        coinflip_match = re.match(r"^(?:coinflip|cf)\b.+\b(\d+)$", raw, flags=re.IGNORECASE)
        if coinflip_match:
            return IntentResult(
                "coinflip",
                confidence=0.99,
                start=0,
                meta={
                    "target_user": message.mentions[0] if message.mentions else None,
                    "amount": int(coinflip_match.group(1)),
                },
            )

        slot_match = re.match(r"^(?:slots|slot|spin)\s+(\d+)$", raw, flags=re.IGNORECASE)
        if slot_match:
            return IntentResult(
                "slots",
                confidence=0.99,
                start=0,
                meta={"amount": int(slot_match.group(1))},
            )

        crash_match = re.match(r"^crash\s+(\d+)$", raw, flags=re.IGNORECASE)
        if crash_match:
            return IntentResult(
                "crash",
                confidence=0.99,
                start=0,
                meta={"amount": int(crash_match.group(1))},
            )

        guess_match = re.match(r"^guess\s+(\d+)$", raw, flags=re.IGNORECASE)
        if guess_match:
            return IntentResult(
                "guess",
                confidence=0.99,
                start=0,
                meta={"amount": int(guess_match.group(1))},
            )

        duel_match = re.match(r"^duel\b.+\b(\d+)$", raw, flags=re.IGNORECASE)
        if duel_match:
            return IntentResult(
                "duel",
                confidence=0.99,
                start=0,
                meta={
                    "target_user": message.mentions[0] if message.mentions else None,
                    "amount": int(duel_match.group(1)),
                },
            )

        dungeon_match = re.match(r"^(?:dungeon\s+run|dungeon|pve)\s+(\d+)$", raw, flags=re.IGNORECASE)
        if dungeon_match:
            return IntentResult(
                "dungeon",
                confidence=0.99,
                start=0,
                meta={"amount": int(dungeon_match.group(1))},
            )

        pvp_match = re.match(r"^(heist|rob|steal)\b", raw, flags=re.IGNORECASE)
        if pvp_match:
            return IntentResult(
                pvp_match.group(1).lower(),
                confidence=0.99,
                start=0,
                meta={"target_user": message.mentions[0] if message.mentions else None},
            )

        purge_match = re.match(r"^purge\s+(\d+)$", raw, flags=re.IGNORECASE)
        if purge_match:
            return IntentResult(
                "purge",
                confidence=0.99,
                start=0,
                meta={"amount": int(purge_match.group(1))},
            )

        givemoney_match = re.match(r"^givemoney\b.+\b(-?\d+)$", raw, flags=re.IGNORECASE)
        if givemoney_match:
            return IntentResult(
                "givemoney",
                confidence=0.99,
                start=0,
                meta={
                    "target_user": message.mentions[0] if message.mentions else None,
                    "amount": int(givemoney_match.group(1)),
                },
            )

        if normalized.startswith("gift "):
            amount_match = re.search(r"\b(\d+)\b", normalized)
            amount = int(amount_match.group(1)) if amount_match else 0
            return IntentResult(
                "gift",
                confidence=0.99,
                start=0,
                meta={
                    "target_user": message.mentions[0] if message.mentions else None,
                    "amount": amount,
                },
            )

        return None

    def _extract_filter_command_fast(self, text: str) -> Optional[IntentResult]:
        raw = (text or "").strip()
        if not raw:
            return None

        normalized = self._normalize_text(raw)

        for keyword in self.FILTER_CLEAR_KEYWORDS:
            if normalized == self._normalize_text(keyword):
                return IntentResult("filter_control", arg="clear", confidence=0.99, start=0)

        for keyword in self.FILTER_SHOW_KEYWORDS:
            if normalized == self._normalize_text(keyword):
                return IntentResult("filter_control", arg="show", confidence=0.99, start=0)

        for effect_name, aliases in self.FILTER_OFF_ALIASES.items():
            for alias in aliases:
                if normalized == self._normalize_text(alias):
                    return IntentResult(
                        "filter_control",
                        arg="off",
                        confidence=0.99,
                        start=0,
                        meta={"effect_name": effect_name},
                    )

        parameter_patterns: tuple[tuple[str, str], ...] = (
            (r"^nightcore(?:\s+(\d+(?:[.,]\d+)?))?(?:\s+(?:on|a\u00e7|ac))?$", "nightcore"),
            (r"^speed\s+(\d+(?:[.,]\d+)?)$", "speed"),
            (r"^pitch\s+(\d+(?:[.,]\d+)?)$", "pitch"),
            (r"^tremolo(?:\s+(\d+(?:[.,]\d+)?))?(?:\s+(\d+(?:[.,]\d+)?))?$", "tremolo"),
            (r"^vibrato(?:\s+(\d+(?:[.,]\d+)?))?(?:\s+(\d+(?:[.,]\d+)?))?$", "vibrato"),
            (r"^lowpass\s+(\d+(?:[.,]\d+)?)$", "lowpass"),
            (r"^highpass\s+(\d+(?:[.,]\d+)?)$", "highpass"),
            (r"^equalizer\s+(\d+(?:[.,]\d+)?)\s+(-?\d+(?:[.,]\d+)?)$", "equalizer"),
            (r"^stereo widen(?:\s+(\d+(?:[.,]\d+)?))?$", "stereo_widen"),
            (r"^(?:filter|effect)\s+volume\s+(\d+(?:[.,]\d+)?)$", "volume_filter"),
        )

        for pattern, effect_name in parameter_patterns:
            match = re.fullmatch(pattern, normalized)
            if match:
                params = [group for group in match.groups() if group is not None]
                return IntentResult(
                    "filter",
                    arg=effect_name,
                    confidence=0.99,
                    start=0,
                    meta={"params": params},
                )

        for effect_name, aliases in self.FILTER_SIMPLE_ALIASES.items():
            for alias in aliases:
                if normalized == self._normalize_text(alias):
                    return IntentResult(
                        "filter",
                        arg=effect_name,
                        confidence=0.99,
                        start=0,
                        meta={"params": []},
                    )

        return None

    def _matches_command_phrases(self, normalized: str, phrases: Iterable[str]) -> bool:
        for phrase in phrases:
            phrase_normalized = self._normalize_text(phrase)
            if normalized == phrase_normalized or normalized.startswith(f"{phrase_normalized} "):
                return True
        return False

    def _extract_turkish_volume_number_fast(self, text: str) -> Optional[int]:
        normalized = self._normalize_text(text)
        for pattern in (
            r"%\s*(\d{1,3})",
            r"(\d{1,3})\s*%",
            r"\b(\d{1,3})\b",
        ):
            match = re.search(pattern, normalized)
            if match:
                try:
                    return max(0, min(int(match.group(1)), 100))
                except ValueError:
                    return None
        return None

    def _extract_turkish_loop_mode_fast(self, text: str) -> Optional[str]:
        normalized = self._normalize_text(text)

        off_phrases = (
            "döngüyü kapat",
            "tekrarı kapat",
            "loop kapat",
            "döngü kapat",
            "tekrar kapat",
        )
        if self._matches_command_phrases(normalized, off_phrases):
            return "off"

        queue_phrases = (
            "listeyi döngüye al",
            "kuyruğu döngüye al",
            "hepsini döngüye al",
            "tüm listeyi tekrara al",
            "queue döngü",
        )
        if self._matches_command_phrases(normalized, queue_phrases):
            return "queue"

        track_phrases = (
            "döngü",
            "döngüye al",
            "tekrara al",
            "şarkıyı döngüye al",
            "şarkıyı tekrara al",
            "bunu döngüye al",
            "loop aç",
        )
        if self._matches_command_phrases(normalized, track_phrases):
            return "track"

        return None

    def _extract_turkish_volume_command_fast(self, text: str) -> Optional[IntentResult]:
        normalized = self._normalize_text(text)

        if self._matches_command_phrases(normalized, ("unmute", "sesi geri aç")):
            return IntentResult(
                "volume",
                arg="100",
                confidence=0.99,
                start=0,
                meta={"volume_percent": 100},
            )

        if self._matches_command_phrases(normalized, ("sessize al", "mute", "sesi kapat")):
            return IntentResult(
                "volume",
                arg="0",
                confidence=0.99,
                start=0,
                meta={"volume_percent": 0},
            )

        absolute_patterns = (
            r"\b(?:ses|volume)\s+%?\s*(\d{1,3})(?:\s*%)?\b",
            r"\b(?:sesi|ses seviyesini)\s+%?\s*(\d{1,3})(?:\s*%)?(?:\s*[' ]?ye)?\s+(?:getir|yap)\b",
        )
        for pattern in absolute_patterns:
            match = re.search(pattern, normalized)
            if match:
                try:
                    value = max(0, min(int(match.group(1)), 100))
                except ValueError:
                    return None
                return IntentResult(
                    "volume",
                    arg=str(value),
                    confidence=0.99,
                    start=0,
                    meta={"volume_percent": value},
                )

        down_phrases = (
            "sesi azalt",
            "sesi kıs",
            "kıs",
            "azalt",
            "biraz kıs",
        )
        if self._matches_command_phrases(normalized, down_phrases):
            value = self._extract_turkish_volume_number_fast(normalized)
            delta = -(value if value is not None else 10)
            return IntentResult(
                "volume",
                confidence=0.99,
                start=0,
                meta={"volume_delta": delta},
            )

        up_phrases = (
            "sesi yükselt",
            "sesi aç",
            "yükselt",
            "artır",
            "arttir",
            "sesi arttır",
            "biraz aç",
        )
        if self._matches_command_phrases(normalized, up_phrases):
            value = self._extract_turkish_volume_number_fast(normalized)
            delta = value if value is not None else 10
            return IntentResult(
                "volume",
                confidence=0.99,
                start=0,
                meta={"volume_delta": delta},
            )

        return None

    def _detect_turkish_intent_fast(self, text: str) -> IntentResult:
        help_intent = self._extract_help_command_fast(text)
        if help_intent is not None:
            return help_intent

        now_playing_intent = self._extract_now_playing_command_fast(text)
        if now_playing_intent is not None:
            return now_playing_intent

        clear_queue_intent = self._extract_clear_queue_command_fast(text)
        if clear_queue_intent is not None:
            return clear_queue_intent

        filter_intent = self._extract_filter_command_fast(text)
        if filter_intent is not None:
            return filter_intent

        playlist_query = self._extract_playlist_play_query_fast(text)
        if playlist_query:
            return IntentResult("play", arg=playlist_query, confidence=0.99, start=0)

        play_query = self._extract_turkish_play_query_fast(text)
        if play_query is not None:
            return IntentResult("play", arg=play_query or None, confidence=0.99, start=0)

        volume_intent = self._extract_turkish_volume_command_fast(text)
        if volume_intent is not None:
            return volume_intent

        loop_mode = self._extract_turkish_loop_mode_fast(text)
        if loop_mode is not None:
            return IntentResult("loop", arg=loop_mode, confidence=0.99, start=0)

        normalized = self._normalize_text(text)
        command_phrases: tuple[tuple[tuple[str, ...], str], ...] = (
            (("geç", "sonraki", "sonrakine geç", "şarkıyı geç", "bunu geç", "atla"), "skip"),
            (("durdur", "müziği durdur", "kapat", "müziği kapat", "bitir", "çalmayı durdur"), "stop"),
            (("duraklat", "beklet", "müziği duraklat", "şarkıyı duraklat"), "pause"),
            (("devam et", "devam", "sürdür", "kaldığı yerden devam et", "müziği devam ettir"), "resume"),
            (("çık", "ayrıl", "kanaldan çık", "sesten çık", "voice'dan çık", "voice dan çık", "vc'den çık", "vc den çık", "kanaldan ayrıl"), "leave"),
            (("katıl", "gel", "kanala gel", "sese gel", "voice'a gel", "voice a gel", "vc'ye gel", "vc ye gel", "kanala katıl"), "join"),
            (("kuyruk", "liste", "çalma listesi", "sırada ne var", "ne çalıyor", "şu an ne çalıyor", "sırayı göster"), "queue"),
            (("karıştır", "listeyi karıştır", "kuyruğu karıştır"), "shuffle"),
        )

        for phrases, intent in command_phrases:
            if self._matches_command_phrases(normalized, phrases):
                return IntentResult(intent, confidence=0.99, start=0)

        return IntentResult("chat", confidence=0.0)

    def _extract_play_query_fast(self, text: str) -> Optional[str]:
        raw = text.strip()
        lower = raw.lower().strip()

        # Do not treat explicit previous/queue-only commands as play requests.
        excluded_starts = (
            "play previous",
            "play the previous",
            "play last",
            "play the last",
            "play it again",
        )
        if lower.startswith(excluded_starts):
            return None

        for prefix in self.PLAY_PREFIXES:
            if lower.startswith(prefix):
                query = raw[len(prefix):].strip(" ?!.,")
                query = self._clean_music_query(query)
                return query or None

        patterns = [
            r"^(?:hey\s+|yo\s+)?(?:jit[\s,]+)?play\s+(.+)$",
            r"^(?:hey\s+|yo\s+)?(?:jit[\s,]+)?put on\s+(.+)$",
            r"^(?:hey\s+|yo\s+)?(?:jit[\s,]+)?queue up\s+(.+)$",
            r"^(?:hey\s+|yo\s+)?(?:jit[\s,]+)?queue\s+(.+)$",
            r"^(?:hey\s+|yo\s+)?(?:jit[\s,]+)?start playing\s+(.+)$",
            r"^(?:can you|could you|would you|please)\s+(?:find and )?play\s+(.+)$",
            r"^(?:can you|could you|would you)\s+put on\s+(.+)$",
            r"^(?:add)\s+(.+)\s+to\s+the\s+queue$",
            r"^(?:search for)\s+(.+)\s+and\s+play(?: it)?$",
        ]

        for pattern in patterns:
            match = re.search(pattern, lower)
            if match:
                start = match.start(1)
                query = raw[start:].strip(" ?!.,")
                query = self._clean_music_query(query)
                return query or None

        if re.match(r"^https?://", raw, flags=re.IGNORECASE):
            return raw

        return None

    # ---------------------------------------------------------------------
    # Lyrics extraction
    # ---------------------------------------------------------------------
    def _extract_lyrics_query_fast(self, text: str) -> Optional[str]:
        raw = text.strip()
        lower = raw.lower().strip()

        for prefix in self.LYRICS_PREFIXES:
            if lower.startswith(prefix):
                query = raw[len(prefix):].strip(" ?!.,:")
                return query or None

        patterns = [
            r"^(?:show me|give me|find|get)\s+the\s+lyrics\s+(?:for\s+)?(.+)$",
            r"^what are the lyrics (?:for|to)\s+(.+)$",
            r"^lyrics of\s+(.+)$",
            r"^lyrics to\s+(.+)$",
            r"^can you show lyrics for\s+(.+)$",
            r"^find the lyrics for\s+(.+)$",
        ]

        for pattern in patterns:
            match = re.search(pattern, lower)
            if match:
                start = match.start(1)
                query = raw[start:].strip(" ?!.,:")
                return query or None

        return None

    # ---------------------------------------------------------------------
    # Volume understanding
    # ---------------------------------------------------------------------
    def _looks_like_volume_command(self, text: str) -> bool:
        normalized = self._normalize_text(text)

        direct_phrases = (
            "volume",
            "mute",
            "unmute",
            "turn it up",
            "turn it down",
            "increase volume",
            "decrease volume",
            "lower volume",
            "raise volume",
            "set volume",
            "keep volume",
            "set the volume",
            "keep the volume",
            "set sound to",
            "keep sound at",
            "keep the sound at",
            "make it louder",
            "make it quieter",
            "louder",
            "quieter",
            "reduce the sound",
            "boost the sound",
            "max volume",
            "full volume",
            "half volume",
        )
        if any(phrase in normalized for phrase in direct_phrases):
            return True

        has_percent = bool(re.search(r"\b\d{1,3}\s*(?:%|percent)\b", normalized))
        has_sound_control_word = any(
            word in normalized
            for word in ("sound", "volume", "loud", "quiet", "louder", "quieter")
        )

        return has_percent and has_sound_control_word

    def _extract_volume_percent_fast(self, text: str) -> Optional[int]:
        normalized = self._normalize_text(text)

        if "mute" in normalized and "unmute" not in normalized:
            return 0
        if "unmute" in normalized:
            return 100
        if "max volume" in normalized or "maximum volume" in normalized or "full volume" in normalized:
            return 100
        if "half volume" in normalized:
            return 50
        if "quarter volume" in normalized:
            return 25

        patterns = [
            r"\b(?:set|keep|make|put)\s+(?:the\s+)?(?:volume|sound)\s+(?:to|at)\s+(\d{1,3})\b",
            r"\b(?:volume|sound)\s+(?:to|at)\s+(\d{1,3})\b",
            r"\b(?:volume|sound)\s+(\d{1,3})\b",
            r"\bmake it\s+(\d{1,3})\b",
            r"\b(\d{1,3})\s*percent\b",
            r"\b(\d{1,3})\s*\%",
        ]

        for pattern in patterns:
            match = re.search(pattern, normalized)
            if match:
                try:
                    value = int(match.group(1))
                    return max(0, min(value, 100))
                except ValueError:
                    return None

        return None

    def _extract_volume_delta_fast(self, text: str) -> Optional[int]:
        normalized = self._normalize_text(text)

        inc_patterns = [
            r"\b(?:turn|put|raise|increase|boost)\s+(?:it\s+|the\s+)?(?:up|volume|sound)?\s*(?:by\s+)?(\d{1,3})\b",
            r"\b(?:louder)\s+(?:by\s+)?(\d{1,3})\b",
        ]
        dec_patterns = [
            r"\b(?:turn|put|lower|decrease|reduce)\s+(?:it\s+|the\s+)?(?:down|volume|sound)?\s*(?:by\s+)?(\d{1,3})\b",
            r"\b(?:quieter)\s+(?:by\s+)?(\d{1,3})\b",
        ]

        for pattern in inc_patterns:
            match = re.search(pattern, normalized)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    return None

        for pattern in dec_patterns:
            match = re.search(pattern, normalized)
            if match:
                try:
                    return -int(match.group(1))
                except ValueError:
                    return None

        if any(phrase in normalized for phrase in ("turn it up", "make it louder", "raise volume", "boost the sound")):
            return 10
        if any(phrase in normalized for phrase in ("turn it down", "make it quieter", "lower volume", "reduce the sound")):
            return -10

        return None

    def _get_current_volume_percent(self, music: "Music") -> Optional[int]:
        voice_client = getattr(music, "voice_client", None)
        if (
            voice_client
            and getattr(voice_client, "source", None)
            and hasattr(voice_client.source, "volume")
        ):
            try:
                raw = float(voice_client.source.volume)
                return max(0, min(int(round(raw * 100)), 200))
            except Exception:
                return None
        return None

    async def _apply_volume(self, music: "Music", message: discord.Message, percent: int) -> bool:
        level = max(0, min(percent, 100)) / 100.0

        voice_client = getattr(music, "voice_client", None)
        if (
            voice_client
            and getattr(voice_client, "source", None)
            and hasattr(voice_client.source, "volume")
        ):
            try:
                voice_client.source.volume = level
                await message.channel.send(f"Blub! Volume set to {percent}% ğŸ¦­")
                return True
            except Exception:
                logger.exception("Failed to set source volume directly")

        set_volume_func = getattr(music, "set_volume_func", None)
        if callable(set_volume_func):
            try:
                await set_volume_func(message, level)
                return True
            except Exception:
                logger.exception("set_volume_func failed")

        await message.channel.send(
            f"Blub... I heard volume {percent}%, but volume control isn't available right now ğŸ¦­"
        )
        return True

    async def _handle_volume(self, music: "Music", message: discord.Message, text: str) -> bool:
        if not self._looks_like_volume_command(text):
            return False

        absolute = self._extract_volume_percent_fast(text)
        if absolute is not None:
            return await self._apply_volume(music, message, absolute)

        delta = self._extract_volume_delta_fast(text)
        if delta is not None:
            current = self._get_current_volume_percent(music)
            if current is None:
                current = 100
            return await self._apply_volume(music, message, max(0, min(current + delta, 100)))

        await message.channel.send("Blub... tell me a volume like 30% ğŸ¦­")
        return True

    # ---------------------------------------------------------------------
    # Seek understanding
    # ---------------------------------------------------------------------
    def _parse_unit_time_to_seconds(self, text: str) -> Optional[int]:
        text = self._normalize_text(text)

        hours = 0
        minutes = 0
        seconds = 0

        h_match = re.search(r"(\d+)\s*(?:hour|hours|hr|hrs|h)\b", text)
        m_match = re.search(r"(\d+)\s*(?:minute|minutes|min|mins|m)\b", text)
        s_match = re.search(r"(\d+)\s*(?:second|seconds|sec|secs|s)\b", text)

        if h_match:
            hours = int(h_match.group(1))
        if m_match:
            minutes = int(m_match.group(1))
        if s_match:
            seconds = int(s_match.group(1))

        total = hours * 3600 + minutes * 60 + seconds
        return total if total > 0 else None

    def _parse_colon_time_to_seconds(self, text: str) -> Optional[int]:
        match = re.search(r"\b(\d{1,2}:\d{1,2}(?::\d{1,2})?)\b", text)
        if not match:
            return None

        raw = match.group(1)
        parts = raw.split(":")

        try:
            if len(parts) == 2:
                minutes, seconds = map(int, parts)
                return minutes * 60 + seconds
            if len(parts) == 3:
                hours, minutes, seconds = map(int, parts)
                return hours * 3600 + minutes * 60 + seconds
        except ValueError:
            return None

        return None

    def _extract_bare_seconds(self, text: str) -> Optional[int]:
        normalized = self._normalize_text(text)

        trigger_phrases = (
            "go to ",
            "seek to ",
            "seek ",
            "jump to ",
            "move to ",
            "skip to ",
            "forward to ",
            "at ",
            "to ",
            "from ",
        )

        if not any(phrase in normalized for phrase in trigger_phrases):
            return None

        match = re.search(
            r"\b(?:go to|seek to|seek|jump to|move to|skip to|forward to|at|to|from)\s+(\d{1,5})\b",
            normalized,
        )
        if not match:
            return None

        try:
            return int(match.group(1))
        except ValueError:
            return None

    def _extract_seek_action_fast(self, text: str) -> Optional[tuple[str, int]]:
        normalized = self._normalize_text(text)

        explicit_relative_patterns: tuple[tuple[str, int], ...] = (
            (r"\b(?:seek forward|forward|fast forward|go forward|skip ahead|move forward|ileri sar|ileri al)\s+([0-9:]+(?:\s*(?:second|seconds|sec|secs|s|saniye))?)\b", 1),
            (r"\b(?:seek back|back|rewind|go back|move back|geri sar|geri al)\s+([0-9:]+(?:\s*(?:second|seconds|sec|secs|s|saniye))?)\b", -1),
            (r"\b([0-9:]+(?:\s*(?:second|seconds|sec|secs|s|saniye))?)\s+(?:forward|ileri)\b", 1),
            (r"\b([0-9:]+(?:\s*(?:second|seconds|sec|secs|s|saniye))?)\s+(?:back|geri)\b", -1),
        )
        for pattern, direction in explicit_relative_patterns:
            match = re.search(pattern, normalized)
            if not match:
                continue

            raw_value = match.group(1)
            seconds = self._parse_colon_time_to_seconds(raw_value)
            if seconds is None:
                seconds = self._parse_unit_time_to_seconds(raw_value)
            if seconds is None:
                bare = re.search(r"(\d+)", raw_value)
                if bare:
                    seconds = int(bare.group(1))
            if seconds is not None:
                return ("rel", seconds * direction)

        if normalized in {
            "restart",
            "restart song",
            "restart track",
            "play from start",
            "go to start",
            "from the beginning",
            "start from beginning",
        }:
            return ("abs", 0)

        special_skip_to_time = re.search(
            r"\b(?:skip to|forward to|go to|jump to|seek to|move to|start from|from)\s+(\d{1,2}:\d{1,2}(?::\d{1,2})?|\d{1,5})\b",
            normalized,
        )
        if special_skip_to_time:
            raw_value = special_skip_to_time.group(1)
            seconds = self._parse_colon_time_to_seconds(raw_value)
            if seconds is None:
                try:
                    seconds = int(raw_value)
                except ValueError:
                    seconds = None
            if seconds is not None:
                return ("abs", seconds)

        if any(
            phrase in normalized
            for phrase in ("rewind", "go back", "back up", "back ", "move back", "geri sar", "geri al")
        ):
            seconds = self._parse_colon_time_to_seconds(normalized)
            if seconds is None:
                seconds = self._parse_unit_time_to_seconds(normalized)
            if seconds is None:
                match = re.search(
                    r"\b(?:rewind|go back|back|move back|geri sar|geri al)\s+(\d+)\b",
                    normalized,
                )
                if match:
                    seconds = int(match.group(1))
            if seconds is not None:
                return ("rel", -seconds)
            return ("rel", -10)

        if any(
            phrase in normalized
            for phrase in (
                "forward",
                "fast forward",
                "go forward",
                "skip ahead",
                "ahead ",
                "move forward",
                "ileri sar",
                "ileri al",
            )
        ):
            seconds = self._parse_colon_time_to_seconds(normalized)
            if seconds is None:
                seconds = self._parse_unit_time_to_seconds(normalized)
            if seconds is None:
                match = re.search(
                    r"\b(?:forward|fast forward|go forward|skip ahead|ahead|move forward|ileri sar|ileri al)\s+(\d+)\b",
                    normalized,
                )
                if match:
                    seconds = int(match.group(1))
            if seconds is not None:
                return ("rel", seconds)
            return ("rel", 10)

        absolute_triggers = (
            "go to",
            "jump to",
            "seek to",
            "seek ",
            "move to",
            "take it to",
            "set it to",
            "skip to",
            "forward to",
            "start from",
            "from ",
        )

        if any(trigger in normalized for trigger in absolute_triggers):
            seconds = self._parse_colon_time_to_seconds(normalized)
            if seconds is None:
                seconds = self._parse_unit_time_to_seconds(normalized)
            if seconds is None:
                seconds = self._extract_bare_seconds(normalized)
            if seconds is not None:
                return ("abs", seconds)

        return None

    def _get_current_progress_seconds(self, music: "Music") -> int:
        start = getattr(music, "_track_start_monotonic", None)
        if start is None:
            return 0

        try:
            progress = int(time.monotonic() - start)
        except Exception:
            return 0

        current = getattr(music, "current", None)
        duration = getattr(current, "duration", None) if current else None

        if isinstance(duration, int):
            progress = max(0, min(progress, duration))
        else:
            progress = max(0, progress)

        return progress

    async def _handle_seek(self, music: "Music", message: discord.Message, text: str) -> bool:
        action = self._extract_seek_action_fast(text)
        if action is None:
            return False

        mode, seconds = action

        current = getattr(music, "current", None)
        duration = getattr(current, "duration", None) if current else None

        if mode == "abs":
            target = max(0, seconds)
        else:
            current_progress = self._get_current_progress_seconds(music)
            target = max(0, current_progress + seconds)

        if isinstance(duration, int):
            target = min(target, duration)

        await music.seek_func(message, self._seconds_to_timestamp(target))
        return True

    # ---------------------------------------------------------------------
    # Loop understanding
    # ---------------------------------------------------------------------
    def _extract_loop_mode_fast(self, text: str) -> Optional[str]:
        normalized = self._normalize_text(text)

        off_phrases = (
            "loop off",
            "turn off loop",
            "disable loop",
            "stop looping",
            "stop loop",
            "repeat off",
            "turn repeat off",
            "unloop",
            "disable repeat",
        )
        if any(phrase in normalized for phrase in off_phrases):
            return "off"

        queue_phrases = (
            "loop queue",
            "repeat queue",
            "loop playlist",
            "repeat playlist",
            "repeat all",
            "loop all",
            "loop the queue",
            "repeat the queue",
            "repeat the playlist",
            "keep the queue looping",
            "keep queue on loop",
        )
        if any(phrase in normalized for phrase in queue_phrases):
            return "queue"

        track_phrases = (
            "loop",
            "loop song",
            "loop this",
            "loop this song",
            "loop track",
            "loop this track",
            "repeat",
            "repeat song",
            "repeat this",
            "repeat this song",
            "repeat track",
            "repeat this track",
            "repeat the song",
            "repeat the track",
            "keep looping",
            "keep it looping",
            "put it on loop",
            "keep it on loop",
            "loop current song",
            "repeat current song",
        )
        if normalized in track_phrases:
            return "track"

        if any(phrase in normalized for phrase in track_phrases):
            return "track"

        return None

    # ---------------------------------------------------------------------
    # Scoring-based fallback intent detection
    # ---------------------------------------------------------------------
    def _score_exact_aliases(self, text: str, intent: str) -> tuple[float, int]:
        normalized = self._normalize_text(text)
        best_score = 0.0
        best_pos = -1
        for alias in self.COMMAND_ALIASES.get(intent, ()): 
            alias_n = self._normalize_text(alias)
            if normalized == alias_n:
                return 1.0, 0
            idx = normalized.find(alias_n)
            if idx != -1 and not self._has_negation_near(normalized, alias_n):
                score = 0.92 if idx == 0 else 0.84
                if score > best_score:
                    best_score = score
                    best_pos = idx
        return best_score, best_pos

    def _score_keyword_overlap(self, text: str, intent: str) -> float:
        tokens = set(self._tokenize(text))
        keywords = self.COMMAND_KEYWORDS.get(intent, ())
        if not tokens or not keywords:
            return 0.0

        matched = 0.0
        total_weight = float(len(keywords))
        for keyword in keywords:
            if keyword in tokens:
                matched += 1.0
                continue
            token_best = 0.0
            for token in tokens:
                token_best = max(token_best, self._phrase_similarity(token, keyword))
            if token_best >= 0.88:
                matched += 0.8
            elif token_best >= 0.78:
                matched += 0.45
        return min(matched / max(total_weight, 1.0), 1.0)

    def _intent_score(self, text: str, intent: str) -> IntentResult:
        alias_score, pos = self._score_exact_aliases(text, intent)
        overlap_score = self._score_keyword_overlap(text, intent)
        confidence = max(alias_score, overlap_score * 0.72)
        return IntentResult(name=intent, confidence=confidence, start=pos)

    # ---------------------------------------------------------------------
    # High-level parse
    # ---------------------------------------------------------------------
    def _detect_primary_intent(self, text: str) -> IntentResult:
        normalized = self._normalize_text(text)

        help_intent = self._extract_help_command_fast(text)
        if help_intent is not None:
            return help_intent

        now_playing_intent = self._extract_now_playing_command_fast(text)
        if now_playing_intent is not None:
            return now_playing_intent

        clear_queue_intent = self._extract_clear_queue_command_fast(text)
        if clear_queue_intent is not None:
            return clear_queue_intent

        filter_intent = self._extract_filter_command_fast(text)
        if filter_intent is not None:
            return filter_intent

        playlist_query = self._extract_playlist_play_query_fast(text)
        if playlist_query:
            return IntentResult("play", arg=playlist_query, confidence=0.99, start=0)

        # 1) play query detection first, because it can include many words.
        play_query = self._extract_play_query_fast(text)
        if play_query:
            pos = self._find_phrase_position(text, self.PLAY_PREFIXES)
            return IntentResult("play", arg=play_query, confidence=0.99, start=pos)

        playback_mode = self._extract_playback_mode_command_fast(text)
        if playback_mode is not None:
            return playback_mode

        # 2) lyrics query detection.
        lyrics_query = self._extract_lyrics_query_fast(text)
        if lyrics_query:
            pos = self._find_phrase_position(text, self.LYRICS_PREFIXES)
            return IntentResult("lyrics_query", arg=lyrics_query, confidence=0.99, start=pos)

        # 3) explicit loop / seek / volume first because they are easier to misread.
        loop_mode = self._extract_loop_mode_fast(text)
        if loop_mode is not None:
            return IntentResult("loop", arg=loop_mode, confidence=0.98, start=normalized.find("loop") if "loop" in normalized else normalized.find("repeat"))

        seek_action = self._extract_seek_action_fast(text)
        if seek_action is not None:
            return IntentResult("seek", confidence=0.98, start=0)

        if self._looks_like_volume_command(text):
            absolute = self._extract_volume_percent_fast(text)
            delta = self._extract_volume_delta_fast(text)
            meta = {}
            if absolute is not None:
                meta["volume_percent"] = absolute
            if delta is not None:
                meta["volume_delta"] = delta
            return IntentResult("volume", arg=str(absolute) if absolute is not None else None, confidence=0.97, start=0, meta=meta)

        # 4) scoring fallback for command-like short phrases.
        candidates: list[IntentResult] = []
        for intent in ("join", "leave", "previous", "lyrics", "skip", "pause", "resume", "stop", "queue", "shuffle"):
            candidates.append(self._intent_score(text, intent))

        best = max(candidates, key=lambda item: item.confidence, default=IntentResult("chat"))
        if best.confidence >= 0.58:
            return best

        return IntentResult("chat", confidence=0.0)

    def _extract_side_actions(self, text: str, primary: IntentResult) -> list[IntentResult]:
        extras: list[IntentResult] = []
        normalized = self._normalize_text(text)
        primary_name = primary.name

        def add_once(intent: str, arg: Optional[str] = None, meta: Optional[dict] = None):
            if any(item.name == intent and item.arg == arg for item in extras):
                return
            extras.append(IntentResult(name=intent, arg=arg, confidence=0.9, meta=meta or {}))

        if primary_name != "volume" and self._looks_like_volume_command(text):
            absolute = self._extract_volume_percent_fast(text)
            delta = self._extract_volume_delta_fast(text)
            if absolute is not None:
                add_once("volume", str(absolute), {"volume_percent": absolute})
            elif delta is not None:
                add_once("volume", None, {"volume_delta": delta})

        if primary_name != "loop":
            loop_mode = self._extract_loop_mode_fast(text)
            if loop_mode is not None:
                add_once("loop", loop_mode)

        if primary_name != "seek":
            seek_action = self._extract_seek_action_fast(text)
            if seek_action is not None:
                add_once("seek")

        if primary_name != "shuffle" and any(phrase in normalized for phrase in ("shuffle the queue", "shuffle queue", "mix the queue")):
            add_once("shuffle")

        if primary_name != "join":
            join_score = self._intent_score(text, "join")
            if join_score.confidence >= 0.9 and join_score.start != -1 and join_score.start < max(primary.start, 9999):
                add_once("join")

        return extras

    async def _run_extra_actions(
        self,
        music: "Music",
        message: discord.Message,
        extras: list[IntentResult],
        parsed_text: Optional[str] = None,
    ):
        for extra in extras:
            if extra.name == "volume":
                absolute = extra.meta.get("volume_percent")
                if absolute is not None:
                    await self._apply_volume(music, message, int(absolute))
                    continue

                delta = extra.meta.get("volume_delta")
                if delta is not None:
                    current = self._get_current_volume_percent(music)
                    if current is None:
                        current = 100
                    await self._apply_volume(music, message, max(0, min(current + int(delta), 100)))
                    continue

            elif extra.name == "loop":
                await music.set_loop_mode_func(message, extra.arg or "track")

            elif extra.name == "seek":
                await self._handle_seek(music, message, parsed_text or message.content or "")

            elif extra.name == "shuffle":
                await music.shuffle_queue_func(message)

            elif extra.name == "join":
                await music.summon_func(message)

    # ---------------------------------------------------------------------
    # Event listener
    # ---------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user:
            return

        if message.author.bot:
            return

        if CHATBOT_CHANNEL_IDS:
            if message.channel.id not in CHATBOT_CHANNEL_IDS:
                return
        elif CHATBOT_CHANNEL_ID and message.channel.id != CHATBOT_CHANNEL_ID:
            return

        text = (message.content or "").strip()
        if not text:
            return

        music = self.music_cog
        community = self.community_cog
        if not music and not community:
            await self.bot.process_commands(message)
            return

        async with self._locks[message.channel.id]:
            parsed_text = text
            extras: list[IntentResult] = []
            primary = (
                self._extract_community_intent_from_message(message)
                or self._extract_most_played_intent_from_message(message)
                or self._extract_history_intent_from_message(message)
                or self._detect_turkish_intent_fast(text)
            )

            if primary.name == "chat":
                primary = self._detect_primary_intent(parsed_text)

                if primary.name == "chat" and _looks_turkish_text(text):
                    try:
                        translated = tr_to_en(text)
                    except Exception:
                        logger.debug("Turkish fallback translation failed", exc_info=True)
                    else:
                        if isinstance(translated, str) and translated.strip():
                            parsed_text = translated.strip()
                            primary = self._detect_primary_intent(parsed_text)

                if primary.name == "chat":
                    if community and message.guild is not None:
                        with contextlib.suppress(Exception):
                            active_text_game = community._get_active_chat_guessing_session(message.guild.id, message.channel.id)
                            if active_text_game is not None:
                                return
                    await self.bot.process_commands(message)
                    return

                extras = self._extract_side_actions(parsed_text, primary)

            if primary.name == "help":
                if community:
                    await community.help_func(message, topic=primary.arg or None)
                    return
                if music:
                    await music.help_func(message)
                    return

            if primary.name == "profile" and community:
                await community.profile_func(
                    message,
                    target_user=primary.meta.get("target_user"),
                )
                return

            if primary.name == "xp_leaderboard" and community:
                await community.xp_leaderboard_func(
                    message,
                    page=int(primary.meta.get("page", 1)),
                )
                return

            if primary.name == "avatar" and community:
                await community.avatar_func(
                    message,
                    target_user=primary.meta.get("target_user"),
                )
                return

            if primary.name == "banner" and community:
                await community.banner_func(
                    message,
                    target_user=primary.meta.get("target_user"),
                )
                return

            if primary.name == "userinfo" and community:
                await community.userinfo_func(
                    message,
                    target_user=primary.meta.get("target_user"),
                )
                return

            if primary.name == "translate" and community:
                await community.translate_func(message, raw_text=primary.arg or "")
                return

            if primary.name == "rewrite" and community:
                await community.rewrite_func(message, raw_text=primary.arg or "")
                return

            if primary.name == "explain" and community:
                await community.explain_func(message, raw_text=primary.arg or "")
                return

            if primary.name == "ping" and community:
                await community.ping_func(message)
                return

            if primary.name == "uptime" and community:
                await community.uptime_func(message)
                return

            if primary.name == "calc" and community:
                await community.calc_func(message, raw_expression=primary.arg or "")
                return

            if primary.name == "timer" and community:
                await community.timer_func(message, raw_duration=primary.arg or "")
                return

            if primary.name == "remind" and community:
                await community.remind_func(message, raw_input=primary.arg or "")
                return

            if primary.name == "notes_add" and community:
                await community.notes_add_func(message, raw_text=primary.arg or "")
                return

            if primary.name == "notes_list" and community:
                await community.notes_list_func(message)
                return

            if primary.name == "notes_delete" and community:
                await community.notes_delete_func(message, note_id=int(primary.meta.get("note_id", 0)))
                return

            if primary.name == "summarize" and community:
                await community.summarize_func(message, raw_text=primary.arg or "")
                return

            if primary.name == "keywords" and community:
                await community.keywords_func(message, raw_text=primary.arg or "")
                return

            if primary.name == "fix" and community:
                await community.fix_func(message, raw_text=primary.arg or "")
                return

            if primary.name == "shorten" and community:
                await community.shorten_func(message, raw_text=primary.arg or "")
                return

            if primary.name == "expand" and community:
                await community.expand_func(message, raw_text=primary.arg or "")
                return

            if primary.name == "tone" and community:
                await community.tone_func(
                    message,
                    mode=str(primary.meta.get("mode", "casual")),
                    raw_text=primary.arg or "",
                )
                return

            if primary.name == "balance" and community:
                await community.balance_func(
                    message,
                    target_user=primary.meta.get("target_user"),
                )
                return

            if primary.name == "jobs" and community:
                await community.jobs_func(message)
                return

            if primary.name == "choose_job" and community:
                await community.choose_job_func(message, raw_job_name=primary.arg or "")
                return

            if primary.name == "current_job" and community:
                await community.current_job_func(message)
                return

            if primary.name == "job_upgrade" and community:
                await community.job_upgrade_func(message)
                return

            if primary.name == "achievements" and community:
                await community.achievements_func(message)
                return

            if primary.name == "quests" and community:
                await community.quests_func(message)
                return

            if primary.name == "income" and community:
                await community.income_func(message)
                return

            if primary.name == "collect" and community:
                await community.collect_func(message)
                return

            if primary.name == "mystats" and community:
                await community.mystats_func(message)
                return

            if primary.name == "dungeonstats" and community:
                await community.dungeonstats_func(message)
                return

            if primary.name == "casinostats" and community:
                await community.casinostats_func(message)
                return

            if primary.name == "jobstats" and community:
                await community.jobstats_func(message)
                return

            if primary.name == "winrate" and community:
                await community.winrate_func(message)
                return

            if primary.name == "lossrate" and community:
                await community.lossrate_func(message)
                return

            if primary.name == "mostused" and community:
                await community.mostused_func(message)
                return

            if primary.name == "playtime" and community:
                await community.playtime_func(message)
                return

            if primary.name == "work" and community:
                await community.work_func(message)
                return

            if primary.name == "beg" and community:
                await community.beg_func(message)
                return

            if primary.name == "quiz" and community:
                await community.quiz_func(message)
                return

            if primary.name == "answer_quiz" and community:
                await community.answer_quiz_func(message, raw_answer=primary.arg or "")
                return

            if primary.name == "daily" and community:
                await community.daily_func(message)
                return

            if primary.name == "quick_earn" and community:
                await community.quick_earn_panel_func(message)
                return

            if primary.name == "shop" and community:
                await community.shop_func(message)
                return

            if primary.name == "shopview" and community:
                await community.shopview_func(message)
                return

            if primary.name == "inventory" and community:
                await community.inventory_func(message)
                return

            if primary.name == "sellall" and community:
                await community.sellall_func(message)
                return

            if primary.name in {"pets", "petshop"} and community:
                await community.petshop_func(message)
                return

            if primary.name == "mypet" and community:
                await community.mypet_func(message)
                return

            if primary.name == "buypet" and community:
                await community.buypet_func(message, raw_pet_name=primary.arg or "")
                return

            if primary.name == "equippet" and community:
                await community.equippet_func(message, raw_pet_name=primary.arg or "")
                return

            if primary.name == "unequippet" and community:
                await community.unequippet_func(message)
                return

            if primary.name == "feedpet" and community:
                await community.feedpet_func(message)
                return

            if primary.name == "petinfo" and community:
                await community.petinfo_func(message)
                return

            if primary.name == "buy" and community:
                await community.buy_func(message, raw_item_name=primary.arg or "")
                return

            if primary.name == "sell" and community:
                await community.sell_func(message, raw_item_name=primary.arg or "")
                return

            if primary.name == "use_item" and community:
                await community.use_item_func(message, raw_item_name=primary.arg or "")
                return

            if primary.name == "gamble" and community:
                await community.gamble_func(
                    message,
                    amount=int(primary.meta.get("amount", 0)),
                )
                return

            if primary.name == "blackjack" and community:
                await community.blackjack_func(
                    message,
                    amount=int(primary.meta.get("amount", 0)),
                    target_user=primary.meta.get("target_user"),
                )
                return

            if primary.name == "coinflip" and community:
                await community.coinflip_func(
                    message,
                    target_user=primary.meta.get("target_user"),
                    amount=int(primary.meta.get("amount", 0)),
                )
                return

            if primary.name == "slots" and community:
                await community.slots_func(
                    message,
                    amount=int(primary.meta.get("amount", 0)),
                )
                return

            if primary.name == "crash" and community:
                await community.crash_func(
                    message,
                    amount=int(primary.meta.get("amount", 0)),
                )
                return

            if primary.name == "guess" and community:
                await community.guess_func(
                    message,
                    amount=int(primary.meta.get("amount", 0)),
                )
                return

            if primary.name == "drawgame" and community:
                await community.drawgame_func(message)
                return

            if primary.name == "drawgame_hint" and community:
                await community.drawgame_hint_func(message)
                return

            if primary.name == "enddrawgame" and community:
                await community.enddrawgame_func(message)
                return

            if primary.name == "hangman" and community:
                await community.hangman_func(message)
                return

            if primary.name == "wordchain" and community:
                await community.wordchain_func(message)
                return

            if primary.name == "trivia" and community:
                await community.trivia_func(message)
                return

            if primary.name == "duel" and community:
                await community.duel_func(
                    message,
                    target_user=primary.meta.get("target_user"),
                    amount=int(primary.meta.get("amount", 0)),
                )
                return

            if primary.name == "dungeon" and community:
                await community.dungeon_func(
                    message,
                    amount=int(primary.meta.get("amount", 0)),
                )
                return

            if primary.name in {"steal", "rob", "heist"} and community:
                await getattr(community, f"{primary.name}_func")(
                    message,
                    target_user=primary.meta.get("target_user"),
                )
                return

            if primary.name == "gift" and community:
                await community.gift_func(
                    message,
                    target_user=primary.meta.get("target_user"),
                    amount=int(primary.meta.get("amount", 0)),
                )
                return

            if primary.name == "givemoney" and community:
                await community.givemoney_func(
                    message,
                    target_user=primary.meta.get("target_user"),
                    amount=int(primary.meta.get("amount", 0)),
                )
                return

            if primary.name == "propose" and community:
                await community.propose_func(
                    message,
                    target_user=primary.meta.get("target_user"),
                )
                return

            if primary.name == "marry" and community:
                await community.marry_func(
                    message,
                    target_user=primary.meta.get("target_user"),
                )
                return

            if primary.name == "accept_marriage" and community:
                await community.accept_marriage_func(message)
                return

            if primary.name == "decline_marriage" and community:
                await community.decline_marriage_func(message)
                return

            if primary.name == "divorce" and community:
                await community.divorce_func(message)
                return

            if primary.name == "spouse" and community:
                await community.spouse_func(
                    message,
                    target_user=primary.meta.get("target_user"),
                )
                return

            if primary.name == "marriage" and community:
                await community.marriage_func(
                    message,
                    target_user=primary.meta.get("target_user"),
                )
                return

            if primary.name == "marriageprofile" and community:
                await community.marriageprofile_func(
                    message,
                    target_user=primary.meta.get("target_user"),
                )
                return

            if primary.name == "love" and community:
                await community.love_func(message)
                return

            if primary.name == "richest" and community:
                await community.richest_func(
                    message,
                    page=int(primary.meta.get("page", 1)),
                )
                return

            if primary.name == "topdungeon" and community:
                await community.topdungeon_func(
                    message,
                    page=int(primary.meta.get("page", 1)),
                )
                return

            if primary.name == "topgamblers" and community:
                await community.topgamblers_func(
                    message,
                    page=int(primary.meta.get("page", 1)),
                )
                return

            if primary.name == "topwins" and community:
                await community.topwins_func(
                    message,
                    page=int(primary.meta.get("page", 1)),
                )
                return

            if primary.name == "toplosses" and community:
                await community.toplosses_func(
                    message,
                    page=int(primary.meta.get("page", 1)),
                )
                return

            if primary.name in {"fish", "hunt", "search", "mine", "deliver", "scavenge", "freelance", "craft", "repair", "patrol"} and community:
                await getattr(community, f"{primary.name}_func")(message)
                return

            if primary.name == "purge" and community:
                await community.purge_func(
                    message,
                    amount=int(primary.meta.get("amount", 0)),
                )
                return

            if not music:
                await self.bot.process_commands(message)
                return

            if primary.name == "join":
                await music.summon_func(message)
                await self._run_extra_actions(music, message, extras, parsed_text)
                return

            if primary.name == "leave":
                await music.disconnect_func(message)
                return

            if primary.name == "history":
                await music.history_func(
                    message,
                    target_user=primary.meta.get("target_user"),
                    page=int(primary.meta.get("page", 1)),
                )
                return

            if primary.name == "most_played":
                await music.most_played_func(
                    message,
                    target_user=primary.meta.get("target_user"),
                    page=int(primary.meta.get("page", 1)),
                )
                return

            if primary.name == "now_playing":
                await music.now_playing_func(message)
                return

            if primary.name == "clear_queue":
                await music.clear_queue_func(message)
                return

            if primary.name == "filter_control":
                if primary.arg == "show":
                    await music.show_filters_func(message)
                elif primary.arg == "off" and primary.meta.get("effect_name"):
                    await music.remove_filter_func(message, primary.meta["effect_name"])
                else:
                    await music.clear_filters_func(message)
                return

            if primary.name == "filter":
                await music.apply_filter_func(
                    message,
                    primary.arg or "",
                    params=primary.meta.get("params"),
                )
                return

            if primary.name == "play":
                query = primary.arg
                if not query:
                    await message.channel.send("Blub... tell me what to play ğŸ¦­")
                    return

                if any(extra.name == "join" for extra in extras):
                    await music.summon_func(message)
                    extras = [extra for extra in extras if extra.name != "join"]

                await music.play_func(message, query)
                await self._run_extra_actions(music, message, extras, parsed_text)
                return

            if primary.name == "previous":
                await music.play_previous_func(message)
                await self._run_extra_actions(music, message, extras, parsed_text)
                return

            if primary.name == "loop":
                await music.set_loop_mode_func(message, primary.arg or "track")
                return

            if primary.name == "playback_preset":
                await music.set_playback_preset_func(
                    message,
                    primary.arg or "nightcore",
                    playback_rate=primary.meta.get("playback_rate"),
                )
                return

            if primary.name == "seek":
                handled = await self._handle_seek(music, message, parsed_text)
                if handled:
                    return

            if primary.name == "volume":
                absolute = primary.meta.get("volume_percent")
                if absolute is not None:
                    await self._apply_volume(music, message, int(absolute))
                    return

                delta = primary.meta.get("volume_delta")
                if delta is not None:
                    current = self._get_current_volume_percent(music)
                    if current is None:
                        current = 100
                    await self._apply_volume(music, message, max(0, min(current + int(delta), 100)))
                    return

                handled = await self._handle_volume(music, message, parsed_text)
                if handled:
                    return

            if primary.name == "lyrics_query":
                await music.lyrics_by_query_func(message, primary.arg or "")
                return

            if primary.name == "lyrics":
                await music.lyrics_func(message)
                return

            if primary.name == "skip":
                await music.skip_func(message)
                return

            if primary.name == "pause":
                await music.pause_func(message)
                return

            if primary.name == "resume":
                await music.resume_func(message)
                return

            if primary.name == "stop":
                await music.stop_func(message)
                return

            if primary.name == "queue":
                result = await music.get_queue_func(message)
                await message.channel.send(result)
                return

            if primary.name == "shuffle":
                await music.shuffle_queue_func(message)
                return

        await self.bot.process_commands(message)


GroqChatCog = RaizelChatCog


async def setup(bot: commands.Bot):
    await bot.add_cog(RaizelChatCog(bot))


