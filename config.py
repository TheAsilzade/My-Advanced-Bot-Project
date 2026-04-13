from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import discord

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
DEFAULT_PROMPT_PATH = REPO_ROOT / "utils" / "default_prompt.txt"

_FALLBACK_PROMPT = (
    "You are Raizel, a cute baby seal who lives inside a Discord music bot. "
    "You talk like a playful, sweet, slightly childish seal. "
    "You are friendly, adorable, and a little silly, but still helpful.\n\n"
    "You can chat normally with users about anything and also control music playback "
    "in voice channels (play songs, skip, pause, resume, change volume, show queue).\n\n"
    "Your personality:\n"
    "- playful baby seal energy\n"
    "- cute and friendly\n"
    "- sometimes a little goofy\n"
    "- short and fun responses\n\n"
    "Always respond in English.\n"
    "Never respond in Russian.\n"
    "Your name is Raizel.\n\n"
)


def _load_env_file(path: Path = DEFAULT_ENV_FILE) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()

        if not key:
            continue

        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file()


def _get_env(
    name: str,
    default: Optional[str] = None,
    *,
    required: bool = False,
) -> Optional[str]:
    value = os.getenv(name, default)

    if required and (value is None or value == ""):
        raise RuntimeError(
            f"Required environment variable '{name}' is missing."
        )

    return value


def _load_default_prompt() -> str:
    try:
        text = DEFAULT_PROMPT_PATH.read_text(encoding="utf-8")
        if text.strip():
            return text
    except Exception:
        pass

    return _FALLBACK_PROMPT


def _parse_channel_ids(*raw_values: Optional[str]) -> tuple[int, ...]:
    ids: list[int] = []
    seen: set[int] = set()

    for raw_value in raw_values:
        if not raw_value:
            continue

        for piece in str(raw_value).split(","):
            item = piece.strip()
            if not item:
                continue

            try:
                channel_id = int(item)
            except ValueError:
                continue

            if channel_id in seen:
                continue

            seen.add(channel_id)
            ids.append(channel_id)

    return tuple(ids)


@dataclass(frozen=True)
class DiscordSettings:
    token: str
    chatbot_channel_id: Optional[int]
    chatbot_channel_ids: tuple[int, ...]
    intents: discord.Intents


@dataclass(frozen=True)
class OpenRouterSettings:
    api_key: str
    default_model: str = "meta-llama/llama-3.1-8b-instruct"


@dataclass(frozen=True)
class MiscSettings:
    music_directory: Path
    context_file: Path
    status_message: str
    prompt_file: Optional[Path]
    prompt_text: str


@dataclass(frozen=True)
class AudioSettings:
    ytdl_options: dict
    ffmpeg_options: dict


@dataclass(frozen=True)
class AppSettings:
    discord: DiscordSettings
    openrouter: OpenRouterSettings
    misc: MiscSettings
    audio: AudioSettings


def _build_intents() -> discord.Intents:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.guilds = True
    intents.messages = True
    intents.voice_states = True
    return intents


def _build_ytdl_options(music_dir: Path) -> dict:
    cookies_path = REPO_ROOT / "cogs" / "cookies.txt"

    opts = {
        "cookiefile": str(cookies_path) if cookies_path.exists() else None,

        # stream için daha güvenli format seçimi
        "format": "bestaudio[protocol=https]/bestaudio/best",

        "skip_download": True,

        "noplaylist": True,
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "quiet": True,
        "no_warnings": True,
        "default_search": "auto",

        "socket_timeout": 20,
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 3,

        "buffersize": 16 * 1024 * 1024,
        "http_chunk_size": 10 * 1024 * 1024,
        "concurrent_fragment_downloads": 4,
        "throttled_rate": 100 * 1024,

        "cachedir": False,

        # daha stabil extractor ayarı
        "extractor_args": {
    "youtube": {
        "player_client": ["android_vr", "web", "web_safari"],
    }
},
    }

    return {k: v for k, v in opts.items() if v is not None}


def _build_ffmpeg_options() -> dict:
    return {
        "before_options_stream": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin",
        "before_options_file": "-nostdin",
        "options": "-vn -loglevel warning",
    }


def load_settings() -> AppSettings:
    discord_token = _get_env("DISCORD_BOT_TOKEN", required=True)

    chatbot_channel_id_raw = _get_env("CHATBOT_CHANNEL_ID")
    chatbot_channel_ids_raw = _get_env("CHATBOT_CHANNEL_IDS")
    chatbot_channel_ids = _parse_channel_ids(chatbot_channel_ids_raw, chatbot_channel_id_raw)
    chatbot_channel_id = chatbot_channel_ids[0] if chatbot_channel_ids else None

    openrouter_key = _get_env("OPENROUTER_API_KEY", "") or ""

    music_directory = Path(_get_env("MUSIC_DIRECTORY", "music_files"))
    context_file = Path(_get_env("CONTEXT_FILE", "chat_context.json"))

    status_message = _get_env("DISCORD_STATUS_MESSAGE", "Jit")

    prompt_text = _load_default_prompt()

    misc_settings = MiscSettings(
        music_directory=music_directory,
        context_file=context_file,
        status_message=status_message,
        prompt_file=None,
        prompt_text=prompt_text,
    )

    audio_settings = AudioSettings(
        ytdl_options=_build_ytdl_options(music_directory),
        ffmpeg_options=_build_ffmpeg_options(),
    )

    return AppSettings(
        discord=DiscordSettings(
            token=discord_token,
            chatbot_channel_id=chatbot_channel_id,
            chatbot_channel_ids=chatbot_channel_ids,
            intents=_build_intents(),
        ),
        openrouter=OpenRouterSettings(
            api_key=openrouter_key
        ),
        misc=misc_settings,
        audio=audio_settings,
    )


_settings = load_settings()

DISCORD_BOT_TOKEN = _settings.discord.token
CHATBOT_CHANNEL_ID = _settings.discord.chatbot_channel_id
CHATBOT_CHANNEL_IDS = _settings.discord.chatbot_channel_ids
INTENTS = _settings.discord.intents
OPENROUTER_API_KEY = _settings.openrouter.api_key

MUSIC_DIRECTORY = _settings.misc.music_directory
CONTEXT_FILE = str(_settings.misc.context_file)
DISCORD_STATUS_MESSAGE = _settings.misc.status_message
BOT_PROMPT_TEXT = _settings.misc.prompt_text

YTDL_OPTIONS = _settings.audio.ytdl_options
FFMPEG_OPTIONS = _settings.audio.ffmpeg_options


def get_settings() -> AppSettings:
    return _settings
