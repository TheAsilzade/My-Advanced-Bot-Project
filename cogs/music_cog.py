from __future__ import annotations

import asyncio
import contextlib
import copy
import datetime
import json
import logging
import random
import time
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Deque, Optional
from urllib.parse import urlparse

import discord
import requests
import yt_dlp
from discord.ext import commands, tasks

from config import FFMPEG_OPTIONS, MUSIC_DIRECTORY, YTDL_OPTIONS
from utils.lyrics import fetch_lyrics

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
except ImportError:
    Image = None
    ImageDraw = None
    ImageFilter = None
    ImageFont = None
    ImageOps = None

logger = logging.getLogger(__name__)

SOUNDCLOUD_DOMAINS = ("soundcloud.com", "on.soundcloud.com")
SOUNDCLOUD_QUERY_PREFIXES = ("sc ", "soundcloud ")
SOUNDCLOUD_QUERY_PREFIXES_WITH_COLON = ("sc:", "soundcloud:")
NOW_PLAYING_WIDGET_WIDTH = 1180
NOW_PLAYING_WIDGET_HEIGHT = 380
NOW_PLAYING_WIDGET_FILENAME = "now-playing-card.png"
NOW_PLAYING_WIDGET_TRANSITION_FILENAME = "now-playing-transition.png"
NOW_PLAYING_WIDGET_TRANSITION_DELAY_SECONDS = 0.35
NOW_PLAYING_WIDGET_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PeaceMusicBot/1.0; +https://discord.com)",
}
YTDL_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
YTDL_STREAM_RESOLUTION_RETRY_DELAY_SECONDS = 0.25
PLAYLIST_MAX_ENTRIES = 25
SONG_HISTORY_FILENAME = "song_history.json"
SONG_HISTORY_PAGE_SIZE = 5
SONG_HISTORY_MAX_ENTRIES_PER_USER = 200
SONG_HISTORY_DUPLICATE_WINDOW_SECONDS = 2.0
HELP_EMBED_COLOR = 0x111827
AUDIO_FILTER_LABELS = {
    "nightcore": "Nightcore",
    "bassboost": "Bassboost",
    "slow": "Slow",
    "speed": "Speed",
    "pitch": "Pitch",
    "reverb": "Reverb",
    "echo": "Echo",
    "karaoke": "Karaoke",
    "tremolo": "Tremolo",
    "vibrato": "Vibrato",
    "flanger": "Flanger",
    "phaser": "Phaser",
    "chorus": "Chorus",
    "distortion": "Distortion",
    "lowpass": "Lowpass",
    "highpass": "Highpass",
    "equalizer": "Equalizer",
    "mono": "Mono",
    "stereo_widen": "Stereo Widen",
    "compressor": "Compressor",
    "gate": "Gate",
    "volume_filter": "Filter Volume",
    "earrape": "Earrape",
    "vaporwave": "Vaporwave",
    "lofi": "Lofi",
    "deep": "Deep",
    "telephone": "Telephone",
    "megaphone": "Megaphone",
    "robot": "Robot",
    "underwater": "Underwater",
    "8d": "8D",
}
AUDIO_FILTER_ORDER = {
    "karaoke": 10,
    "bassboost": 20,
    "equalizer": 30,
    "lowpass": 40,
    "highpass": 50,
    "compressor": 60,
    "gate": 70,
    "distortion": 80,
    "tremolo": 90,
    "vibrato": 100,
    "flanger": 110,
    "phaser": 120,
    "chorus": 130,
    "echo": 140,
    "reverb": 150,
    "telephone": 160,
    "megaphone": 170,
    "robot": 180,
    "underwater": 190,
    "lofi": 200,
    "mono": 210,
    "stereo_widen": 220,
    "8d": 230,
    "nightcore": 240,
    "slow": 241,
    "speed": 242,
    "pitch": 243,
    "vaporwave": 244,
    "deep": 245,
    "volume_filter": 260,
    "earrape": 270,
}
AUDIO_FILTER_CONFLICT_GROUPS = {
    "tempo_pitch": {"nightcore", "slow", "speed", "pitch", "vaporwave", "deep"},
    "stereo_field": {"mono", "stereo_widen", "8d"},
    "gain_stage": {"volume_filter", "earrape"},
}


def _widget_resample_filter() -> int:
    if Image is None:
        raise RuntimeError("Pillow is not available for widget rendering.")
    if hasattr(Image, "Resampling"):
        return Image.Resampling.LANCZOS
    return Image.LANCZOS


def _widget_adaptive_palette() -> Any:
    if Image is None:
        raise RuntimeError("Pillow is not available for widget rendering.")
    if hasattr(Image, "Palette") and hasattr(Image.Palette, "ADAPTIVE"):
        return Image.Palette.ADAPTIVE
    return Image.ADAPTIVE


def _widget_font_candidates(*, bold: bool) -> tuple[str, ...]:
    if bold:
        return (
            "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        )

    return (
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )


@lru_cache(maxsize=48)
def _load_widget_font(size: int, *, bold: bool = False):
    if ImageFont is None:
        raise RuntimeError("Pillow is not available for widget rendering.")

    for candidate in _widget_font_candidates(bold=bold):
        if not Path(candidate).exists():
            continue
        with contextlib.suppress(OSError):
            return ImageFont.truetype(candidate, size=size)

    fallback_name = "arialbd.ttf" if bold else "arial.ttf"
    with contextlib.suppress(OSError):
        return ImageFont.truetype(fallback_name, size=size)

    return ImageFont.load_default()


def _measure_text(draw: Any, text: str, font: Any) -> float:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return float(right - left)


def _truncate_text(draw: Any, text: str, font: Any, max_width: float) -> str:
    if not text:
        return ""

    if _measure_text(draw, text, font) <= max_width:
        return text

    ellipsis = "..."
    working = text
    while working and _measure_text(draw, f"{working}{ellipsis}", font) > max_width:
        working = working[:-1].rstrip()

    return f"{working or text[:1]}{ellipsis}"


def format_duration(duration_seconds: float | int | None) -> str:
    if duration_seconds is None:
        return "00:00"

    try:
        total_seconds = int(float(duration_seconds))
    except (TypeError, ValueError):
        return "00:00"

    if total_seconds < 1:
        return "00:00"

    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def parse_time(time_str: str) -> int:
    parts = time_str.split(":")
    if len(parts) == 1:
        return int(parts[0])
    if len(parts) == 2:
        minutes, seconds = map(int, parts)
        return minutes * 60 + seconds
    if len(parts) == 3:
        hours, minutes, seconds = map(int, parts)
        return hours * 3600 + minutes * 60 + seconds
    raise ValueError("Invalid time format. Use seconds, MM:SS, or HH:MM:SS.")


def _looks_like_url(query: str) -> bool:
    lowered = query.lower()
    return lowered.startswith(("http://", "https://"))


def _is_direct_media_url(query: str) -> bool:
    if not _looks_like_url(query):
        return False

    parsed = urlparse(query)
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return False

    direct_host_suffixes = (
        "youtube.com",
        "youtu.be",
        "soundcloud.com",
        "on.soundcloud.com",
    )
    if any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in direct_host_suffixes):
        return True

    return _is_probable_webpage_url(query) or _is_probable_stream_url(query)


def _is_probable_webpage_url(url: str) -> bool:
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False

    lowered = url.lower()

    webpage_markers = (
        "youtube.com/watch?",
        "youtu.be/",
        "youtube.com/shorts/",
        "youtube.com/results?",
        "soundcloud.com/",
        "on.soundcloud.com/",
    )

    return any(marker in lowered for marker in webpage_markers)


def _is_youtube_webpage_url(url: str) -> bool:
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False

    lowered = url.lower()
    youtube_markers = (
        "youtube.com/watch?",
        "youtube.com/shorts/",
        "youtu.be/",
        "music.youtube.com/",
    )
    return any(marker in lowered for marker in youtube_markers)


def _is_probable_stream_url(url: str) -> bool:
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False
    return not _is_probable_webpage_url(url)


def normalize_audio_query(query: str) -> str:
    query = query.strip()
    if not query:
        return query

    lowered = query.lower()

    for prefix in SOUNDCLOUD_QUERY_PREFIXES:
        if lowered.startswith(prefix):
            rest = query[len(prefix):].strip()
            if rest:
                return f"scsearch1:{rest}"
            return query

    for prefix in SOUNDCLOUD_QUERY_PREFIXES_WITH_COLON:
        if lowered.startswith(prefix):
            rest = query[len(prefix):].strip()
            if rest:
                return f"scsearch1:{rest}"
            return query

    if lowered.startswith("scsearch"):
        return query

    if not _looks_like_url(query):
        stripped_query = query.lstrip("www.")
        if " " not in stripped_query and any(
            domain in stripped_query.lower() for domain in SOUNDCLOUD_DOMAINS
        ):
            return f"https://{query}"

    return query


def is_soundcloud_query(query: str) -> bool:
    lowered = query.lower()
    if lowered.startswith("scsearch"):
        return True

    if _looks_like_url(query):
        parsed = urlparse(query)
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False
        return any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in SOUNDCLOUD_DOMAINS
        )

    return False


@dataclass
class QueuedTrack:
    title: str
    requester: discord.abc.User
    webpage_url: Optional[str] = None
    thumbnail: Optional[str] = None
    uploader: Optional[str] = None
    duration: Optional[int] = None
    channel: Optional[discord.abc.Messageable] = None
    playback_preset: str = "normal"
    info: dict[str, Any] = field(default_factory=dict)
    local_path: Optional[Path] = None
    original_query: Optional[str] = None
    download_task: Optional[asyncio.Task] = None
    stream_url: Optional[str] = None
    stream_task: Optional[asyncio.Task] = None
    playback_rate: Optional[float] = None


@dataclass(slots=True)
class AudioFilterEntry:
    name: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AudioFilterState:
    effects: dict[str, AudioFilterEntry] = field(default_factory=dict)


@dataclass(slots=True)
class SongHistoryEntry:
    title: str
    webpage_url: Optional[str] = None
    requester_display_name: Optional[str] = None
    timestamp: Optional[str] = None


class SeekModal(discord.ui.Modal, title="Seek to time"):
    def __init__(self, cog: "Music", view: "MusicControlView"):
        super().__init__()
        self.cog = cog
        self.view_ref = view

        self.time_input = discord.ui.TextInput(
            label="Timestamp",
            placeholder="Examples: 1:20, 01:20, 1:02:30, 73",
            required=True,
            max_length=20,
            style=discord.TextStyle.short,
        )
        self.add_item(self.time_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        deferred = False
        if not interaction.response.is_done():
            with contextlib.suppress(discord.HTTPException):
                await interaction.response.defer(ephemeral=True)
                deferred = True

        raw_value = self.time_input.value.strip()

        try:
            seconds = parse_time(raw_value)
        except ValueError:
            if deferred:
                with contextlib.suppress(discord.HTTPException, discord.NotFound):
                    await interaction.followup.send(
                        "Invalid time format. Use seconds, MM:SS, or HH:MM:SS.",
                        ephemeral=True,
                    )
            elif not interaction.response.is_done():
                with contextlib.suppress(discord.HTTPException):
                    await interaction.response.send_message(
                        "Invalid time format. Use seconds, MM:SS, or HH:MM:SS.",
                        ephemeral=True,
                    )
            return

        _, response = await self.cog.seek_to_seconds_interaction(interaction, seconds)
        await self.cog._refresh_active_controls(force=True)

        if deferred:
            with contextlib.suppress(discord.HTTPException, discord.NotFound):
                await interaction.followup.send(response, ephemeral=True)
        elif not interaction.response.is_done():
            with contextlib.suppress(discord.HTTPException):
                await interaction.response.send_message(response, ephemeral=True)


class MusicControlView(discord.ui.View):
    def __init__(self, cog: "Music", *, timeout: float = 900):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.message: Optional[discord.Message] = None
        self._sync_styles()

    def _sync_styles(self) -> None:
        preset = "normal"
        paused = False

        if self.cog.current:
            preset = self.cog.current.playback_preset

        if self.cog._vc_connected():
            paused = self.cog._vc_paused()

        self.pause_button.style = (
            discord.ButtonStyle.success
            if not paused
            else discord.ButtonStyle.secondary
        )
        self.resume_button.style = (
            discord.ButtonStyle.success
            if paused
            else discord.ButtonStyle.secondary
        )

        self.nightcore_button.style = (
            discord.ButtonStyle.success
            if preset == "nightcore"
            else discord.ButtonStyle.secondary
        )
        self.slow_button.style = (
            discord.ButtonStyle.success
            if preset == "slow"
            else discord.ButtonStyle.secondary
        )

    async def _run_interaction_action(
        self,
        interaction: discord.Interaction,
        action_coro,
        *,
        refresh_controls: bool = True,
    ) -> None:
        deferred = False
        if not interaction.response.is_done():
            with contextlib.suppress(discord.HTTPException):
                await interaction.response.defer(ephemeral=True)
                deferred = True

        _, response = await action_coro

        if refresh_controls:
            await self.cog._refresh_active_controls(force=True)

        if deferred:
            with contextlib.suppress(discord.HTTPException, discord.NotFound):
                await interaction.followup.send(response, ephemeral=True)
        elif not interaction.response.is_done():
            with contextlib.suppress(discord.HTTPException):
                await interaction.response.send_message(response, ephemeral=True)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        vc = self.cog.voice_client
        if not vc or not self.cog._vc_connected():
            await interaction.response.send_message(
                "The bot is not connected to a voice channel right now.",
                ephemeral=True,
            )
            return False

        user_voice = getattr(interaction.user, "voice", None)
        if not user_voice or user_voice.channel != vc.channel:
            await interaction.response.send_message(
                "You have to be in the same voice channel as me.",
                ephemeral=True,
            )
            return False

        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True

        if self.message:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.secondary, row=0)
    async def pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._run_interaction_action(interaction, self.cog.pause_interaction(interaction))

    @discord.ui.button(label="Resume", style=discord.ButtonStyle.secondary, row=0)
    async def resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._run_interaction_action(interaction, self.cog.resume_interaction(interaction))

    @discord.ui.button(label="Seek", style=discord.ButtonStyle.primary, row=0)
    async def seek_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SeekModal(self.cog, self))

    @discord.ui.button(label="Nightcore", style=discord.ButtonStyle.secondary, row=1)
    async def nightcore_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._run_interaction_action(
            interaction,
            self.cog.set_playback_preset_interaction(interaction, "nightcore"),
        )

    @discord.ui.button(label="Slow", style=discord.ButtonStyle.secondary, row=1)
    async def slow_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._run_interaction_action(
            interaction,
            self.cog.set_playback_preset_interaction(interaction, "slow"),
        )

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.danger, row=1)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._run_interaction_action(interaction, self.cog.skip_interaction(interaction))


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_client: Optional[discord.VoiceClient] = None
        self.queue: Deque[QueuedTrack] = deque()
        self.current: Optional[QueuedTrack] = None
        self.previous_track_data: Optional[dict[str, Any]] = None

        self._play_lock = asyncio.Lock()
        self._start_next_lock = asyncio.Lock()
        self._download_semaphore = asyncio.Semaphore(4)
        self._voice_transition_lock = asyncio.Lock()

        self._skip_after_callback = False
        self.loop_mode = "off"
        self._replay_track: Optional[QueuedTrack] = None

        self.volume = 0.5
        self._current_source: Optional[discord.PCMVolumeTransformer] = None
        self._filter_state = AudioFilterState()

        # 3. MUSIC_COG INTEGRATION: the cog keeps one active now-playing widget
        # message and refreshes it from the playback pipeline below.
        self._active_control_message: Optional[discord.Message] = None
        self._active_control_view: Optional[MusicControlView] = None
        self._active_control_description: str = "Now playing"
        self._active_control_color: discord.Color = discord.Color.green()
        self._active_control_uses_widget_image = False
        self._control_refresh_lock = asyncio.Lock()
        self._last_control_refresh_monotonic = 0.0
        self._progress_update_task: Optional[asyncio.Task] = None
        self._widget_transition_task: Optional[asyncio.Task] = None
        self._widget_transition_nonce = 0

        self._last_audio_time: Optional[datetime.datetime] = None
        self._current_position_base_seconds = 0
        self._current_started_monotonic: Optional[float] = None

        self.music_directory = Path(MUSIC_DIRECTORY)
        self.music_directory.mkdir(parents=True, exist_ok=True)
        self._song_history_path = self.music_directory / SONG_HISTORY_FILENAME
        self._history_lock = asyncio.Lock()
        self._song_history: dict[str, dict[str, list[dict[str, Any]]]] = self._load_song_history_sync()
        self._last_history_record_signature: Optional[tuple[int, int, tuple[str, ...]]] = None
        self._last_history_recorded_at_monotonic = 0.0

        self.check_for_inactivity.start()

    def cog_unload(self) -> None:
        self.check_for_inactivity.cancel()
        self._cancel_progress_update_task()
        self._cancel_widget_transition_task()

    def _vc_connected(self) -> bool:
        return bool(self.voice_client and self.voice_client.is_connected())

    def _vc_playing(self) -> bool:
        return bool(self.voice_client and self.voice_client.is_playing())

    def _vc_paused(self) -> bool:
        return bool(self.voice_client and self.voice_client.is_paused())

    def _vc_active(self) -> bool:
        return self._vc_playing() or self._vc_paused()

    def _volume_percent(self) -> int:
        return max(0, min(200, int(round(self.volume * 100))))

    def _player_busy(self) -> bool:
        return self._vc_active()

    def _touch_audio_heartbeat(self) -> None:
        self._last_audio_time = discord.utils.utcnow()

    async def _cleanup_audio_source(
        self,
        source: Optional[discord.AudioSource],
        *,
        reason: str,
    ) -> None:
        if source is None:
            return

        cleanup = getattr(source, "cleanup", None)
        if not callable(cleanup):
            return

        try:
            logger.debug("Cleaning up audio source (%s)", reason)
            await asyncio.to_thread(cleanup)
        except Exception:
            logger.debug("Audio source cleanup failed (%s)", reason, exc_info=True)

    async def _cleanup_current_source(self, *, reason: str) -> None:
        source = self._current_source
        self._current_source = None
        await self._cleanup_audio_source(source, reason=reason)

    async def _wait_for_voice_idle(self, *, timeout: float = 1.5) -> bool:
        voice_client = self.voice_client
        if voice_client is None:
            return True

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not voice_client.is_playing() and not voice_client.is_paused():
                return True
            await asyncio.sleep(0.05)

        return not voice_client.is_playing() and not voice_client.is_paused()

    async def _stop_voice_playback_locked(
        self,
        *,
        reason: str,
        suppress_after_callback: bool,
    ) -> None:
        voice_client = self.voice_client

        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            logger.info("Stopping previous playback (%s)", reason)
            if suppress_after_callback:
                self._skip_after_callback = True

            try:
                voice_client.stop()
            except Exception:
                logger.exception("Failed to stop voice playback cleanly (%s)", reason)

            if not await self._wait_for_voice_idle():
                logger.warning("Voice client still reported active after stop (%s)", reason)

        self._current_started_monotonic = None
        await self._cleanup_current_source(reason=reason)

    async def _stop_voice_playback(
        self,
        *,
        reason: str,
        suppress_after_callback: bool,
    ) -> None:
        async with self._voice_transition_lock:
            await self._stop_voice_playback_locked(
                reason=reason,
                suppress_after_callback=suppress_after_callback,
            )

    def _make_ytdl(
        self,
        *,
        for_download: bool,
        youtube_clients: Optional[list[str]] = None,
        format_selector: Optional[str] = None,
    ) -> yt_dlp.YoutubeDL:
        options = copy.deepcopy(YTDL_OPTIONS)
        options.setdefault("quiet", True)
        options.setdefault("no_warnings", True)
        options.setdefault("noplaylist", True)
        options.setdefault("overwrites", False)
        options.setdefault("restrictfilenames", False)
        options.setdefault("logger", logger)
        options.setdefault("cachedir", False)
        options["socket_timeout"] = 15
        options["retries"] = 2
        options["fragment_retries"] = 2
        options["extractor_retries"] = 1

        http_headers = options.get("http_headers")
        if not isinstance(http_headers, dict):
            http_headers = {}
        options["http_headers"] = {**YTDL_HTTP_HEADERS, **http_headers}

        extractor_args = options.get("extractor_args")
        if not isinstance(extractor_args, dict):
            extractor_args = {}

        youtube_args = extractor_args.get("youtube")
        if not isinstance(youtube_args, dict):
            youtube_args = {}

        if youtube_clients is not None:
            youtube_args["player_client"] = list(youtube_clients)
        else:
            configured_clients = youtube_args.get("player_client")
            if isinstance(configured_clients, str):
                configured_clients = [configured_clients]
            if not isinstance(configured_clients, list):
                configured_clients = []

            normalized_clients = [str(client).strip().lower() for client in configured_clients if str(client).strip()]
            if not normalized_clients or any(client in {"android", "ios", "mweb"} for client in normalized_clients):
                youtube_args["player_client"] = ["android_vr", "web", "web_safari"]
        extractor_args["youtube"] = youtube_args
        options["extractor_args"] = extractor_args

        if not for_download:
            options["skip_download"] = True
            options["lazy_playlist"] = True
            options["extract_flat"] = "in_playlist"
            options["playlistend"] = 1
        else:
            options["skip_download"] = True
            options.pop("extract_flat", None)
            options.pop("playlistend", None)
            options["lazy_playlist"] = False
            options["format"] = (
                format_selector
                or "bestaudio[protocol=https][acodec!=none]/bestaudio[acodec!=none]/best[protocol=https]/best"
            )

        return yt_dlp.YoutubeDL(options)

    def _iter_stream_resolution_profiles(self, webpage_url: str) -> list[dict[str, Any]]:
        default_safe_format = (
            "bestaudio[acodec!=none][protocol=https]/"
            "bestaudio[acodec!=none]/best[protocol=https]/best"
        )
        safari_fallback_format = (
            "bestaudio[acodec!=none][protocol=m3u8_native]/"
            "bestaudio[acodec!=none][protocol=https]/"
            "bestaudio[acodec!=none][protocol=m3u8]/"
            "bestaudio[acodec!=none]/best"
        )
        tv_format = "bestaudio[acodec!=none]/bestaudio/best"

        if not _is_youtube_webpage_url(webpage_url):
            return [
                {
                    "name": "default",
                    "youtube_clients": ["android_vr", "web", "web_safari"],
                    "format": default_safe_format,
                }
            ]

        return [
            {
                "name": "default",
                "youtube_clients": ["android_vr", "web", "web_safari"],
                "format": default_safe_format,
            },
            {
                "name": "web_safari",
                "youtube_clients": ["web_safari", "web"],
                "format": safari_fallback_format,
            },
            {
                "name": "tv",
                "youtube_clients": ["tv_simply", "tv", "web"],
                "format": tv_format,
            },
        ]

    def _should_retry_stream_resolution_error(
        self,
        webpage_url: str,
        error: Exception,
        *,
        attempt_index: int,
        total_attempts: int,
    ) -> bool:
        if attempt_index >= total_attempts:
            return False

        if not _is_youtube_webpage_url(webpage_url):
            return False

        message = str(error).lower()
        fatal_markers = (
            "private video",
            "video unavailable",
            "this video is unavailable",
            "not available in your country",
            "members-only",
            "members only",
            "sign in if you've been granted access",
            "live event will begin",
            "premieres in",
        )
        if any(marker in message for marker in fatal_markers):
            return False

        retry_markers = (
            "needs to be reloaded",
            "requested format is not available",
            "unable to extract initial player response",
            "http error 403",
            "forbidden",
            "timed out",
            "connection reset",
            "remote end closed connection",
            "temporarily unavailable",
            "precondition check failed",
        )
        if any(marker in message for marker in retry_markers):
            return True

        return isinstance(
            error,
            (
                yt_dlp.utils.DownloadError,
                yt_dlp.utils.ExtractorError,
                TimeoutError,
            ),
        )

    def _make_search_term(self, query: str) -> str:
        actual_query = query.strip()

        if actual_query.lower().startswith("scsearch1:"):
            return actual_query

        if _looks_like_url(actual_query):
            return actual_query

        return f"ytsearch1:{actual_query}"

    def _flatten_info_entries(self, info: dict[str, Any]) -> list[dict[str, Any]]:
        if not info:
            return []

        if "entries" in info and info["entries"]:
            return [entry for entry in info["entries"] if entry]

        return [info]

    def _resolve_webpage_url(self, info: dict[str, Any]) -> Optional[str]:
        candidates = [
            info.get("webpage_url"),
            info.get("original_url"),
            info.get("url"),
        ]

        for candidate in candidates:
            if isinstance(candidate, str) and _is_probable_webpage_url(candidate):
                return candidate

        video_id = info.get("id")
        extractor = (info.get("extractor") or info.get("extractor_key") or "").lower()
        if video_id and "youtube" in extractor:
            return f"https://www.youtube.com/watch?v={video_id}"

        return None

    def _extract_stream_url_from_info(self, info: dict[str, Any]) -> Optional[str]:
        direct_url = info.get("url")
        if isinstance(direct_url, str) and _is_probable_stream_url(direct_url):
            return direct_url

        requested_formats = info.get("requested_formats") or []
        if isinstance(requested_formats, list):
            for fmt in requested_formats:
                if not isinstance(fmt, dict):
                    continue
                url = fmt.get("url")
                acodec = fmt.get("acodec")
                if isinstance(url, str) and _is_probable_stream_url(url) and acodec != "none":
                    return url

        formats = info.get("formats") or []
        if isinstance(formats, list):
            best_url = None
            best_score = -1

            for fmt in formats:
                if not isinstance(fmt, dict):
                    continue

                url = fmt.get("url")
                if not isinstance(url, str) or not _is_probable_stream_url(url):
                    continue

                acodec = fmt.get("acodec")
                vcodec = fmt.get("vcodec")
                protocol = str(fmt.get("protocol") or "").lower()
                abr = fmt.get("abr")
                ext = str(fmt.get("ext") or "").lower()

                if not acodec or acodec == "none":
                    continue

                score = 0
                if vcodec == "none":
                    score += 100
                if protocol in {"https", "http"}:
                    score += 45
                elif protocol in {"m3u8", "m3u8_native"}:
                    score -= 15
                if ext in {"m4a", "webm", "mp4"}:
                    score += 10
                if isinstance(abr, (int, float)):
                    score += int(abr)

                if score > best_score:
                    best_score = score
                    best_url = url

            if best_url:
                return best_url

        return None

    def _build_track_from_info(
        self,
        info: dict[str, Any],
        *,
        requester: discord.abc.User,
        channel: Optional[discord.abc.Messageable],
        playback_preset: str = "normal",
        original_query: Optional[str] = None,
    ) -> QueuedTrack:
        duration = info.get("duration")
        duration_int = int(duration) if isinstance(duration, (int, float)) else None

        webpage_url = self._resolve_webpage_url(info)
        stream_url = self._extract_stream_url_from_info(info)

        return QueuedTrack(
            title=info.get("title") or "Untitled",
            requester=requester,
            webpage_url=webpage_url,
            thumbnail=info.get("thumbnail"),
            uploader=info.get("uploader") or info.get("channel"),
            duration=duration_int,
            channel=channel,
            playback_preset=playback_preset,
            info=info,
            original_query=original_query,
            stream_url=stream_url,
        )

    def _clone_track(self, track: QueuedTrack) -> QueuedTrack:
        return QueuedTrack(
            title=track.title,
            requester=track.requester,
            webpage_url=track.webpage_url,
            thumbnail=track.thumbnail,
            uploader=track.uploader,
            duration=track.duration,
            channel=track.channel,
            playback_preset=track.playback_preset,
            info=copy.deepcopy(track.info),
            local_path=Path(track.local_path) if track.local_path else None,
            original_query=track.original_query,
            stream_url=track.stream_url,
            playback_rate=track.playback_rate,
        )

    def _remember_previous_track(self, track: Optional[QueuedTrack]) -> None:
        if not track:
            return

        self.previous_track_data = {
            "title": track.title,
            "webpage_url": track.webpage_url,
            "thumbnail": track.thumbnail,
            "uploader": track.uploader,
            "duration": track.duration,
            "requester": track.requester,
            "channel": track.channel,
            "playback_preset": track.playback_preset,
            "info": copy.deepcopy(track.info),
            "local_path": str(track.local_path) if track.local_path else None,
            "original_query": track.original_query,
            "stream_url": track.stream_url,
            "playback_rate": track.playback_rate,
        }

    def _get_display_name(self, user: discord.abc.User) -> str:
        for attr in ("display_name", "global_name", "name"):
            value = getattr(user, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return "unknown"

    def _load_song_history_sync(self) -> dict[str, dict[str, list[dict[str, Any]]]]:
        if not self._song_history_path.exists():
            return {}

        try:
            payload = json.loads(self._song_history_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to load song history from %s", self._song_history_path, exc_info=True)
            return {}

        if not isinstance(payload, dict):
            return {}

        normalized: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for guild_key, user_map in payload.items():
            if not isinstance(user_map, dict):
                continue

            cleaned_user_map: dict[str, list[dict[str, Any]]] = {}
            for user_key, entries in user_map.items():
                if not isinstance(entries, list):
                    continue

                cleaned_entries: list[dict[str, Any]] = []
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue

                    title = str(entry.get("title") or "").strip()
                    if not title:
                        continue

                    webpage_url = entry.get("webpage_url")
                    requester_display_name = entry.get("requester_display_name")
                    timestamp = entry.get("timestamp")

                    cleaned_entries.append(
                        {
                            "title": title,
                            "webpage_url": webpage_url if isinstance(webpage_url, str) and webpage_url.strip() else None,
                            "requester_display_name": (
                                requester_display_name.strip()
                                if isinstance(requester_display_name, str) and requester_display_name.strip()
                                else None
                            ),
                            "timestamp": timestamp if isinstance(timestamp, str) and timestamp.strip() else None,
                        }
                    )

                if cleaned_entries:
                    cleaned_user_map[str(user_key)] = cleaned_entries[:SONG_HISTORY_MAX_ENTRIES_PER_USER]

            if cleaned_user_map:
                normalized[str(guild_key)] = cleaned_user_map

        return normalized

    def _save_song_history_sync(self) -> None:
        self._song_history_path.write_text(
            json.dumps(self._song_history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def _persist_song_history(self) -> None:
        await asyncio.to_thread(self._save_song_history_sync)

    async def _record_tracks_in_history(
        self,
        *,
        guild: Optional[discord.Guild],
        requester: discord.abc.User,
        tracks: list[QueuedTrack],
    ) -> None:
        if guild is None or not tracks:
            return

        signature = (
            guild.id,
            requester.id,
            tuple(f"{track.title}|{track.webpage_url or track.original_query or ''}" for track in tracks),
        )
        now = time.monotonic()

        async with self._history_lock:
            if (
                self._last_history_record_signature == signature
                and (now - self._last_history_recorded_at_monotonic) < SONG_HISTORY_DUPLICATE_WINDOW_SECONDS
            ):
                logger.debug(
                    "Skipping duplicate history write for requester=%s guild=%s",
                    requester.id,
                    guild.id,
                )
                return

            guild_key = str(guild.id)
            user_key = str(requester.id)
            guild_history = self._song_history.setdefault(guild_key, {})
            user_history = guild_history.setdefault(user_key, [])
            requester_name = self._get_display_name(requester)
            recorded_at = discord.utils.utcnow().isoformat()

            for track in tracks:
                title = (track.title or "Untitled").strip()
                if not title:
                    continue

                user_history.insert(
                    0,
                    {
                        "title": title,
                        "webpage_url": track.webpage_url,
                        "requester_display_name": requester_name,
                        "timestamp": recorded_at,
                    },
                )

            del user_history[SONG_HISTORY_MAX_ENTRIES_PER_USER:]
            self._last_history_record_signature = signature
            self._last_history_recorded_at_monotonic = now
            await self._persist_song_history()

    def _get_user_song_history_entries(
        self,
        *,
        guild: Optional[discord.Guild],
        target_user: discord.abc.User,
    ) -> list[dict[str, Any]]:
        if guild is None:
            return []

        guild_key = str(guild.id)
        user_key = str(target_user.id)
        return copy.deepcopy(self._song_history.get(guild_key, {}).get(user_key, []))

    def _build_history_embed(
        self,
        *,
        target_user: discord.abc.User,
        entries: list[dict[str, Any]],
        page: int,
        total_pages: int,
    ) -> discord.Embed:
        display_name = self._get_display_name(target_user)
        start_index = (page - 1) * SONG_HISTORY_PAGE_SIZE
        lines = []
        for offset, entry in enumerate(entries, start=start_index + 1):
            lines.append(f"{offset}. {entry.get('title', 'Untitled')}")

        embed = discord.Embed(
            title=f"History for {display_name}",
            description="\n".join(lines) or "No songs recorded yet.",
            color=HELP_EMBED_COLOR,
        )
        embed.set_footer(text=f"Page {page}/{total_pages}")
        return embed

    def _get_most_played_for_user(
        self,
        *,
        guild: Optional[discord.Guild],
        target_user: discord.abc.User,
    ) -> list[dict[str, Any]]:
        user_history = self._get_user_song_history_entries(guild=guild, target_user=target_user)
        aggregates: dict[str, dict[str, Any]] = {}

        for index, entry in enumerate(user_history):
            title = str(entry.get("title") or "").strip()
            if not title:
                continue

            aggregate = aggregates.get(title)
            if aggregate is None:
                aggregates[title] = {
                    "title": title,
                    "count": 1,
                    "recent_index": index,
                }
                continue

            aggregate["count"] += 1

        return sorted(
            aggregates.values(),
            key=lambda item: (-int(item["count"]), int(item["recent_index"]), str(item["title"]).lower()),
        )

    def _build_most_played_embed(
        self,
        *,
        target_user: discord.abc.User,
        entries: list[dict[str, Any]],
        page: int,
        total_pages: int,
    ) -> discord.Embed:
        display_name = self._get_display_name(target_user)
        start_index = (page - 1) * SONG_HISTORY_PAGE_SIZE
        lines = []
        for offset, entry in enumerate(entries, start=start_index + 1):
            count = int(entry.get("count", 0))
            play_label = "play" if count == 1 else "plays"
            lines.append(f"{offset}. {entry.get('title', 'Untitled')} ? {count} {play_label}")

        embed = discord.Embed(
            title=f"Most Played for {display_name}",
            description="\n".join(lines) or "No songs recorded yet.",
            color=HELP_EMBED_COLOR,
        )
        embed.set_footer(text=f"Page {page}/{total_pages}")
        return embed

    async def history_func(
        self,
        message: discord.Message,
        *,
        target_user: Optional[discord.abc.User] = None,
        page: int = 1,
    ) -> str:
        if message.guild is None:
            await message.reply("Song history is only available inside a server.")
            return "History unavailable in DMs"

        target = target_user or message.author
        async with self._history_lock:
            user_history = self._get_user_song_history_entries(guild=message.guild, target_user=target)

        if not user_history:
            await message.reply(f"No song history found for {self._get_display_name(target)} yet.")
            return "No history"

        total_pages = max(1, (len(user_history) + SONG_HISTORY_PAGE_SIZE - 1) // SONG_HISTORY_PAGE_SIZE)
        page = max(1, min(page, total_pages))
        start_index = (page - 1) * SONG_HISTORY_PAGE_SIZE
        entries = user_history[start_index:start_index + SONG_HISTORY_PAGE_SIZE]

        await message.reply(
            embed=self._build_history_embed(
                target_user=target,
                entries=entries,
                page=page,
                total_pages=total_pages,
            )
        )
        return f"History page {page}/{total_pages} for {self._get_display_name(target)}"

    async def most_played_func(
        self,
        message: discord.Message,
        *,
        target_user: Optional[discord.abc.User] = None,
        page: int = 1,
    ) -> str:
        if message.guild is None:
            await message.reply("Most played songs are only available inside a server.")
            return "Most played unavailable in DMs"

        target = target_user or message.author
        async with self._history_lock:
            ranked_entries = self._get_most_played_for_user(guild=message.guild, target_user=target)

        if not ranked_entries:
            await message.reply(f"No song history found for {self._get_display_name(target)} yet.")
            return "No history"

        total_pages = max(1, (len(ranked_entries) + SONG_HISTORY_PAGE_SIZE - 1) // SONG_HISTORY_PAGE_SIZE)
        page = max(1, min(page, total_pages))
        start_index = (page - 1) * SONG_HISTORY_PAGE_SIZE
        entries = ranked_entries[start_index:start_index + SONG_HISTORY_PAGE_SIZE]

        await message.reply(
            embed=self._build_most_played_embed(
                target_user=target,
                entries=entries,
                page=page,
                total_pages=total_pages,
            )
        )
        return f"Most played page {page}/{total_pages} for {self._get_display_name(target)}"

    def _widget_renderer_available(self) -> bool:
        return all(
            part is not None
            for part in (Image, ImageDraw, ImageFilter, ImageFont, ImageOps)
        )

    def _get_track_artist_name(self, track: QueuedTrack) -> str:
        info = track.info or {}
        candidates = (
            info.get("artist"),
            info.get("album_artist"),
            track.uploader,
            info.get("uploader"),
            info.get("channel"),
        )

        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()

        return "Unknown Artist"

    def _get_track_requester_name(self, track: QueuedTrack) -> str:
        requester = track.requester
        for attr in ("display_name", "global_name", "name"):
            value = getattr(requester, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return "unknown"

    def _get_track_duration_label(self, track: QueuedTrack) -> str:
        if isinstance(track.duration, int) and track.duration > 0:
            return format_duration(track.duration)
        return "LIVE"

    def _get_track_artist_badge_text(self, track: QueuedTrack) -> str:
        artist = self._get_track_artist_name(track)
        first = next((char for char in artist.strip() if char.isalnum()), "M")
        return first.upper()

    def _get_track_cover_url(self, track: QueuedTrack) -> Optional[str]:
        info = track.info or {}
        direct_candidates = (
            track.thumbnail,
            info.get("thumbnail"),
            info.get("artwork_url"),
            info.get("album_art"),
        )

        for candidate in direct_candidates:
            if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                return candidate

        thumbnails = info.get("thumbnails")
        best_thumbnail_url = None
        best_area = -1
        if isinstance(thumbnails, list):
            for thumb in thumbnails:
                if not isinstance(thumb, dict):
                    continue

                url = thumb.get("url")
                if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                    continue

                width = thumb.get("width")
                height = thumb.get("height")
                area = width * height if isinstance(width, int) and isinstance(height, int) else 0
                if area >= best_area:
                    best_area = area
                    best_thumbnail_url = url

        if best_thumbnail_url:
            return best_thumbnail_url

        video_id = info.get("id")
        extractor = str(info.get("extractor") or info.get("extractor_key") or "").lower()
        if isinstance(video_id, str) and video_id and "youtube" in extractor:
            return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

        return None

    def _download_widget_image_bytes(self, url: str) -> Optional[bytes]:
        try:
            response = requests.get(
                url,
                headers=NOW_PLAYING_WIDGET_REQUEST_HEADERS,
                timeout=15,
            )
            response.raise_for_status()
        except requests.RequestException:
            logger.debug("Failed to fetch widget image: %s", url, exc_info=True)
            return None

        return response.content or None

    def _build_widget_snapshot_track(
        self,
        track_data: Optional[dict[str, Any]],
    ) -> Optional[QueuedTrack]:
        if not track_data:
            return None

        local_path = track_data.get("local_path")
        requester = track_data.get("requester") or self.bot.user or discord.Object(id=0)

        return QueuedTrack(
            title=track_data.get("title") or "Untitled",
            requester=requester,
            webpage_url=track_data.get("webpage_url"),
            thumbnail=track_data.get("thumbnail"),
            uploader=track_data.get("uploader"),
            duration=track_data.get("duration"),
            channel=track_data.get("channel"),
            playback_preset=track_data.get("playback_preset") or "normal",
            info=copy.deepcopy(track_data.get("info") or {}),
            local_path=Path(local_path) if isinstance(local_path, str) and local_path else None,
            original_query=track_data.get("original_query"),
            stream_url=track_data.get("stream_url"),
        )

    def _create_widget_placeholder_cover(self, track: QueuedTrack):
        if not self._widget_renderer_available():
            raise RuntimeError("Pillow is not available for widget rendering.")

        size = 640
        canvas = Image.new("RGBA", (size, size), (30, 34, 46, 255))
        overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)

        for y in range(size):
            blend = y / max(size - 1, 1)
            red = int(40 + (215 - 40) * blend)
            green = int(46 + (138 - 46) * blend)
            blue = int(66 + (88 - 66) * blend)
            overlay_draw.line((0, y, size, y), fill=(red, green, blue, 255))

        overlay_draw.ellipse((-120, -60, 340, 340), fill=(255, 255, 255, 45))
        overlay_draw.ellipse((240, 200, 760, 780), fill=(255, 214, 179, 55))
        overlay_draw.rounded_rectangle(
            (48, 48, size - 48, size - 48),
            radius=72,
            outline=(255, 255, 255, 48),
            width=3,
        )
        overlay = overlay.filter(ImageFilter.GaussianBlur(4))
        canvas.alpha_composite(overlay)

        draw = ImageDraw.Draw(canvas)
        title_font = _load_widget_font(84, bold=True)
        subtitle_font = _load_widget_font(26, bold=False)

        draw.text(
            (size / 2, size / 2 - 24),
            "MUSIC",
            font=title_font,
            fill=(248, 244, 238, 255),
            anchor="mm",
        )
        draw.text(
            (size / 2, size / 2 + 52),
            _truncate_text(draw, self._get_track_artist_name(track), subtitle_font, 340),
            font=subtitle_font,
            fill=(248, 244, 238, 190),
            anchor="mm",
        )
        return canvas

    def _load_cover_art_image(self, track: QueuedTrack, *, size: int):
        if not self._widget_renderer_available():
            raise RuntimeError("Pillow is not available for widget rendering.")

        # 1. LEFT-SIDE COVER IMAGE IS LOADED HERE.
        cover_url = self._get_track_cover_url(track)
        if cover_url:
            image_bytes = self._download_widget_image_bytes(cover_url)
            if image_bytes:
                with contextlib.suppress(Exception):
                    with Image.open(BytesIO(image_bytes)) as source_image:
                        return ImageOps.fit(
                            source_image.convert("RGB"),
                            (size, size),
                            method=_widget_resample_filter(),
                        )

        placeholder = self._create_widget_placeholder_cover(track)
        return ImageOps.fit(
            placeholder.convert("RGB"),
            (size, size),
            method=_widget_resample_filter(),
        )

    def _draw_now_playing_widget(self, track: QueuedTrack):
        if not self._widget_renderer_available():
            raise RuntimeError("Pillow is not available for widget rendering.")

        width = NOW_PLAYING_WIDGET_WIDTH
        height = NOW_PLAYING_WIDGET_HEIGHT
        card = Image.new("RGBA", (width, height), (246, 243, 238, 255))
        draw = ImageDraw.Draw(card)

        cover_size = 288
        cover_x = 46
        cover_y = 46

        cover_shadow = Image.new("RGBA", (cover_size + 28, cover_size + 28), (0, 0, 0, 0))
        cover_shadow_draw = ImageDraw.Draw(cover_shadow)
        cover_shadow_draw.rounded_rectangle(
            (12, 10, cover_size + 10, cover_size + 10),
            radius=40,
            fill=(16, 22, 31, 72),
        )
        cover_shadow = cover_shadow.filter(ImageFilter.GaussianBlur(12))
        card.alpha_composite(cover_shadow, (cover_x - 10, cover_y - 8))

        cover_image = self._load_cover_art_image(track, size=cover_size).convert("RGBA")
        cover_mask = Image.new("L", (cover_size, cover_size), 0)
        cover_mask_draw = ImageDraw.Draw(cover_mask)
        cover_mask_draw.rounded_rectangle(
            (0, 0, cover_size, cover_size),
            radius=36,
            fill=255,
        )
        card.paste(cover_image, (cover_x, cover_y), cover_mask)

        right_x = 384
        content_width = width - right_x - 44

        badge_font = _load_widget_font(22, bold=True)
        title_font = _load_widget_font(56, bold=True)
        artist_font = _load_widget_font(42, bold=False)
        requester_font = _load_widget_font(28, bold=False)
        artist_badge_font = _load_widget_font(20, bold=True)
        duration_font = _load_widget_font(30, bold=False)

        badge_text = "NOW PLAYING"
        badge_width = int(_measure_text(draw, badge_text, badge_font)) + 42
        badge_height = 40
        badge_y = 56
        draw.rounded_rectangle(
            (right_x, badge_y, right_x + badge_width, badge_y + badge_height),
            radius=20,
            fill=(34, 40, 51, 255),
        )
        draw.text(
            (right_x + badge_width / 2, badge_y + badge_height / 2 - 1),
            badge_text,
            font=badge_font,
            fill=(251, 248, 243, 255),
            anchor="mm",
        )

        title = _truncate_text(draw, track.title or "Untitled", title_font, content_width)
        draw.text(
            (right_x, 102),
            title,
            font=title_font,
            fill=(23, 26, 31, 255),
        )

        artist_icon_size = 34
        artist_row_y = 186
        draw.rounded_rectangle(
            (right_x, artist_row_y, right_x + artist_icon_size, artist_row_y + artist_icon_size),
            radius=10,
            fill=(24, 27, 33, 255),
        )
        draw.text(
            (right_x + artist_icon_size / 2, artist_row_y + artist_icon_size / 2 - 1),
            self._get_track_artist_badge_text(track),
            font=artist_badge_font,
            fill=(250, 246, 241, 255),
            anchor="mm",
        )

        artist_name = _truncate_text(
            draw,
            self._get_track_artist_name(track),
            artist_font,
            content_width - artist_icon_size - 20,
        )
        draw.text(
            (right_x + artist_icon_size + 14, artist_row_y - 7),
            artist_name,
            font=artist_font,
            fill=(55, 59, 65, 255),
        )

        requester_text = _truncate_text(
            draw,
            f"Requested by {self._get_track_requester_name(track)}",
            requester_font,
            content_width,
        )
        draw.text(
            (right_x, 244),
            requester_text,
            font=requester_font,
            fill=(118, 114, 109, 255),
        )

        indicator_x = right_x
        indicator_y = height - 92
        draw.ellipse(
            (indicator_x, indicator_y, indicator_x + 32, indicator_y + 32),
            fill=(246, 243, 238, 255),
            outline=(212, 205, 195, 255),
            width=3,
        )
        draw.arc(
            (indicator_x + 5, indicator_y + 5, indicator_x + 27, indicator_y + 27),
            start=300,
            end=60,
            fill=(32, 37, 47, 255),
            width=4,
        )
        draw.ellipse(
            (indicator_x + 10, indicator_y + 10, indicator_x + 16, indicator_y + 16),
            fill=(32, 37, 47, 255),
        )

        duration_text = self._get_track_duration_label(track)
        duration_width = int(_measure_text(draw, duration_text, duration_font)) + 54
        duration_height = 44
        duration_x = width - 44 - duration_width
        duration_y = height - 88
        draw.rounded_rectangle(
            (duration_x, duration_y, duration_x + duration_width, duration_y + duration_height),
            radius=22,
            fill=(232, 227, 220, 255),
            outline=(210, 203, 195, 255),
            width=2,
        )
        draw.ellipse(
            (duration_x + 14, duration_y + 13, duration_x + 26, duration_y + 25),
            outline=(60, 64, 71, 255),
            width=2,
        )
        draw.ellipse(
            (duration_x + 19, duration_y + 18, duration_x + 21, duration_y + 20),
            fill=(60, 64, 71, 255),
        )
        draw.text(
            (duration_x + 34, duration_y + duration_height / 2 - 1),
            duration_text,
            font=duration_font,
            fill=(70, 73, 80, 255),
            anchor="lm",
        )

        rounded_mask = Image.new("L", (width, height), 0)
        rounded_mask_draw = ImageDraw.Draw(rounded_mask)
        rounded_mask_draw.rounded_rectangle(
            (0, 0, width - 1, height - 1),
            radius=46,
            fill=255,
        )

        clipped_card = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        clipped_card.paste(card, (0, 0), rounded_mask)
        clipped_draw = ImageDraw.Draw(clipped_card)
        clipped_draw.rounded_rectangle(
            (1, 1, width - 2, height - 2),
            radius=46,
            outline=(225, 219, 211, 255),
            width=2,
        )
        return clipped_card

    def _render_widget_buffer(self, track: QueuedTrack) -> tuple[BytesIO, str]:
        current_card = self._draw_now_playing_widget(track)
        buffer = BytesIO()
        current_card.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer, NOW_PLAYING_WIDGET_FILENAME

    def _render_widget_transition_buffer(
        self,
        previous_track: QueuedTrack,
        current_track: QueuedTrack,
    ) -> tuple[BytesIO, str]:
        previous_card = self._draw_now_playing_widget(previous_track)
        current_card = self._draw_now_playing_widget(current_track)
        transition_card = Image.blend(previous_card, current_card, 0.5)

        buffer = BytesIO()
        transition_card.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer, NOW_PLAYING_WIDGET_TRANSITION_FILENAME

    async def _build_now_playing_widget_file(
        self,
        track: QueuedTrack,
    ) -> Optional[discord.File]:
        if not self._widget_renderer_available():
            return None

        try:
            buffer, filename = await asyncio.to_thread(
                self._render_widget_buffer,
                track,
            )
        except Exception:
            logger.exception("Failed to render the now-playing widget for %s", track.title)
            return None

        return discord.File(buffer, filename=filename)

    async def _build_now_playing_transition_widget_file(
        self,
        track: QueuedTrack,
    ) -> Optional[discord.File]:
        if not self._widget_renderer_available():
            return None

        previous_track = self._build_widget_snapshot_track(self.previous_track_data)
        if not previous_track:
            return None

        if (
            previous_track.title == track.title
            and previous_track.webpage_url == track.webpage_url
        ):
            return None

        try:
            buffer, filename = await asyncio.to_thread(
                self._render_widget_transition_buffer,
                previous_track,
                track,
            )
        except Exception:
            logger.exception("Failed to render the transition widget for %s", track.title)
            return None

        return discord.File(buffer, filename=filename)

    def _build_now_playing_widget_embed(
        self,
        track: QueuedTrack,
        *,
        color: discord.Color,
        description: str,
        image_filename: str,
    ) -> discord.Embed:
        embed = discord.Embed(color=color)

        if description and description.lower() != "now playing":
            embed.description = description

        embed.set_image(url=f"attachment://{image_filename}")
        embed.set_footer(text="Use the buttons below to control playback.")
        return embed

    def _sanitize_playback_rate(self, rate: Optional[float], *, minimum: float, maximum: float) -> Optional[float]:
        if rate is None:
            return None
        try:
            value = float(rate)
        except (TypeError, ValueError):
            return None
        return max(minimum, min(maximum, value))

    def _sanitize_numeric_value(
        self,
        value: Any,
        *,
        minimum: float,
        maximum: float,
    ) -> Optional[float]:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return max(minimum, min(maximum, number))

    def _format_filter_value(self, value: float) -> str:
        text = f"{float(value):.2f}"
        text = text.rstrip("0").rstrip(".")
        return text or "0"

    def _filter_group_name(self, effect_name: str) -> Optional[str]:
        for group_name, effects in AUDIO_FILTER_CONFLICT_GROUPS.items():
            if effect_name in effects:
                return group_name
        return None

    def _make_filter_entry(self, effect_name: str, **params: Any) -> AudioFilterEntry:
        clean_params = {key: value for key, value in params.items() if value is not None}
        return AudioFilterEntry(name=effect_name, params=clean_params)

    def _active_filter_entries(self) -> list[AudioFilterEntry]:
        return sorted(
            self._filter_state.effects.values(),
            key=lambda entry: AUDIO_FILTER_ORDER.get(entry.name, 999),
        )

    def _sync_track_filter_metadata(self, track: Optional[QueuedTrack] = None) -> None:
        target = track or self.current
        if target is None:
            return

        if "nightcore" in self._filter_state.effects:
            nightcore = self._filter_state.effects["nightcore"]
            target.playback_preset = "nightcore"
            target.playback_rate = self._sanitize_playback_rate(
                nightcore.params.get("rate"),
                minimum=1.01,
                maximum=2.0,
            )
            return

        if "slow" in self._filter_state.effects:
            target.playback_preset = "slow"
            target.playback_rate = None
            return

        target.playback_preset = "normal"
        target.playback_rate = None

    def _build_atempo_filters(self, tempo: float) -> list[str]:
        value = max(0.25, min(4.0, float(tempo)))
        filters: list[str] = []

        while value < 0.5:
            filters.append("atempo=0.5")
            value /= 0.5

        while value > 2.0:
            filters.append("atempo=2.0")
            value /= 2.0

        filters.append(f"atempo={value:.4f}")
        return filters

    def _build_pitch_preserving_filters(self, pitch: float) -> list[str]:
        scale = max(0.5, min(2.0, float(pitch)))
        filters = [f"asetrate=48000*{scale:.4f}", "aresample=48000"]
        filters.extend(self._build_atempo_filters(1.0 / scale))
        return filters

    def _build_filter_parts_for_entry(self, entry: AudioFilterEntry) -> list[str]:
        name = entry.name
        params = entry.params

        if name == "nightcore":
            # Raise pitch and tempo together for the classic nightcore tone.
            rate = self._sanitize_playback_rate(params.get("rate"), minimum=1.01, maximum=2.0) or 1.45
            return [f"asetrate=48000*{rate:.4f}", "aresample=48000"]

        if name == "bassboost":
            # Lift the low end, then gently compress it so the bass stays usable.
            gain = self._sanitize_numeric_value(params.get("gain", 8.0), minimum=1.0, maximum=20.0) or 8.0
            return [f"bass=g={gain:.2f}:f=110:w=0.6", "acompressor=threshold=0.7:ratio=2:attack=20:release=120"]

        if name == "slow":
            # Preserve the existing slow-mode behavior: deeper and slower at once.
            return ["asetrate=48000*0.8500", "aresample=48000"]

        if name == "speed":
            # Tempo-only acceleration/deceleration.
            rate = self._sanitize_numeric_value(params.get("rate", 1.15), minimum=0.5, maximum=2.0) or 1.15
            return self._build_atempo_filters(rate)

        if name == "pitch":
            # Pitch-shift with tempo compensation so the song length stays practical.
            rate = self._sanitize_numeric_value(params.get("rate", 1.10), minimum=0.5, maximum=2.0) or 1.10
            return self._build_pitch_preserving_filters(rate)

        if name == "reverb":
            # Reverb-like ambience via layered echoes.
            return ["aecho=0.8:0.88:60|120|180:0.20|0.14|0.10"]

        if name == "echo":
            # Cleaner, shorter repeats than the reverb preset.
            return ["aecho=0.8:0.75:60|120:0.30|0.20"]

        if name == "karaoke":
            # Vocal reduction approximation using phase cancellation and band-shaping.
            return ["pan=stereo|c0<c0-c1|c1<c1-c0", "highpass=f=120", "lowpass=f=8000"]

        if name == "tremolo":
            # Amplitude modulation for pulsing volume movement.
            frequency = self._sanitize_numeric_value(params.get("frequency", 5.0), minimum=0.1, maximum=20.0) or 5.0
            depth = self._sanitize_numeric_value(params.get("depth", 0.7), minimum=0.1, maximum=1.0) or 0.7
            return [f"tremolo=f={frequency:.2f}:d={depth:.2f}"]

        if name == "vibrato":
            # Gentle pitch wobble.
            frequency = self._sanitize_numeric_value(params.get("frequency", 6.0), minimum=0.1, maximum=20.0) or 6.0
            depth = self._sanitize_numeric_value(params.get("depth", 0.5), minimum=0.01, maximum=1.0) or 0.5
            return [f"vibrato=f={frequency:.2f}:d={depth:.2f}"]

        if name == "flanger":
            # Swirling comb-filter motion.
            return ["flanger=delay=0:depth=2:regen=0:width=71:speed=0.5:shape=sine:phase=25:interp=linear"]

        if name == "phaser":
            # Phase-cancellation sweep using FFmpeg's aphaser.
            return ["aphaser=in_gain=0.4:out_gain=0.74:delay=3:decay=0.4:speed=0.5:type=t"]

        if name == "chorus":
            # Multi-voice widening chorus.
            return ["chorus=0.5:0.9:50|60|40:0.4|0.3|0.25:0.25|0.4|0.3:2|2.3|1.3"]

        if name == "distortion":
            # Bit-crushed overdrive approximation.
            return ["acrusher=bits=8:mix=0.8:aa=1"]

        if name == "lowpass":
            # Roll off the top end for a warmer or muffled sound.
            frequency = self._sanitize_numeric_value(params.get("frequency", 300.0), minimum=20.0, maximum=20000.0) or 300.0
            return [f"lowpass=f={frequency:.2f}"]

        if name == "highpass":
            # Thin out rumble and heavy low frequencies.
            frequency = self._sanitize_numeric_value(params.get("frequency", 200.0), minimum=20.0, maximum=20000.0) or 200.0
            return [f"highpass=f={frequency:.2f}"]

        if name == "equalizer":
            # Single-band EQ boost/cut centered on the requested frequency.
            frequency = self._sanitize_numeric_value(params.get("frequency", 100.0), minimum=20.0, maximum=20000.0) or 100.0
            gain = self._sanitize_numeric_value(params.get("gain", 2.0), minimum=-20.0, maximum=20.0) or 2.0
            return [f"equalizer=f={frequency:.2f}:t=q:w=1:g={gain:.2f}"]

        if name == "mono":
            # Downmix to mono for a centered, narrow image.
            return ["pan=mono|c0=.5*c0+.5*c1"]

        if name == "stereo_widen":
            # Push the stereo separation outward.
            amount = self._sanitize_numeric_value(params.get("amount", 2.5), minimum=1.0, maximum=10.0) or 2.5
            return [f"extrastereo=m={amount:.2f}"]

        if name == "compressor":
            # Smooth dynamic peaks for a denser, louder mix.
            return ["acompressor=threshold=0.18:ratio=4:attack=20:release=250:makeup=1.5"]

        if name == "gate":
            # Noise gate to clamp quieter tail noise.
            return ["agate=threshold=0.02:ratio=10:attack=20:release=250"]

        if name == "volume_filter":
            # Filter-layer gain separate from the bot's master PCM volume control.
            percent = self._sanitize_numeric_value(params.get("percent", 150.0), minimum=10.0, maximum=300.0) or 150.0
            return [f"volume={percent / 100.0:.4f}"]

        if name == "earrape":
            # Aggressive gain with limiting so it stays audible without total digital collapse.
            return ["volume=2.8000", "acrusher=bits=7:mix=0.25:aa=1", "alimiter=limit=0.97"]

        if name == "vaporwave":
            # Slower, pitched-down, softly filtered retro wash.
            return ["asetrate=48000*0.8000", "aresample=48000", "lowpass=f=3200", "volume=0.95"]

        if name == "lofi":
            # Band-limited texture with mild crunch and gentle compression.
            return ["highpass=f=110", "lowpass=f=3800", "acrusher=bits=10:mix=0.15:aa=1", "acompressor=threshold=0.30:ratio=2.5:attack=15:release=120"]

        if name == "deep":
            # Lower the perceived pitch while adding extra low-end body.
            return self._build_pitch_preserving_filters(0.86) + ["bass=g=4:f=110:w=0.7"]

        if name == "telephone":
            # Narrow band-pass style telephone effect.
            return ["highpass=f=500", "lowpass=f=2600", "volume=1.15"]

        if name == "megaphone":
            # Mid-focused, compressed megaphone coloration.
            return ["highpass=f=350", "lowpass=f=3400", "acompressor=threshold=0.12:ratio=6:attack=5:release=60", "volume=1.35"]

        if name == "robot":
            # Robotic approximation using crushing + phased mid-range emphasis.
            return ["highpass=f=120", "lowpass=f=4500", "acrusher=bits=8:mix=0.35:aa=1", "aphaser=in_gain=0.45:out_gain=0.75:delay=2:decay=0.25:speed=1.2:type=t"]

        if name == "underwater":
            # Muffled waterline effect with a short reflective tail.
            return ["lowpass=f=650", "highpass=f=80", "aecho=0.8:0.6:50|90:0.18|0.12"]

        if name == "8d":
            # Rotating stereo motion approximation.
            return ["apulsator=hz=0.125:amount=0.95:offset_l=0.0:offset_r=0.5"]

        return []

    def _build_active_filter_chain(self, track: QueuedTrack) -> list[str]:
        entries = self._active_filter_entries()
        if not entries:
            if track.playback_preset == "nightcore":
                legacy_rate = self._sanitize_playback_rate(track.playback_rate, minimum=1.01, maximum=2.0) or 1.45
                entries = [self._make_filter_entry("nightcore", rate=legacy_rate)]
            elif track.playback_preset == "slow":
                entries = [self._make_filter_entry("slow")]

        filters: list[str] = []
        active_names: set[str] = set()
        for entry in entries:
            filters.extend(self._build_filter_parts_for_entry(entry))
            active_names.add(entry.name)

        if active_names & {"bassboost", "equalizer", "volume_filter", "earrape", "deep", "megaphone"}:
            filters.append("alimiter=limit=0.97")

        return [part for part in filters if part]

    def _get_filter_arg(self, track: QueuedTrack) -> Optional[str]:
        chain = self._build_active_filter_chain(track)
        if not chain:
            return None
        return ",".join(chain)

    def _describe_filter_entry(self, entry: AudioFilterEntry) -> str:
        label = AUDIO_FILTER_LABELS.get(entry.name, entry.name.replace("_", " ").title())
        params = entry.params

        if entry.name == "nightcore":
            rate = self._sanitize_playback_rate(params.get("rate"), minimum=1.01, maximum=2.0) or 1.45
            return f"{label} {self._format_filter_value(rate)}x"
        if entry.name in {"speed", "pitch"}:
            rate = self._sanitize_numeric_value(params.get("rate", 1.0), minimum=0.5, maximum=2.0) or 1.0
            return f"{label} {self._format_filter_value(rate)}x"
        if entry.name in {"lowpass", "highpass"}:
            frequency = self._sanitize_numeric_value(params.get("frequency"), minimum=20.0, maximum=20000.0)
            if frequency is not None:
                return f"{label} {self._format_filter_value(frequency)}Hz"
        if entry.name == "equalizer":
            frequency = self._sanitize_numeric_value(params.get("frequency"), minimum=20.0, maximum=20000.0)
            gain = self._sanitize_numeric_value(params.get("gain"), minimum=-20.0, maximum=20.0)
            if frequency is not None and gain is not None:
                sign = "+" if gain >= 0 else ""
                return f"{label} {self._format_filter_value(frequency)}Hz {sign}{self._format_filter_value(gain)}dB"
        if entry.name in {"tremolo", "vibrato"}:
            frequency = self._sanitize_numeric_value(params.get("frequency"), minimum=0.1, maximum=20.0)
            depth = self._sanitize_numeric_value(params.get("depth"), minimum=0.01, maximum=1.0)
            if frequency is not None and depth is not None:
                return f"{label} {self._format_filter_value(frequency)} / {self._format_filter_value(depth)}"
        if entry.name == "stereo_widen":
            amount = self._sanitize_numeric_value(params.get("amount"), minimum=1.0, maximum=10.0)
            if amount is not None:
                return f"{label} {self._format_filter_value(amount)}"
        if entry.name == "volume_filter":
            percent = self._sanitize_numeric_value(params.get("percent"), minimum=10.0, maximum=300.0)
            if percent is not None:
                return f"{label} {self._format_filter_value(percent)}%"

        return label

    def _describe_current_filters_text(self) -> str:
        entries = self._active_filter_entries()
        if not entries:
            return "None"
        return ", ".join(self._describe_filter_entry(entry) for entry in entries)

    def _reset_filter_session_state(self, *, reason: str) -> None:
        # Filters are stored at the guild/session layer so they carry across
        # consecutive tracks. When playback truly ends for the session, we clear
        # that state here so the next listening session starts clean.
        if not self._filter_state.effects:
            return

        logger.info(
            "Resetting session filter state (%s): %s",
            reason,
            self._describe_current_filters_text(),
        )
        self._filter_state.effects.clear()
        if self.current is not None:
            self._sync_track_filter_metadata(self.current)

    def _cancel_progress_update_task(self) -> None:
        if self._progress_update_task and not self._progress_update_task.done():
            self._progress_update_task.cancel()
        self._progress_update_task = None

    def _cancel_widget_transition_task(self) -> None:
        if self._widget_transition_task and not self._widget_transition_task.done():
            self._widget_transition_task.cancel()
        self._widget_transition_task = None

    async def _complete_widget_transition(
        self,
        *,
        message: discord.Message,
        view: MusicControlView,
        widget_file: discord.File,
        transition_nonce: int,
    ) -> None:
        try:
            await asyncio.sleep(NOW_PLAYING_WIDGET_TRANSITION_DELAY_SECONDS)

            if transition_nonce != self._widget_transition_nonce:
                return

            if self._active_control_message != message or self._active_control_view != view:
                return

            await message.edit(
                view=view,
                attachments=[widget_file],
                content=None,
            )
        except asyncio.CancelledError:
            return
        except (discord.HTTPException, TypeError):
            logger.debug(
                "Skipped widget transition completion for %s",
                getattr(self.current, "title", "unknown track"),
                exc_info=True,
            )
        finally:
            if asyncio.current_task() is self._widget_transition_task:
                self._widget_transition_task = None

    def _ensure_progress_update_task(self) -> None:
        if self._progress_update_task and not self._progress_update_task.done():
            return
        self._progress_update_task = asyncio.create_task(self._progress_update_loop())

    async def _progress_update_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(2.0)

                if not self._active_control_message or not self._active_control_view:
                    break

                if self._active_control_uses_widget_image:
                    break

                if not self.current:
                    continue

                if self._vc_active():
                    await self._refresh_active_controls(force=True)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Progress update loop failed")

    def _get_progress_text(self, track: QueuedTrack) -> str:
        progress = self._get_current_progress_seconds()
        current_text = format_duration(progress)

        if isinstance(track.duration, int) and track.duration > 0:
            total_text = format_duration(track.duration)
            return f"{current_text} / {total_text}"

        return current_text

    async def _disable_active_controls(self) -> None:
        self._cancel_widget_transition_task()

        if not self._active_control_view or not self._active_control_message:
            self._cancel_progress_update_task()
            return

        for child in self._active_control_view.children:
            child.disabled = True

        with contextlib.suppress(discord.HTTPException):
            if self._active_control_uses_widget_image:
                await self._active_control_message.edit(view=self._active_control_view)
            else:
                embed = None
                if self.current:
                    embed = self._build_track_embed(
                        self.current,
                        color=self._active_control_color,
                        description=self._active_control_description,
                    )

                await self._active_control_message.edit(
                    embed=embed,
                    view=self._active_control_view,
                )

        self._active_control_view.stop()
        self._active_control_message = None
        self._active_control_view = None
        self._active_control_uses_widget_image = False
        self._last_control_refresh_monotonic = 0.0
        self._cancel_progress_update_task()

    async def lyrics_func(self, message: discord.Message) -> str:
        if not self.current:
            await message.reply("Nothing is playing right now.")
            return "Nothing is playing"

        title = self.current.title
        artist = self.current.uploader

        status_msg = await message.reply("Fetching lyrics...")

        try:
            lyrics = await asyncio.to_thread(fetch_lyrics, title, artist)
        except Exception:
            logger.exception("Lyrics fetch failed")
            await status_msg.edit(content="Couldn't fetch lyrics.")
            return "Lyrics fetch failed"

        if not lyrics:
            await status_msg.edit(content="Couldn't find lyrics for this track.")
            return "Lyrics not found"

        chunks = []
        max_len = 1900
        text = lyrics.strip()

        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break

            split_at = text.rfind("\n", 0, max_len)
            if split_at == -1:
                split_at = max_len

            chunk = text[:split_at].strip()
            if chunk:
                chunks.append(chunk)

            text = text[split_at:].strip()

        await status_msg.edit(content=f"**Lyrics for:** {title}")

        for chunk in chunks[:4]:
            await message.channel.send(chunk)

        if len(chunks) > 4:
            await message.channel.send("...lyrics truncated.")

        return f"Lyrics sent for: {title}"

    async def _refresh_active_controls(self, *, force: bool = False) -> None:
        if not self._active_control_view or not self._active_control_message:
            return

        now = time.monotonic()
        if not force and (now - self._last_control_refresh_monotonic) < 0.75:
            return

        async with self._control_refresh_lock:
            if not self._active_control_view or not self._active_control_message:
                return

            now = time.monotonic()
            if not force and (now - self._last_control_refresh_monotonic) < 0.75:
                return

            self._active_control_view._sync_styles()

            try:
                if self._active_control_uses_widget_image:
                    await self._active_control_message.edit(view=self._active_control_view)
                else:
                    embed = None
                    if self.current:
                        embed = self._build_track_embed(
                            self.current,
                            color=self._active_control_color,
                            description=self._active_control_description,
                        )

                    await self._active_control_message.edit(
                        embed=embed,
                        view=self._active_control_view,
                    )
            except discord.HTTPException:
                logger.debug("Skipped control view refresh due to HTTPException", exc_info=True)
                return

            self._last_control_refresh_monotonic = time.monotonic()

    def _apply_volume_to_source(self) -> None:
        if self._current_source is not None:
            self._current_source.volume = self.volume

    def _update_playback_clock_on_pause(self) -> None:
        if self._current_started_monotonic is None:
            return

        elapsed = max(0.0, time.monotonic() - self._current_started_monotonic)
        self._current_position_base_seconds += int(elapsed)
        self._current_started_monotonic = None

    def _update_playback_clock_on_resume(self) -> None:
        self._current_started_monotonic = time.monotonic()

    def _reset_playback_clock(self, *, start_seconds: int = 0) -> None:
        self._current_position_base_seconds = max(0, start_seconds)
        self._current_started_monotonic = None

    def _search_tracks_sync(self, query: str) -> list[dict[str, Any]]:
        search_term = self._make_search_term(query)
        started_at = time.monotonic()
        logger.info("Starting yt-dlp search for query=%s", query)

        with self._make_ytdl(for_download=False, youtube_clients=["web"]) as ydl:
            info = ydl.extract_info(search_term, download=False)

        entries = self._flatten_info_entries(info)
        logger.info(
            "Finished yt-dlp search for query=%s in %.2fs (%s result(s))",
            query,
            time.monotonic() - started_at,
            len(entries),
        )
        return entries

    async def _search_tracks(self, query: str) -> list[dict[str, Any]]:
        try:
            return await asyncio.to_thread(self._search_tracks_sync, query)
        except Exception:
            logger.exception("Track search failed")
            return []

    def _extract_track_from_direct_url_sync(
        self,
        query: str,
    ) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        started_at = time.monotonic()
        logger.info("Starting direct media URL extraction for %s", query)

        info, stream_url = self._download_track_sync(query)
        if info and stream_url:
            enriched_info = copy.deepcopy(info)
            enriched_info.setdefault("webpage_url", self._resolve_webpage_url(enriched_info) or query)
            enriched_info["url"] = stream_url
            logger.info(
                "Finished direct media URL extraction for %s in %.2fs",
                query,
                time.monotonic() - started_at,
            )
            return enriched_info, stream_url

        logger.warning(
            "Direct media URL extraction did not yield a playable stream for %s in %.2fs",
            query,
            time.monotonic() - started_at,
        )
        return info, stream_url

    async def _extract_track_from_direct_url(
        self,
        query: str,
        *,
        requester: discord.abc.User,
        channel: Optional[discord.abc.Messageable],
        playback_preset: str = "normal",
        original_query: Optional[str] = None,
    ) -> Optional[QueuedTrack]:
        try:
            info, stream_url = await asyncio.to_thread(self._extract_track_from_direct_url_sync, query)
        except Exception:
            logger.exception("Direct media URL extraction failed for %s", query)
            return None

        if not info or not stream_url:
            return None

        track = self._build_track_from_info(
            info,
            requester=requester,
            channel=channel,
            playback_preset=playback_preset,
            original_query=original_query,
        )
        track.stream_url = stream_url
        if not track.webpage_url:
            track.webpage_url = query
        return track

    def _is_playlist_query(self, query: str) -> bool:
        if not _looks_like_url(query):
            return False

        parsed = urlparse(query)
        hostname = (parsed.hostname or "").lower()
        path = (parsed.path or "").lower()
        query_params = parsed.query.lower()

        if "youtube.com" in hostname or "youtu.be" in hostname:
            return "list=" in query_params or "/playlist" in path

        if "soundcloud.com" in hostname or "on.soundcloud.com" in hostname:
            return "/sets/" in path

        return False

    def _extract_playlist_entries_sync(self, query: str) -> list[dict[str, Any]]:
        started_at = time.monotonic()
        logger.info("Starting playlist extraction for query=%s", query)

        options = copy.deepcopy(YTDL_OPTIONS)
        options.setdefault("quiet", True)
        options.setdefault("no_warnings", True)
        options.setdefault("overwrites", False)
        options.setdefault("restrictfilenames", False)
        options.setdefault("logger", logger)
        options.setdefault("cachedir", False)
        options["skip_download"] = True
        options["lazy_playlist"] = True
        options["extract_flat"] = "in_playlist"
        options["playlistend"] = PLAYLIST_MAX_ENTRIES
        options["noplaylist"] = False
        options["ignoreerrors"] = True
        options["socket_timeout"] = 15
        options["retries"] = 2
        options["fragment_retries"] = 2
        options["extractor_retries"] = 1

        http_headers = options.get("http_headers")
        if not isinstance(http_headers, dict):
            http_headers = {}
        options["http_headers"] = {**YTDL_HTTP_HEADERS, **http_headers}

        extractor_args = options.get("extractor_args")
        if not isinstance(extractor_args, dict):
            extractor_args = {}
        youtube_args = extractor_args.get("youtube")
        if not isinstance(youtube_args, dict):
            youtube_args = {}
        youtube_args["player_client"] = ["android_vr", "web", "web_safari"]
        extractor_args["youtube"] = youtube_args
        options["extractor_args"] = extractor_args

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(query, download=False)

        entries = []
        if isinstance(info, dict):
            raw_entries = info.get("entries") or []
            if isinstance(raw_entries, list):
                entries = [entry for entry in raw_entries if isinstance(entry, dict)]

        logger.info(
            "Finished playlist extraction for query=%s in %.2fs (%s track(s))",
            query,
            time.monotonic() - started_at,
            len(entries),
        )
        return entries[:PLAYLIST_MAX_ENTRIES]

    async def _extract_playlist_tracks(
        self,
        query: str,
        *,
        requester: discord.abc.User,
        channel: Optional[discord.abc.Messageable],
        playback_preset: str = "normal",
        original_query: Optional[str] = None,
    ) -> list[QueuedTrack]:
        try:
            infos = await asyncio.to_thread(self._extract_playlist_entries_sync, query)
        except Exception:
            logger.exception("Playlist extraction failed for %s", query)
            return []

        tracks: list[QueuedTrack] = []
        for info in infos:
            track = self._build_track_from_info(
                info,
                requester=requester,
                channel=channel,
                playback_preset=playback_preset,
                original_query=original_query,
            )
            if not track.webpage_url:
                resolved_url = self._resolve_webpage_url(info)
                if resolved_url:
                    track.webpage_url = resolved_url
            if track.webpage_url or track.stream_url or track.title:
                tracks.append(track)

        return tracks

    def _download_track_sync(self, webpage_url: str) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        started_at = time.monotonic()
        profiles = self._iter_stream_resolution_profiles(webpage_url)
        last_error: Optional[Exception] = None
        last_info: Optional[dict[str, Any]] = None
        total_attempts = len(profiles)

        for attempt_index, profile in enumerate(profiles, start=1):
            profile_name = str(profile.get("name") or f"attempt-{attempt_index}")
            logger.info(
                "Starting yt-dlp stream resolution for %s (profile=%s attempt=%s/%s)",
                webpage_url,
                profile_name,
                attempt_index,
                total_attempts,
            )

            try:
                with self._make_ytdl(
                    for_download=True,
                    youtube_clients=profile.get("youtube_clients"),
                    format_selector=profile.get("format"),
                ) as ydl:
                    info = ydl.extract_info(webpage_url, download=False)
            except Exception as exc:
                if not isinstance(
                    exc,
                    (
                        yt_dlp.utils.DownloadError,
                        yt_dlp.utils.ExtractorError,
                        TimeoutError,
                    ),
                ):
                    raise

                last_error = exc
                should_retry = self._should_retry_stream_resolution_error(
                    webpage_url,
                    exc,
                    attempt_index=attempt_index,
                    total_attempts=total_attempts,
                )
                log_func = logger.warning if should_retry else logger.error
                log_func(
                    "yt-dlp stream resolution failed for %s (profile=%s attempt=%s/%s): %s",
                    webpage_url,
                    profile_name,
                    attempt_index,
                    total_attempts,
                    exc,
                )
                if should_retry:
                    time.sleep(
                        YTDL_STREAM_RESOLUTION_RETRY_DELAY_SECONDS + random.uniform(0.0, 0.25)
                    )
                    continue
                break

            if not info:
                logger.warning(
                    "yt-dlp returned no info for %s (profile=%s attempt=%s/%s)",
                    webpage_url,
                    profile_name,
                    attempt_index,
                    total_attempts,
                )
                if attempt_index < total_attempts:
                    time.sleep(
                        YTDL_STREAM_RESOLUTION_RETRY_DELAY_SECONDS + random.uniform(0.0, 0.25)
                    )
                    continue
                break

            if "entries" in info and info["entries"]:
                info = next((entry for entry in info["entries"] if entry), None)

            if not info:
                logger.warning(
                    "yt-dlp returned only empty entries for %s (profile=%s attempt=%s/%s)",
                    webpage_url,
                    profile_name,
                    attempt_index,
                    total_attempts,
                )
                if attempt_index < total_attempts:
                    time.sleep(
                        YTDL_STREAM_RESOLUTION_RETRY_DELAY_SECONDS + random.uniform(0.0, 0.25)
                    )
                    continue
                break

            last_info = info
            stream_url = self._extract_stream_url_from_info(info)
            if stream_url:
                logger.info(
                    "Finished yt-dlp stream resolution for %s in %.2fs (profile=%s stream=%s)",
                    info.get("title") or webpage_url,
                    time.monotonic() - started_at,
                    profile_name,
                    True,
                )
                logger.debug(
                    "Resolved track info title=%s extractor=%s webpage=%s direct=%s stream=%s profile=%s",
                    info.get("title"),
                    info.get("extractor"),
                    self._resolve_webpage_url(info),
                    info.get("url"),
                    stream_url,
                    profile_name,
                )
                return info, stream_url

            logger.warning(
                "No stable playable stream URL was found for %s using profile=%s (attempt=%s/%s)",
                info.get("title") or webpage_url,
                profile_name,
                attempt_index,
                total_attempts,
            )
            if attempt_index < total_attempts:
                time.sleep(
                    YTDL_STREAM_RESOLUTION_RETRY_DELAY_SECONDS + random.uniform(0.0, 0.25)
                )

        logger.warning(
            "All yt-dlp stream resolution attempts were exhausted for %s after %.2fs",
            webpage_url,
            time.monotonic() - started_at,
        )
        if last_info is not None:
            return last_info, None
        if last_error is not None:
            raise last_error
        return None, None

    async def _download_track(self, track: QueuedTrack) -> bool:
        if track.stream_url and _is_probable_stream_url(track.stream_url):
            return True

        if not track.webpage_url:
            track.webpage_url = self._resolve_webpage_url(track.info)

        if not track.webpage_url and track.stream_url and _is_probable_webpage_url(track.stream_url):
            track.webpage_url = track.stream_url
            track.stream_url = None

        if not track.webpage_url:
            logger.warning("Track has no webpage URL and cannot be resolved for streaming: %s", track.title)
            return False

        async with self._download_semaphore:
            if track.stream_url and _is_probable_stream_url(track.stream_url):
                return True

            try:
                logger.info("Resolving playable stream for track: %s", track.title)
                info, stream_url = await asyncio.to_thread(self._download_track_sync, track.webpage_url)
            except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError, TimeoutError) as exc:
                logger.warning("Failed to resolve stream for track %s: %s", track.title, exc)
                return False
            except Exception:
                logger.exception("Failed to resolve stream for track: %s", track.title)
                return False

            if info:
                track.info = info
                track.webpage_url = self._resolve_webpage_url(info) or track.webpage_url
                track.thumbnail = info.get("thumbnail") or track.thumbnail
                track.uploader = info.get("uploader") or info.get("channel") or track.uploader
                duration = info.get("duration")
                if isinstance(duration, (int, float)):
                    track.duration = int(duration)

            if stream_url and _is_probable_stream_url(stream_url):
                track.stream_url = stream_url
                return True

            logger.warning("No stable playable stream URL was found for track: %s", track.title)
            return False

    def _ensure_download_started(self, track: QueuedTrack) -> None:
        if track.stream_url and _is_probable_stream_url(track.stream_url):
            return

        if track.stream_url and _is_probable_webpage_url(track.stream_url) and not track.webpage_url:
            track.webpage_url = track.stream_url
            track.stream_url = None

        if track.stream_task and not track.stream_task.done():
            return

        track.stream_task = asyncio.create_task(self._download_track(track))

    async def _ensure_track_downloaded(self, track: QueuedTrack) -> bool:
        if track.stream_url and _is_probable_stream_url(track.stream_url):
            return True

        if track.stream_url and _is_probable_webpage_url(track.stream_url):
            if not track.webpage_url:
                track.webpage_url = track.stream_url
            track.stream_url = None

        self._ensure_download_started(track)

        if not track.stream_task:
            return False

        try:
            result = await track.stream_task
        except Exception:
            logger.exception("Track stream task failed: %s", track.title)
            return False

        return bool(result and track.stream_url and _is_probable_stream_url(track.stream_url))

    def _preload_upcoming_tracks(self, limit: int = 3) -> None:
        candidates: list[QueuedTrack] = []

        if self.current:
            candidates.append(self.current)

        for track in self.queue:
            candidates.append(track)
            if len(candidates) >= (limit + (1 if self.current else 0)):
                break

        for track in candidates:
            self._ensure_download_started(track)

    async def _ensure_voice_client(self, message: discord.Message) -> Optional[discord.VoiceClient]:
        author = message.author
        author_voice = getattr(author, "voice", None)

        if not author_voice or not author_voice.channel:
            await message.reply("You are not connected to a voice channel.")
            return None

        guild = message.guild
        if guild is None:
            await message.reply("This command can only be used in a server.")
            return None

        logger.info(
            "Ensuring voice connection for guild=%s channel=%s",
            guild.id,
            getattr(author_voice.channel, "name", author_voice.channel),
        )

        guild_vc = guild.voice_client

        if guild_vc and not isinstance(guild_vc, discord.VoiceClient):
            with contextlib.suppress(Exception):
                await asyncio.wait_for(guild_vc.disconnect(force=True), timeout=10)
            guild_vc = None

        if isinstance(guild_vc, discord.VoiceClient):
            self.voice_client = guild_vc

        if self._vc_connected():
            if self.voice_client and self.voice_client.channel != author_voice.channel:
                try:
                    logger.info(
                        "Moving voice client from %s to %s",
                        getattr(self.voice_client.channel, "name", self.voice_client.channel),
                        getattr(author_voice.channel, "name", author_voice.channel),
                    )
                    await asyncio.wait_for(self.voice_client.move_to(author_voice.channel), timeout=15)
                except Exception:
                    logger.exception("Failed to move voice client to target channel")
                    await message.reply("I couldn't move to your voice channel.")
                    return None
            else:
                logger.debug(
                    "Reusing existing voice connection in %s",
                    getattr(author_voice.channel, "name", author_voice.channel),
                )

            return self.voice_client

        last_error: Optional[Exception] = None

        for attempt in range(2):
            try:
                logger.info(
                    "Connecting to voice channel %s (attempt %s)",
                    getattr(author_voice.channel, "name", author_voice.channel),
                    attempt + 1,
                )
                self.voice_client = await asyncio.wait_for(
                    author_voice.channel.connect(self_deaf=True),
                    timeout=20,
                )
                logger.info(
                    "Voice connection established for guild=%s channel=%s",
                    guild.id,
                    getattr(author_voice.channel, "name", author_voice.channel),
                )
                self._touch_audio_heartbeat()
                return self.voice_client
            except Exception as exc:
                last_error = exc
                logger.warning("Voice connect attempt %s failed: %s", attempt + 1, exc, exc_info=True)

                stale = guild.voice_client
                if stale:
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(stale.disconnect(force=True), timeout=10)

                self.voice_client = None
                await asyncio.sleep(1.0)

        await message.reply("I couldn't connect to your voice channel.")
        if last_error:
            logger.error("Final voice connect failure: %s", last_error)
        return None

    def _build_ffmpeg_source(self, track: QueuedTrack, *, seek_seconds: int = 0) -> discord.PCMVolumeTransformer:
        if not track.stream_url:
            raise RuntimeError("Track stream URL is missing.")

        base_before = FFMPEG_OPTIONS.get("before_options_stream", "-nostdin").strip()
        headers = track.info.get("http_headers") or {}
        header_lines = []

        if isinstance(headers, dict):
            for key, value in headers.items():
                if value is None:
                    continue
                key_str = str(key).strip()
                value_str = str(value).strip().replace('"', '\\"')
                if key_str and value_str:
                    header_lines.append(f"{key_str}: {value_str}")

        before_options = base_before

        if header_lines:
            joined_headers = "\r\n".join(header_lines) + "\r\n"
            before_options = f'{before_options} -headers "{joined_headers}"'

        if seek_seconds > 0:
            before_options = f"{before_options} -ss {seek_seconds}"

        options = FFMPEG_OPTIONS.get("options", "-vn -loglevel warning").strip()

        filter_arg = self._get_filter_arg(track)
        if filter_arg:
            options = f"{options} -af {filter_arg}"

        logger.debug(
            "FFmpeg source build track=%s stream=%s webpage=%s before=%s options=%s",
            track.title,
            track.stream_url,
            track.webpage_url,
            before_options,
            options,
        )

        source = discord.FFmpegPCMAudio(
            track.stream_url,
            executable="C:/ffmpeg/bin/ffmpeg.exe",
            before_options=before_options,
            options=options,
        )
        return discord.PCMVolumeTransformer(source, volume=self.volume)

    async def _build_ffmpeg_source_async(
        self,
        track: QueuedTrack,
        *,
        seek_seconds: int = 0,
    ) -> discord.PCMVolumeTransformer:
        logger.info("Creating ffmpeg source for %s (seek=%ss)", track.title, seek_seconds)
        return await asyncio.to_thread(
            self._build_ffmpeg_source,
            track,
            seek_seconds=seek_seconds,
        )

    def _after_playback_callback(self, error: Optional[Exception]) -> None:
        self.bot.loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self._handle_after_playback(error))
        )

    async def _handle_after_playback(self, error: Optional[Exception]) -> None:
        if error:
            logger.error("Playback after-callback reported an error: %s", error)

        finished_source = self._current_source
        self._current_source = None
        self._current_started_monotonic = None

        if finished_source is not None:
            asyncio.create_task(
                self._cleanup_audio_source(
                    finished_source,
                    reason="after playback callback",
                )
            )

        if self._skip_after_callback:
            self._skip_after_callback = False
            logger.debug("Suppressed automatic after-playback transition")
            return

        finished_track = self.current
        if finished_track:
            logger.info("Playback finished for track: %s", finished_track.title)
            self._remember_previous_track(finished_track)

        if finished_track:
            if self.loop_mode == "track":
                self._replay_track = self._clone_track(finished_track)
            elif self.loop_mode == "queue":
                self.queue.append(self._clone_track(finished_track))
                self._replay_track = None
            else:
                self._replay_track = None

        self.current = None

        if not self._vc_connected() and (self._replay_track or self.queue):
            logger.warning("Voice client disconnected before starting the next queued track")

        await self._start_next_track()

    async def _send_track_message(self, track: QueuedTrack, *, color: discord.Color, description: str) -> None:
        if not track.channel:
            return

        self._cancel_widget_transition_task()
        self._widget_transition_nonce += 1
        transition_nonce = self._widget_transition_nonce

        current_message = self._active_control_message
        current_view = self._active_control_view
        same_channel_message = (
            current_message
            if current_message is not None and current_message.channel == track.channel
            else None
        )

        widget_file = await self._build_now_playing_widget_file(track)
        transition_widget_file = None
        if widget_file is not None and same_channel_message is not None:
            transition_widget_file = await self._build_now_playing_transition_widget_file(track)

        embed = None
        if widget_file is None:
            embed = self._build_track_embed(track, color=color, description=description)

        view = MusicControlView(self)

        if same_channel_message is not None:
            try:
                edit_kwargs: dict[str, Any] = {
                    "view": view,
                    "attachments": [],
                    "content": None,
                }
                if widget_file is not None:
                    edit_kwargs["embed"] = None
                    if transition_widget_file is not None:
                        edit_kwargs["attachments"] = [transition_widget_file]
                    else:
                        edit_kwargs["attachments"] = [widget_file]
                else:
                    edit_kwargs["embed"] = embed
                await same_channel_message.edit(**edit_kwargs)
            except (discord.HTTPException, TypeError):
                logger.debug(
                    "Falling back to a new now-playing message for %s",
                    track.title,
                    exc_info=True,
                )
            else:
                if current_view:
                    current_view.stop()
                view.message = same_channel_message
                self._active_control_message = same_channel_message
                self._active_control_view = view
                self._active_control_description = description
                self._active_control_color = color
                self._active_control_uses_widget_image = widget_file is not None
                self._last_control_refresh_monotonic = 0.0
                self._cancel_progress_update_task()
                if widget_file is None:
                    self._ensure_progress_update_task()
                elif transition_widget_file is not None:
                    self._widget_transition_task = asyncio.create_task(
                        self._complete_widget_transition(
                            message=same_channel_message,
                            view=view,
                            widget_file=widget_file,
                            transition_nonce=transition_nonce,
                        )
                    )
                return

        await self._disable_active_controls()

        try:
            if widget_file is not None:
                message = await track.channel.send(view=view, file=widget_file)
            else:
                message = await track.channel.send(embed=embed, view=view)
        except discord.HTTPException:
            return

        view.message = message
        self._active_control_message = message
        self._active_control_view = view
        self._active_control_description = description
        self._active_control_color = color
        self._active_control_uses_widget_image = widget_file is not None
        self._last_control_refresh_monotonic = 0.0
        self._cancel_progress_update_task()
        if widget_file is None:
            self._ensure_progress_update_task()

    async def _play_track_safe(
        self,
        track: QueuedTrack,
        *,
        start_seconds: int = 0,
        send_message: bool = True,
        description: str = "Now playing",
        color: discord.Color = discord.Color.green(),
    ) -> bool:
        if not self._vc_connected():
            logger.warning("Cannot play track because no connected voice client exists")
            return False

        logger.info("Preparing playback startup for track: %s", track.title)
        ok = await self._ensure_track_downloaded(track)
        if not ok or not track.stream_url:
            logger.warning("Stream resolve failed or stream URL missing for track: %s", track.title)
            return False

        last_error: Optional[Exception] = None

        for attempt in range(2):
            source: Optional[discord.PCMVolumeTransformer] = None
            try:
                async with self._voice_transition_lock:
                    voice_client = self.voice_client
                    if not voice_client or not voice_client.is_connected():
                        logger.warning("Voice client became unavailable before playback startup for %s", track.title)
                        return False

                    await self._stop_voice_playback_locked(
                        reason=f"starting playback for {track.title}",
                        suppress_after_callback=True,
                    )

                    voice_client = self.voice_client
                    if not voice_client or not voice_client.is_connected():
                        logger.warning("Voice client disconnected during playback startup for %s", track.title)
                        return False

                    source_started_at = time.monotonic()
                    source = await self._build_ffmpeg_source_async(track, seek_seconds=start_seconds)
                    logger.debug(
                        "FFmpeg source created for %s in %.2fs",
                        track.title,
                        time.monotonic() - source_started_at,
                    )

                    if self.voice_client is not voice_client or not voice_client.is_connected():
                        logger.warning("Voice client changed or disconnected during FFmpeg startup for %s", track.title)
                        await self._cleanup_audio_source(source, reason="voice client changed before playback")
                        return False

                    self._current_source = source
                    logger.info("Starting playback for %s (attempt %s)", track.title, attempt + 1)
                    voice_client.play(source, after=self._after_playback_callback)

                self._reset_playback_clock(start_seconds=start_seconds)
                self._update_playback_clock_on_resume()
                self._touch_audio_heartbeat()
                self._apply_volume_to_source()
                self._preload_upcoming_tracks(limit=3)

                if send_message:
                    # 2. THE WIDGET REFRESHES WHEN A NEW TRACK STARTS HERE.
                    await self._send_track_message(track, color=color, description=description)

                return True
            except Exception as exc:
                last_error = exc
                logger.exception("Failed to start track playback (attempt %s): %s", attempt + 1, exc)

                async with self._voice_transition_lock:
                    if source is not None and self._current_source is source:
                        self._current_source = None

                await self._cleanup_audio_source(source, reason="playback startup failure")
                track.stream_url = None
                await asyncio.sleep(0.5)
                await self._ensure_track_downloaded(track)

        if last_error:
            logger.error("Giving up on track playback: %s", last_error)
        return False

    async def _restart_current_playback(self, *, start_seconds: Optional[int] = None, keep_paused: bool = False) -> bool:
        if not self.current or not self._vc_connected():
            return False

        target = self._get_current_progress_seconds() if start_seconds is None else start_seconds
        target = max(0, target)

        was_paused = keep_paused or self._vc_paused()

        self._sync_track_filter_metadata(self.current)
        logger.info("Restarting current playback for %s from %ss", self.current.title, target)
        ok = await self._play_track_safe(self.current, start_seconds=target, send_message=False)

        if ok and was_paused and self.voice_client:
            self.voice_client.pause()
            self._update_playback_clock_on_pause()

        await self._refresh_active_controls(force=True)
        return ok

    async def _start_next_track(self) -> None:
        async with self._start_next_lock:
            logger.debug(
                "Attempting to start next track (connected=%s active=%s queue=%s replay=%s)",
                self._vc_connected(),
                self._vc_active(),
                len(self.queue),
                bool(self._replay_track),
            )

            if not self._vc_connected():
                logger.warning("Cannot start next track because the voice client is disconnected")
                self.current = None
                return

            if self._vc_active():
                return

            if self._replay_track:
                track = self._replay_track
                self._replay_track = None
                self.current = track
                # Reapply the current guild/session filter state to each track.
                self._sync_track_filter_metadata(track)
                logger.info("Starting replay track: %s", track.title)

                played = await self._play_track_safe(
                    track,
                    description="Repeating track",
                    color=discord.Color.purple(),
                )
                if played:
                    return

                self.current = None

            while self.queue:
                next_track = self.queue.popleft()
                self.current = next_track
                # Reapply the current guild/session filter state to each track.
                self._sync_track_filter_metadata(next_track)
                logger.info("Starting queued track: %s", next_track.title)

                played = await self._play_track_safe(
                    next_track,
                    description="Now playing",
                    color=discord.Color.green(),
                )
                if played:
                    return

                logger.warning("Skipping unplayable track: %s", next_track.title)
                self.current = None

            self.current = None
            # A continuous listening session has ended only when nothing is left
            # to replay or queue. At that point we clear session-level filters.
            self._reset_filter_session_state(reason="queue exhausted")
            await self._disable_active_controls()

    async def _seek_to_seconds_internal(self, seconds: int) -> tuple[bool, str]:
        if not self.current or not self._vc_active():
            return False, "Nothing is playing right now."

        if isinstance(self.current.duration, int):
            seconds = max(0, min(seconds, self.current.duration))
        else:
            seconds = max(0, seconds)

        ok = await self._restart_current_playback(start_seconds=seconds, keep_paused=self._vc_paused())
        if not ok:
            return False, "Failed to seek the current track."

        self._touch_audio_heartbeat()
        return True, f"Seeked to {format_duration(seconds)}"

    async def _seek_relative_internal(self, delta_seconds: int) -> tuple[bool, str]:
        if not self.current:
            return False, "Nothing is playing right now."

        target = self._get_current_progress_seconds() + delta_seconds
        return await self._seek_to_seconds_internal(target)

    async def _set_current_playback_preset_internal(
        self,
        preset: str,
        *,
        playback_rate: Optional[float] = None,
    ) -> tuple[bool, str]:
        preset = preset.lower()
        if preset not in {"normal", "nightcore", "slow"}:
            return False, "Unknown playback mode."

        async with self._play_lock:
            if preset == "normal":
                return await self._clear_filters_internal(
                    effect_names=AUDIO_FILTER_CONFLICT_GROUPS["tempo_pitch"],
                    success_message="Normal mode enabled.",
                    empty_message="Normal mode is already active.",
                )

            if preset == "nightcore":
                rate = self._sanitize_playback_rate(playback_rate, minimum=1.01, maximum=2.0) or 1.45
                active = self._filter_state.effects.get("nightcore")
                active_rate = None
                if active is not None:
                    active_rate = self._sanitize_playback_rate(active.params.get("rate"), minimum=1.01, maximum=2.0)
                if active is not None and active_rate == rate:
                    return await self._clear_filters_internal(
                        effect_names={"nightcore"},
                        success_message="Normal mode enabled.",
                        empty_message="Normal mode is already active.",
                    )
                return await self._apply_filter_effect_internal(
                    "nightcore",
                    params=[rate],
                    success_message=f"Nightcore mode enabled at {rate:.2f}x.",
                    queue_message=f"Nightcore mode primed at {rate:.2f}x for the next track.",
                )

            active = self._filter_state.effects.get("slow")
            if active is not None:
                return await self._clear_filters_internal(
                    effect_names={"slow"},
                    success_message="Normal mode enabled.",
                    empty_message="Normal mode is already active.",
                )
            return await self._apply_filter_effect_internal(
                "slow",
                params=[],
                success_message="Slow mode enabled.",
                queue_message="Slow mode primed for the next track.",
            )

    def _get_current_progress_seconds(self) -> int:
        if not self.current:
            return 0

        progress = self._current_position_base_seconds

        if self._current_started_monotonic is not None:
            progress += int(max(0.0, time.monotonic() - self._current_started_monotonic))

        if isinstance(self.current.duration, int):
            progress = max(0, min(progress, self.current.duration))
        else:
            progress = max(0, progress)

        return progress

    async def seek_relative_interaction(self, interaction: discord.Interaction, delta_seconds: int) -> tuple[bool, str]:
        return await self._seek_relative_internal(delta_seconds)

    async def seek_to_seconds_interaction(self, interaction: discord.Interaction, seconds: int) -> tuple[bool, str]:
        return await self._seek_to_seconds_internal(seconds)

    async def set_playback_preset_interaction(self, interaction: discord.Interaction, preset: str) -> tuple[bool, str]:
        return await self._set_current_playback_preset_internal(preset)

    async def set_playback_preset_func(
        self,
        message: discord.Message,
        preset: str,
        *,
        playback_rate: Optional[float] = None,
    ) -> str:
        ok, response = await self._set_current_playback_preset_internal(
            preset,
            playback_rate=playback_rate,
        )
        await message.reply(response)
        return response if ok else "Playback mode change failed"

    def _build_help_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="Cadis Etrama Di Raizel",
            description=(
                "Clean music controls, Turkish shortcuts, filters, history, and playlist playback in one place. "
                "Use natural chat commands and the bot will route them through the current music system."
            ),
            color=HELP_EMBED_COLOR,
        )
        embed.set_author(name="Music Guide")
        embed.add_field(
            name="Playback",
            value=(
                "`play Breaking Benjamin` `pause` `resume` `skip` `stop`\n"
                "`queue` `shuffle` `clearqueue` `nowplaying` `np`\n"
                "`seek 1:20` `forward 10` `back 10` `loop`"
            ),
            inline=False,
        )
        embed.add_field(
            name="History",
            value=(
                "`history` `history @user` `history me`\n"
                "`mostplayed @user` `mostplayed me` `favorites @user`\n"
                "`history @user page 2` `mostplayed me 2` `ge\u00e7mi\u015f @user sayfa 2`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Playlist Support",
            value=(
                "`play <playlist url>`\n"
                "`playlist <url>`\n"
                "`\u00e7al <playlist url>` `liste oynat <url>`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Filters",
            value=(
                "`nightcore` `bassboost` `slow` `reverb` `echo` `karaoke`\n"
                "`speed 1.15` `pitch 0.9` `tremolo 5 0.7` `vibrato 6 0.5`\n"
                "`lowpass 300` `highpass 200` `equalizer 100 3`\n"
                "`mono` `stereo widen` `compressor` `gate` `8d`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Disable / Reset",
            value=(
                "`nightcore off` `reverb off` `bassboost off` `8d off`\n"
                "`show filters` `current filters`\n"
                "`filter off` `filters off` `reset filters` `clear filters`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Turkish Support",
            value=(
                "`\u00e7al not strong enough` `\u015fimdi \u00e7alan` `\u015fu an ne \u00e7al\u0131yor`\n"
                "`kuyru\u011fu temizle` `s\u0131ray\u0131 temizle`\n"
                "`ge\u00e7mi\u015fim` `\u015fark\u0131lar\u0131m` `ileri sar 10` `geri sar 10`"
            ),
            inline=False,
        )
        embed.set_footer(text="History pages show 5 songs per page. Filters stay active during the current session.")
        return embed

    def _build_filter_status_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="Cadis Etrama Di Raizel",
            description="Live filter state for the current session.",
            color=HELP_EMBED_COLOR,
        )
        embed.set_author(name="Filter Status")
        entries = self._active_filter_entries()
        if entries:
            embed.add_field(
                name="Active Filters",
                value="\n".join(
                    f"`{index}.` {self._describe_filter_entry(entry)}"
                    for index, entry in enumerate(entries, start=1)
                ),
                inline=False,
            )
        else:
            embed.add_field(name="Active Filters", value="`None`", inline=False)

        if self.current:
            embed.add_field(name="Current Track", value=self.current.title, inline=False)
        else:
            embed.add_field(name="Current Track", value="Nothing is playing right now.", inline=False)

        embed.set_footer(text="Use 'reset filters' to clear every active effect.")
        return embed

    def _validate_filter_request(
        self,
        effect_name: str,
        params: Optional[list[Any]] = None,
    ) -> tuple[bool, Optional[AudioFilterEntry], str]:
        values = list(params or [])
        label = AUDIO_FILTER_LABELS.get(effect_name, effect_name.replace("_", " ").title())

        def parse_number(
            index: int,
            *,
            minimum: float,
            maximum: float,
            field_name: str,
            default: Optional[float] = None,
        ) -> tuple[Optional[float], Optional[str]]:
            if index >= len(values):
                if default is None:
                    return None, f"{label} needs {field_name}."
                return default, None

            raw_value = str(values[index]).replace(",", ".").strip()
            try:
                number = float(raw_value)
            except ValueError:
                return None, f"{label} {field_name} must be numeric."

            if not minimum <= number <= maximum:
                return None, f"{label} {field_name} must be between {minimum:g} and {maximum:g}."

            return number, None

        if effect_name == "nightcore":
            rate, error = parse_number(0, minimum=1.01, maximum=2.0, field_name="speed", default=1.45)
            return (error is None, self._make_filter_entry("nightcore", rate=rate) if error is None else None, error or "")

        if effect_name == "bassboost":
            gain, error = parse_number(0, minimum=1.0, maximum=20.0, field_name="gain", default=8.0)
            return (error is None, self._make_filter_entry("bassboost", gain=gain) if error is None else None, error or "")

        if effect_name == "slow":
            return True, self._make_filter_entry("slow"), ""

        if effect_name == "speed":
            rate, error = parse_number(0, minimum=0.5, maximum=2.0, field_name="rate")
            return (error is None, self._make_filter_entry("speed", rate=rate) if error is None else None, error or "")

        if effect_name == "pitch":
            rate, error = parse_number(0, minimum=0.5, maximum=2.0, field_name="rate")
            return (error is None, self._make_filter_entry("pitch", rate=rate) if error is None else None, error or "")

        if effect_name in {"reverb", "echo", "karaoke", "flanger", "phaser", "chorus", "distortion", "mono", "compressor", "gate", "earrape", "vaporwave", "lofi", "deep", "telephone", "megaphone", "robot", "underwater", "8d"}:
            return True, self._make_filter_entry(effect_name), ""

        if effect_name == "tremolo":
            frequency, error = parse_number(0, minimum=0.1, maximum=20.0, field_name="frequency", default=5.0)
            if error:
                return False, None, error
            depth, error = parse_number(1, minimum=0.1, maximum=1.0, field_name="depth", default=0.7)
            if error:
                return False, None, error
            return True, self._make_filter_entry("tremolo", frequency=frequency, depth=depth), ""

        if effect_name == "vibrato":
            frequency, error = parse_number(0, minimum=0.1, maximum=20.0, field_name="frequency", default=6.0)
            if error:
                return False, None, error
            depth, error = parse_number(1, minimum=0.01, maximum=1.0, field_name="depth", default=0.5)
            if error:
                return False, None, error
            return True, self._make_filter_entry("vibrato", frequency=frequency, depth=depth), ""

        if effect_name == "lowpass":
            frequency, error = parse_number(0, minimum=20.0, maximum=20000.0, field_name="frequency")
            return (error is None, self._make_filter_entry("lowpass", frequency=frequency) if error is None else None, error or "")

        if effect_name == "highpass":
            frequency, error = parse_number(0, minimum=20.0, maximum=20000.0, field_name="frequency")
            return (error is None, self._make_filter_entry("highpass", frequency=frequency) if error is None else None, error or "")

        if effect_name == "equalizer":
            frequency, error = parse_number(0, minimum=20.0, maximum=20000.0, field_name="frequency")
            if error:
                return False, None, error
            gain, error = parse_number(1, minimum=-20.0, maximum=20.0, field_name="gain")
            if error:
                return False, None, error
            return True, self._make_filter_entry("equalizer", frequency=frequency, gain=gain), ""

        if effect_name == "stereo_widen":
            amount, error = parse_number(0, minimum=1.0, maximum=10.0, field_name="amount", default=2.5)
            return (error is None, self._make_filter_entry("stereo_widen", amount=amount) if error is None else None, error or "")

        if effect_name == "volume_filter":
            percent, error = parse_number(0, minimum=10.0, maximum=300.0, field_name="percent")
            return (error is None, self._make_filter_entry("volume_filter", percent=percent) if error is None else None, error or "")

        return False, None, "Unknown filter."

    async def _clear_filters_internal(
        self,
        *,
        effect_names: Optional[set[str]] = None,
        success_message: Optional[str] = None,
        empty_message: str = "No filters are active.",
    ) -> tuple[bool, str]:
        active_names = set(self._filter_state.effects)
        target_names = active_names if effect_names is None else active_names.intersection(effect_names)
        if not target_names:
            return False, empty_message

        snapshot = copy.deepcopy(self._filter_state.effects)
        removed_entries = [entry for entry in self._active_filter_entries() if entry.name in target_names]
        for name in target_names:
            self._filter_state.effects.pop(name, None)
        self._sync_track_filter_metadata()

        if self.current and self._vc_connected() and self._vc_active():
            ok = await self._restart_current_playback(
                start_seconds=self._get_current_progress_seconds(),
                keep_paused=self._vc_paused(),
            )
            if not ok:
                self._filter_state.effects = snapshot
                self._sync_track_filter_metadata()
                return False, "Failed to rebuild playback with the updated filter state."
            self._touch_audio_heartbeat()

        if success_message:
            return True, success_message

        removed_text = ", ".join(self._describe_filter_entry(entry) for entry in removed_entries)
        if self.current and self._vc_connected():
            return True, f"Cleared: {removed_text}."
        return True, f"Cleared: {removed_text}. The next track will stay clean."

    async def _apply_filter_effect_internal(
        self,
        effect_name: str,
        *,
        params: Optional[list[Any]] = None,
        success_message: Optional[str] = None,
        queue_message: Optional[str] = None,
    ) -> tuple[bool, str]:
        ok, entry, error = self._validate_filter_request(effect_name, params)
        if not ok or entry is None:
            return False, error

        existing = self._filter_state.effects.get(effect_name)
        if existing is not None and existing.params == entry.params:
            active_text = self._describe_filter_entry(existing)
            return True, f"{active_text} is already active."

        snapshot = copy.deepcopy(self._filter_state.effects)
        removed_labels: list[str] = []
        group_name = self._filter_group_name(effect_name)
        if group_name is not None:
            for conflicting_name in AUDIO_FILTER_CONFLICT_GROUPS[group_name]:
                if conflicting_name == effect_name:
                    continue
                conflicting_entry = self._filter_state.effects.pop(conflicting_name, None)
                if conflicting_entry is not None:
                    removed_labels.append(self._describe_filter_entry(conflicting_entry))

        self._filter_state.effects[effect_name] = entry
        self._sync_track_filter_metadata()

        if self.current and self._vc_connected() and self._vc_active():
            ok = await self._restart_current_playback(
                start_seconds=self._get_current_progress_seconds(),
                keep_paused=self._vc_paused(),
            )
            if not ok:
                self._filter_state.effects = snapshot
                self._sync_track_filter_metadata()
                return False, "Failed to rebuild playback with the selected filter."
            self._touch_audio_heartbeat()
            response = success_message or f"{self._describe_filter_entry(entry)} enabled."
        else:
            response = queue_message or f"{self._describe_filter_entry(entry)} primed for the next track."

        if removed_labels:
            response += f" Replaced: {', '.join(removed_labels)}."
        return True, response

    async def apply_filter_func(
        self,
        message: discord.Message,
        effect_name: str,
        *,
        params: Optional[list[Any]] = None,
    ) -> str:
        async with self._play_lock:
            ok, response = await self._apply_filter_effect_internal(effect_name, params=params)
        await message.reply(response)
        return response if ok else "Filter update failed"

    async def remove_filter_func(self, message: discord.Message, effect_name: str) -> str:
        label = AUDIO_FILTER_LABELS.get(effect_name, effect_name.replace("_", " ").title())
        async with self._play_lock:
            ok, response = await self._clear_filters_internal(
                effect_names={effect_name},
                success_message=f"{label} disabled.",
                empty_message=f"{label} is not active.",
            )
        await message.reply(response)
        return response if ok else "Filter remove failed"

    async def clear_filters_func(self, message: discord.Message) -> str:
        async with self._play_lock:
            ok, response = await self._clear_filters_internal(success_message="All filters cleared.")
        await message.reply(response)
        return response if ok else "Filter clear failed"

    async def show_filters_func(self, message: discord.Message) -> str:
        await message.reply(embed=self._build_filter_status_embed())
        return self._describe_current_filters_text()

    async def help_func(self, message: discord.Message) -> str:
        await message.reply(embed=self._build_help_embed())
        return "Help sent"

    async def pause_interaction(self, interaction: discord.Interaction) -> tuple[bool, str]:
        if not self._vc_playing():
            return False, "Nothing is playing right now."

        try:
            self.voice_client.pause()
            self._update_playback_clock_on_pause()
        except Exception:
            logger.exception("Failed to pause playback")
            return False, "Failed to pause playback."

        return True, "Playback paused."

    async def resume_interaction(self, interaction: discord.Interaction) -> tuple[bool, str]:
        if not self._vc_paused():
            return False, "Nothing is paused right now."

        try:
            self.voice_client.resume()
            self._update_playback_clock_on_resume()
        except Exception:
            logger.exception("Failed to resume playback")
            return False, "Failed to resume playback."

        self._touch_audio_heartbeat()
        return True, "Playback resumed."

    async def skip_interaction(self, interaction: discord.Interaction) -> tuple[bool, str]:
        if not self._vc_active():
            return False, "Nothing is playing right now."

        skipped = self.current.title if self.current else "current track"

        try:
            self.voice_client.stop()
        except Exception:
            logger.exception("Failed to skip track")
            return False, "Failed to skip the current track."

        return True, f"Skipped: {skipped}"

    def _build_track_embed(
        self,
        track: QueuedTrack,
        *,
        color: discord.Color,
        description: str = "Track added to queue",
    ) -> discord.Embed:
        embed = discord.Embed(title=track.title, description=description, color=color)

        if track.webpage_url:
            embed.url = track.webpage_url

        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)

        if track.requester:
            with contextlib.suppress(Exception):
                embed.set_author(
                    name=track.requester.display_name,
                    icon_url=track.requester.display_avatar.url,
                )

        if track.uploader:
            embed.add_field(name="Uploader", value=track.uploader, inline=True)

        if track.duration:
            embed.add_field(name="Duration", value=format_duration(track.duration), inline=True)

        embed.add_field(name="Progress", value=self._get_progress_text(track), inline=True)

        preset_labels = {
            "normal": "Normal",
            "nightcore": "Nightcore",
            "slow": "Slow",
        }
        mode_label = preset_labels.get(track.playback_preset, "Normal")
        if track.playback_preset == "nightcore" and track.playback_rate:
            mode_label = f"{mode_label} {track.playback_rate:.2f}x"
        embed.add_field(name="Mode", value=mode_label, inline=True)

        filter_summary = self._describe_current_filters_text()
        if filter_summary != "None":
            embed.add_field(name="Filters", value=filter_summary, inline=False)

        if track.stream_url:
            embed.add_field(name="Source", value="Streaming", inline=True)
        else:
            embed.add_field(name="Source", value="Preparing stream", inline=True)

        embed.set_footer(text="Use the buttons below to control playback.")
        return embed

    def _build_progress_bar(self, progress: int, duration: Optional[int], *, width: int = 14) -> str:
        if not duration or duration <= 0:
            return "[ live stream ]"

        clamped = max(0, min(progress, duration))
        filled = int(round((clamped / duration) * width))
        filled = max(0, min(filled, width))
        return f"[{'#' * filled}{'-' * (width - filled)}]"

    def _build_now_playing_embed(self, track: QueuedTrack) -> discord.Embed:
        progress = self._get_current_progress_seconds()
        duration = track.duration if isinstance(track.duration, int) else None
        progress_label = format_duration(progress)
        duration_label = format_duration(duration) if duration else "LIVE"

        embed = discord.Embed(
            title="Now Playing",
            description=f"**{track.title}**",
            color=discord.Color.green(),
        )

        if track.webpage_url:
            embed.url = track.webpage_url

        cover_url = self._get_track_cover_url(track)
        if cover_url:
            embed.set_thumbnail(url=cover_url)

        embed.add_field(
            name="Progress",
            value=f"{self._build_progress_bar(progress, duration)}\n`{progress_label} / {duration_label}`",
            inline=False,
        )
        embed.add_field(name="Requester", value=self._get_track_requester_name(track), inline=True)
        embed.add_field(name="Artist", value=self._get_track_artist_name(track), inline=True)

        filter_summary = self._describe_current_filters_text()
        if filter_summary != "None":
            embed.add_field(name="Filters", value=filter_summary, inline=False)

        return embed

    async def play_func(self, message: discord.Message, song_name: str) -> str:
        async with self._play_lock:
            voice_client = await self._ensure_voice_client(message)
            if not voice_client:
                return "User is not in a voice channel"

            normalized_query = normalize_audio_query(song_name)
            logger.info("Received play request for query=%s", normalized_query)
            if normalized_query != song_name:
                logger.debug("Normalized audio query from %s to %s", song_name, normalized_query)

            is_soundcloud = is_soundcloud_query(normalized_query)
            is_direct_media = _is_direct_media_url(normalized_query)
            is_playlist_query = self._is_playlist_query(normalized_query)
            if is_playlist_query:
                msg = await message.reply("Loading playlist...")
            elif is_direct_media:
                msg = await message.reply("Loading direct URL...")
            else:
                msg = await message.reply("Loading SoundCloud track..." if is_soundcloud else "Loading track...")

            if is_playlist_query:
                tracks = await self._extract_playlist_tracks(
                    normalized_query,
                    requester=message.author,
                    channel=message.channel,
                    playback_preset="normal",
                    original_query=normalized_query,
                )
                if not tracks and is_direct_media:
                    logger.warning("Playlist extraction returned no usable entries; falling back to direct URL handling for %s", normalized_query)
                    track = await self._extract_track_from_direct_url(
                        normalized_query,
                        requester=message.author,
                        channel=message.channel,
                        playback_preset="normal",
                        original_query=normalized_query,
                    )
                    tracks = [track] if track else []
                if not tracks:
                    await msg.edit(content="Couldn't load that playlist. Try another playlist URL.")
                    return "Playlist extraction failed"
            elif is_direct_media:
                track = await self._extract_track_from_direct_url(
                    normalized_query,
                    requester=message.author,
                    channel=message.channel,
                    playback_preset="normal",
                    original_query=normalized_query,
                )
                if not track:
                    await msg.edit(
                        content="Couldn't extract a playable stream from that URL. Try another link or a text search query."
                    )
                    return "Direct URL extraction failed"
                tracks = [track]
            else:
                try:
                    infos = await self._search_tracks(normalized_query)
                except Exception as exc:
                    logger.exception("Search failed for %s", normalized_query)
                    await msg.edit(content=f"Search error: {exc}")
                    return "Search error"

                if not infos:
                    await msg.edit(content="No track found for that query.")
                    return "Track not found"

                if not _looks_like_url(normalized_query) and not normalized_query.lower().startswith("scsearch1:"):
                    infos = infos[:1]

                tracks = [
                    self._build_track_from_info(
                        info,
                        requester=message.author,
                        channel=message.channel,
                        playback_preset="normal",
                        original_query=normalized_query,
                    )
                    for info in infos
                ]

            if not tracks:
                await msg.edit(content="No playable tracks were found for that request.")
                return "Track not found"

            for track in tracks:
                self.queue.append(track)

            await self._record_tracks_in_history(guild=message.guild, requester=message.author, tracks=tracks)
            self._preload_upcoming_tracks(limit=4)

            will_play_immediately = not self._player_busy()

            if will_play_immediately:
                delete_task = asyncio.create_task(msg.delete())
                await self._start_next_track()
                with contextlib.suppress(discord.HTTPException):
                    await delete_task

                if self.current and self.current.title == tracks[0].title:
                    if len(tracks) > 1:
                        await message.reply(f"Added {len(tracks)} tracks from the playlist. Now playing: {tracks[0].title}")
                        return f"Playlist started: {tracks[0].title}"
                    return f"Now playing: {tracks[0].title}"

                await message.reply("Track was added, but playback could not start.")
                return "Track queued but playback failed"

            if len(tracks) > 1:
                try:
                    await msg.edit(content=f"Added {len(tracks)} tracks from the playlist.", embed=None)
                except discord.HTTPException:
                    pass
                return f"Added {len(tracks)} playlist tracks"

            embed = self._build_track_embed(tracks[0], color=discord.Color.blue())
            try:
                await msg.edit(content=None, embed=embed)
            except discord.HTTPException:
                pass

            return f"Added to queue: {tracks[0].title}"

    async def play_previous_func(self, message: discord.Message) -> str:
        voice_client = await self._ensure_voice_client(message)
        if not voice_client:
            return "User is not in a voice channel"

        data = self.previous_track_data
        if not data:
            await message.reply("I don't have a previous song to replay yet.")
            return "No previous track"

        try:
            track = QueuedTrack(
                title=data.get("title", "Unknown"),
                requester=message.author,
                webpage_url=data.get("webpage_url"),
                thumbnail=data.get("thumbnail"),
                uploader=data.get("uploader"),
                duration=data.get("duration"),
                channel=message.channel,
                playback_preset=data.get("playback_preset", "normal"),
                info=copy.deepcopy(data.get("info") or {}),
                local_path=Path(data["local_path"]) if data.get("local_path") else None,
                original_query=data.get("original_query"),
                stream_url=data.get("stream_url"),
                playback_rate=data.get("playback_rate"),
            )

            self.queue.appendleft(track)
            self._ensure_download_started(track)

            if self._vc_active():
                self.voice_client.stop()
            else:
                await self._start_next_track()

            await message.reply(f"Playing the previous song again: {track.title}")
            return f"Playing the previous song again: {track.title}"

        except Exception:
            logger.exception("Failed to replay previous track")
            await message.reply("Couldn't replay the previous song.")
            return "Previous track replay failed"

    async def play_attachment_func(self, message: discord.Message, attachment: discord.Attachment) -> str:
        await message.reply("Attachment playback is not available in this yt-dlp version yet.")
        return "Attachment playback unavailable"

    async def skip_func(self, message: discord.Message) -> str:
        if not self._vc_active():
            await message.reply("Nothing is playing right now.")
            return "Queue is not playing"

        skipped = self.current.title if self.current else "current track"

        try:
            self.voice_client.stop()
        except Exception:
            logger.exception("Failed to skip track")
            await message.reply("Failed to skip the current track.")
            return "Skip failed"

        await message.reply(f"Skipping: {skipped}")
        return f"Skipped track: {skipped}"

    async def skip_by_name_func(self, message: discord.Message, song_name: str) -> str:
        lowercase_query = song_name.lower()

        if self.current and lowercase_query in self.current.title.lower():
            skipped_title = self.current.title
            if self.voice_client:
                try:
                    self.voice_client.stop()
                except Exception:
                    logger.exception("Failed to skip current track by name")
                    await message.reply("Failed to skip the current track.")
                    return "Skip failed"

            await message.reply(f"Skipped current track: {skipped_title}")
            return f"Skipped current track: {skipped_title}"

        for track in list(self.queue):
            if lowercase_query in track.title.lower():
                self.queue.remove(track)
                await message.reply(f"Removed from queue: {track.title}")
                return f"Removed from queue: {track.title}"

        await message.reply("That track was not found in the queue.")
        return "Track not found"

    async def stop_func(self, message: discord.Message) -> str:
        self.queue.clear()
        self._replay_track = None
        self.current = None
        self._reset_playback_clock(start_seconds=0)

        await self._stop_voice_playback(
            reason="stop command",
            suppress_after_callback=True,
        )

        await self._disable_active_controls()
        self._reset_filter_session_state(reason="stop command")
        await message.reply("Queue cleared and playback stopped.")
        return "Queue cleared"

    async def summon_func(self, message: discord.Message) -> str:
        voice_client = await self._ensure_voice_client(message)
        if not voice_client:
            return "User is not in a voice channel"

        await message.reply("Joined your voice channel.")
        return "Joined voice channel"

    async def disconnect_func(self, message: discord.Message) -> str:
        self.queue.clear()
        self._replay_track = None
        self.current = None
        self._reset_playback_clock(start_seconds=0)

        await self._stop_voice_playback(
            reason="disconnect command",
            suppress_after_callback=True,
        )

        if self.voice_client:
            async with self._voice_transition_lock:
                voice_client = self.voice_client
                if voice_client:
                    logger.info(
                        "Disconnecting voice client from %s",
                        getattr(voice_client.channel, "name", voice_client.channel),
                    )
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(voice_client.disconnect(force=True), timeout=10)
                    if self.voice_client is voice_client:
                        self.voice_client = None

        await self._disable_active_controls()
        self._reset_filter_session_state(reason="disconnect command")

        await message.reply("Disconnected from the channel and cleared the queue.")
        return "Bot disconnected"

    async def seek_func(self, message: discord.Message, time_str: str) -> str:
        if not self.current or not self._vc_active():
            await message.reply("Nothing is playing right now.")
            return "No track to seek"

        try:
            seconds = parse_time(time_str)
        except ValueError:
            await message.reply("Invalid time format. Example: 1:23 or 73")
            return "Invalid time"

        _, response = await self._seek_to_seconds_internal(seconds)
        await message.reply(response)
        return response

    async def pause_func(self, message: discord.Message) -> str:
        if self._vc_playing():
            try:
                self.voice_client.pause()
                self._update_playback_clock_on_pause()
            except Exception:
                logger.exception("Failed to pause playback")
                await message.reply("Failed to pause playback.")
                return "Pause failed"

            await message.reply("Playback paused.")
            return "Playback paused"

        await message.reply("Nothing is playing right now.")
        return "Nothing is playing"

    async def resume_func(self, message: discord.Message) -> str:
        if self._vc_paused():
            try:
                self.voice_client.resume()
                self._update_playback_clock_on_resume()
            except Exception:
                logger.exception("Failed to resume playback")
                await message.reply("Failed to resume playback.")
                return "Resume failed"

            self._touch_audio_heartbeat()
            await message.reply("Playback resumed.")
            return "Playback resumed"

        await message.reply("Nothing is paused right now.")
        return "Nothing to resume"

    async def now_playing_func(self, message: discord.Message) -> str:
        if not self.current or not self._vc_active():
            await message.reply("Nothing is playing right now.")
            return "Nothing is playing right now."

        await message.reply(embed=self._build_now_playing_embed(self.current))
        return f"Now playing: {self.current.title}"

    async def get_queue_func(self, message: discord.Message) -> str:
        if not self.queue:
            return "Queue is empty."

        lines = []
        for i, track in enumerate(self.queue, start=1):
            dur = format_duration(track.duration) if track.duration else "?:??"
            lines.append(f"{i}. {track.title} ({dur})")
            if i >= 20:
                lines.append("... and more tracks")
                break

        return "\n".join(lines)

    async def shuffle_queue_func(self, message: discord.Message) -> str:
        if not self.queue:
            await message.reply("Queue is empty, nothing to shuffle.")
            return "Queue is empty, nothing to shuffle."

        queue_list = list(self.queue)
        random.shuffle(queue_list)
        self.queue.clear()
        self.queue.extend(queue_list)
        self._preload_upcoming_tracks(limit=4)

        await message.reply("Queue shuffled.")
        return "Queue shuffled"

    async def clear_queue_func(self, message: discord.Message) -> str:
        if not self.queue:
            await message.reply("Queue is already empty.")
            return "Queue is already empty."

        self.queue.clear()
        await message.reply("Queue cleared (the current track continues playing).")
        return "Queue cleared"

    async def remove_from_queue_func(self, message: discord.Message, index: int) -> str:
        if not self.queue:
            return "Queue is empty."

        if index < 1 or index > len(self.queue):
            return f"Invalid index. There are {len(self.queue)} tracks in the queue."

        track = self.queue[index - 1]
        self.queue.remove(track)

        await message.reply(f"Removed from queue: {track.title}")
        return f"Removed track: {track.title}"

    async def set_loop_mode_func(self, message: discord.Message, mode: str) -> str:
        mode = mode.lower()
        if mode not in ("off", "track", "queue"):
            return "Unknown mode. Use 'off', 'track' or 'queue'."

        self.loop_mode = mode
        mode_labels = {
            "off": "Off",
            "track": "Current track",
            "queue": "Entire queue",
        }

        await message.reply(f"Loop mode set to: {mode_labels[mode]}.")
        return f"Loop mode: {mode}"

    async def set_volume_func(self, message: discord.Message, level: float) -> str:
        if level < 0.0 or level > 2.0:
            await message.reply("Volume must be between 0.0 and 2.0.")
            return "Invalid volume value"

        self.volume = level
        self._apply_volume_to_source()

        await message.reply(f"Volume set to {self._volume_percent()}%.")
        return f"Volume {self._volume_percent()}%"

    async def lyrics_by_query_func(self, message: discord.Message, query: str) -> str:
        query = (query or "").strip()
        if not query:
            await message.reply("Tell me which song you want lyrics for.")
            return "Lyrics query missing"

        status_msg = await message.reply(f"Fetching lyrics for: {query}")

        try:
            lyrics = await asyncio.to_thread(fetch_lyrics, query, None)
        except Exception:
            logger.exception("Lyrics query fetch failed")
            await status_msg.edit(content="Couldn't fetch lyrics.")
            return "Lyrics fetch failed"

        if not lyrics:
            await status_msg.edit(content=f"Couldn't find lyrics for: {query}")
            return "Lyrics not found"

        chunks = []
        max_len = 1900
        text = lyrics.strip()

        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break

            split_at = text.rfind("\n", 0, max_len)
            if split_at == -1:
                split_at = max_len

            chunk = text[:split_at].strip()
            if chunk:
                chunks.append(chunk)

            text = text[split_at:].strip()

        await status_msg.edit(content=f"**Lyrics for:** {query}")

        for chunk in chunks[:4]:
            await message.channel.send(chunk)

        if len(chunks) > 4:
            await message.channel.send("...lyrics truncated.")

        return f"Lyrics sent for: {query}"

    async def volume_func(self, message: discord.Message, value: str) -> str:
        try:
            percent = float(str(value).strip().replace("%", ""))
        except (TypeError, ValueError):
            await message.reply("Give me a valid volume like 30.")
            return "Invalid volume value"

        percent = max(0.0, min(percent, 200.0))
        return await self.set_volume_func(message, percent / 100.0)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.id != self.bot.user.id:
            return

        guild = member.guild
        if self.voice_client and guild != self.voice_client.guild:
            return

        before_name = getattr(before.channel, "name", None)
        after_name = getattr(after.channel, "name", None)
        logger.info(
            "Bot voice state changed in guild=%s: %s -> %s",
            guild.id,
            before_name,
            after_name,
        )

        guild_voice_client = guild.voice_client
        if isinstance(guild_voice_client, discord.VoiceClient):
            self.voice_client = guild_voice_client
        elif after.channel is None:
            logger.warning("Bot voice client is no longer attached to guild=%s", guild.id)

    @tasks.loop(minutes=5)
    async def check_for_inactivity(self) -> None:
        now = discord.utils.utcnow()

        if self.voice_client and self._vc_connected():
            if not self._vc_active():
                last_time = self._last_audio_time or now
                if (now - last_time).total_seconds() > 1800:
                    with contextlib.suppress(Exception):
                        await self.voice_client.disconnect(force=True)
                    self.voice_client = None

        if self.voice_client and not self._vc_connected():
            self.queue.clear()
            self.current = None
            self._replay_track = None
            self._current_source = None
            self._reset_playback_clock(start_seconds=0)
            self._reset_filter_session_state(reason="voice disconnected or inactive")
            await self._disable_active_controls()
            self.voice_client = None

    @check_for_inactivity.before_loop
    async def before_check_for_inactivity(self) -> None:
        await self.bot.wait_until_ready()






