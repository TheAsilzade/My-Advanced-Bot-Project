# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import ast
import html
import contextlib
import datetime as dt
from dataclasses import dataclass, field
import io
import json
import logging
import math
import operator
import random
import re
import sqlite3
import string
import time
from urllib.parse import quote
from pathlib import Path
from typing import Any, Optional

import aiohttp
import discord
import requests
from discord.ext import commands
from PIL import Image, ImageChops, ImageDraw
from utils.quickdraw_cache import (
    DEFAULT_CATEGORY_ATTEMPT_LIMIT,
    DEFAULT_SAMPLE_ATTEMPT_LIMIT,
    QuickDrawCacheManager,
    normalize_quickdraw_strokes,
    quickdraw_entry_is_drawable,
    sanitize_quickdraw_entry,
)

try:
    import argostranslate.translate as _argos_translate
except ImportError:
    _argos_translate = None

logger = logging.getLogger(__name__)

PROFILE_XP_FILENAME = "profile_xp.json"
ECONOMY_DB_FILENAME = "economy.sqlite3"
EMBED_COLOR = 0x111827
XP_GAIN_COOLDOWN_SECONDS = 45.0
XP_GAIN_MIN = 8
XP_GAIN_MAX = 16
PROFILE_LEADERBOARD_PAGE_SIZE = 10
ECONOMY_LEADERBOARD_PAGE_SIZE = 10
QUIZ_TIMEOUT_SECONDS = 180.0
WORK_COOLDOWN_SECONDS = 180.0
DAILY_COOLDOWN_SECONDS = 24 * 60 * 60
DEFAULT_PROFESSION_KEY = "scavenger"
PASSIVE_INCOME_TICK_SECONDS = 5 * 60
PROFESSION_LEVEL_CAP = 10
CRASH_TICK_SECONDS = 0.55
CRASH_VIEW_TIMEOUT_SECONDS = 60.0
SHOPVIEW_PAGE_SIZE = 4
NOTES_LIST_PAGE_SIZE = 10
DUNGEON_LIFE_COST = 150
DUNGEON_LIFE_MAX = 3
DRAWGAME_TIMEOUT_SECONDS = 70.0
DRAWGAME_PHASE_DELAYS: tuple[float, ...] = (0.0, 6.0, 4.0, 3.0)
HANGMAN_TIMEOUT_SECONDS = 150.0
WORDCHAIN_TURN_TIMEOUT_SECONDS = 25.0
QUICKDRAW_CATEGORY_ATTEMPT_LIMIT = 8
QUICKDRAW_SAMPLE_ATTEMPT_LIMIT = 10
QUICKDRAW_STARTUP_TIMEOUT_SECONDS = 18.0
DRAWSHARE_CANVAS_SIZE = 512
TRIVIA_BATCH_SIZE = 5
TRIVIA_QUESTION_TIMEOUT_SECONDS = 22.0
TRIVIA_SESSION_IDLE_TIMEOUT_SECONDS = 90.0
TRIVIA_NEXT_QUESTION_DELAY_SECONDS = 2.5
TRIVIA_TOKEN_REQUEST_URL = "https://opentdb.com/api_token.php?command=request"
TRIVIA_TOKEN_RESET_URL = "https://opentdb.com/api_token.php?command=reset&token={token}"
TRIVIA_BATCH_URL = "https://opentdb.com/api.php?amount={amount}&type=multiple&token={token}"
DUNGEON_FIGHTERSEAL_COST = 1000
DUNGEON_FIGHTERSEAL_BONUS = 0.10
DUNGEON_COMPANIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "fighterseal",
        "name": "FighterSeal",
        "cost": DUNGEON_FIGHTERSEAL_COST,
        "bonus": DUNGEON_FIGHTERSEAL_BONUS,
        "button_label": "FighterSeal (1000)",
        "activation_text": "FighterSeal joins your run. Your odds sharpen.",
    },
    {
        "key": "kelpy",
        "name": "Kelpy",
        "cost": 1000,
        "bonus": 0.10,
        "button_label": "Kelpy (1000)",
        "activation_text": "Kelpy slips into the shadows beside you.",
    },
    {
        "key": "thibeault",
        "name": "Thibeault (FisherKing)",
        "cost": 1000,
        "bonus": 0.10,
        "button_label": "Thibeault (FisherKing) (1000)",
        "activation_text": "Thibeault (FisherKing) steadies the path ahead.",
    },
    {
        "key": "kamil",
        "name": "Kamil",
        "cost": 2500,
        "bonus": 0.20,
        "button_label": "Kamil (2500)",
        "activation_text": "Kamil joins the run, raising your odds dramatically.",
    },
    {
        "key": "batman",
        "name": "Batman",
        "cost": 1000,
        "bonus": 0.10,
        "button_label": "Batman (1000)",
        "activation_text": "Batman enters the dungeon with you, silent and prepared.",
    },
    {
        "key": "hessa_king",
        "name": "Hessa King",
        "cost": 400,
        "bonus": 0.05,
        "button_label": "Hessa King (400)",
        "activation_text": "Hessa King joins the run with a calm edge to your odds.",
    },
)
DUNGEON_COMPANION_LOOKUP: dict[str, dict[str, Any]] = {
    str(companion["key"]): companion for companion in DUNGEON_COMPANIONS
}

ECONOMY_ACTION_COOLDOWNS = {
    "beg": 45.0,
    "fish": 90.0,
    "hunt": 120.0,
    "search": 90.0,
    "mine": 120.0,
    "deliver": 120.0,
    "scavenge": 75.0,
    "freelance": 150.0,
    "craft": 135.0,
    "repair": 120.0,
    "patrol": 150.0,
}

QUICK_EARN_ACTIONS: tuple[dict[str, str], ...] = (
    {"key": "work", "label": "Work", "emoji": "💼"},
    {"key": "fish", "label": "Fish", "emoji": "🎣"},
    {"key": "hunt", "label": "Hunt", "emoji": "🏹"},
    {"key": "search", "label": "Search", "emoji": "🔎"},
    {"key": "mine", "label": "Mine", "emoji": "⛏️"},
    {"key": "deliver", "label": "Deliver", "emoji": "📦"},
    {"key": "scavenge", "label": "Scavenge", "emoji": "🗑️"},
    {"key": "freelance", "label": "Freelance", "emoji": "💻"},
    {"key": "craft", "label": "Craft", "emoji": "🛠️"},
    {"key": "repair", "label": "Repair", "emoji": "🔧"},
    {"key": "patrol", "label": "Patrol", "emoji": "🛡️"},
)

FALLBACK_QUICKDRAW_ENTRIES: tuple[dict[str, Any], ...] = (
    {
        "answer": "apple",
        "clue": "A fruit that grows on trees.",
        "aliases": ("apples",),
        "drawing": [[[256, 190, 150, 130, 138, 170, 220, 290, 350, 380, 370, 340, 300, 250, 200, 160], [80, 90, 125, 180, 260, 340, 390, 415, 395, 335, 250, 175, 125, 98, 94, 110]], [[252, 265, 280], [82, 42, 18]], [[248, 215, 190, 172], [58, 38, 24, 20]]],
    },
    {
        "answer": "house",
        "clue": "A place people live in.",
        "aliases": ("home",),
        "drawing": [[[120, 120, 392, 392, 120], [220, 400, 400, 220, 220]], [[120, 256, 392], [220, 90, 220]], [[220, 220, 292, 292, 220], [400, 300, 300, 400, 400]], [[150, 205, 205, 150, 150], [260, 260, 320, 320, 260]]],
    },
    {
        "answer": "bicycle",
        "clue": "You ride it using pedals.",
        "aliases": ("bike", "bikes"),
        "drawing": [[[110, 80, 95, 135, 150, 120, 95], [350, 390, 425, 430, 390, 350, 350]], [[310, 280, 295, 335, 350, 320, 295], [350, 390, 425, 430, 390, 350, 350]], [[135, 220, 270, 200, 150], [430, 300, 300, 350, 430]], [[220, 245, 270], [300, 250, 300]], [[200, 220], [350, 300]], [[270, 310], [300, 250]]],
    },
    {
        "answer": "fish",
        "clue": "It swims in water.",
        "aliases": ("fishes",),
        "drawing": [[[100, 180, 260, 335, 380, 340, 260, 180, 100], [260, 210, 205, 235, 260, 290, 315, 310, 260]], [[340, 430, 380], [235, 200, 260]], [[340, 430, 380], [290, 320, 260]], [[155, 165], [255, 255]]],
    },
    {
        "answer": "tree",
        "clue": "It has leaves and a trunk.",
        "aliases": ("trees",),
        "drawing": [[[228, 228, 284, 284, 228], [410, 280, 280, 410, 410]], [[256, 180, 140, 165, 125, 185, 245, 320, 375, 345, 385, 330, 256], [110, 180, 245, 315, 365, 400, 380, 398, 365, 310, 240, 180, 110]]],
    },
    {
        "answer": "airplane",
        "clue": "It flies people through the sky.",
        "aliases": ("plane", "jet"),
        "drawing": [[[90, 390], [255, 255]], [[170, 255, 310], [255, 155, 255]], [[240, 290, 330], [255, 200, 225]], [[120, 145, 175], [255, 210, 235]], [[345, 400, 425], [255, 220, 245]]],
    },
    {
        "answer": "crown",
        "clue": "A royal piece worn on the head.",
        "aliases": ("royal crown",),
        "drawing": [[[100, 100, 160, 220, 280, 340, 410, 410, 100], [350, 230, 315, 180, 315, 180, 315, 350, 350]], [[160, 160], [315, 350]], [[220, 220], [180, 350]], [[280, 280], [315, 350]], [[340, 340], [180, 350]]],
    },
    {
        "answer": "cup",
        "clue": "You drink from it.",
        "aliases": ("mug",),
        "drawing": [[[145, 165, 345, 365], [120, 390, 390, 120]], [[365, 410, 410, 365], [175, 175, 300, 300]], [[165, 345], [390, 390]]],
    },
)

QUICKDRAW_CLUES: dict[str, str] = {
    "angel": "Often shown with wings or a halo.",
    "ant": "A tiny insect that works in groups.",
    "backpack": "You carry things in it on your back.",
    "banana": "A curved yellow fruit.",
    "baseball bat": "Used to hit a ball in sports.",
    "bicycle": "You ride it using pedals.",
    "bird": "An animal with wings and feathers.",
    "book": "You read pages from it.",
    "candle": "It gives off light with a flame.",
    "car": "A common vehicle on roads.",
    "cat": "A popular pet with whiskers.",
    "chair": "You sit on it.",
    "clock": "It tells time.",
    "cloud": "It floats in the sky.",
    "coffee cup": "It holds a hot drink.",
    "dog": "A loyal pet that barks.",
    "fish": "It swims in water.",
    "flower": "It grows from the ground and blooms.",
    "house": "A place people live in.",
    "moon": "A bright object seen at night.",
    "star": "A shape with points, or something in the sky.",
    "tree": "It has leaves and a trunk.",
}

HANGMAN_WORDS: tuple[str, ...] = (
    "apple", "anchor", "ancient", "artist", "bamboo", "barista", "battery", "bicycle", "bridge", "candle",
    "captain", "castle", "coffee", "compass", "crystal", "dungeon", "ember", "falcon", "fisherman", "forest",
    "galaxy", "garden", "glacier", "goblet", "harbor", "helmet", "lantern", "library", "marble", "meadow",
    "meteor", "mirror", "mountain", "notebook", "ocean", "orchard", "painter", "pillow", "pirate", "planet",
    "pocket", "programmer", "radar", "ranger", "rocket", "sapphire", "scholar", "seal", "shadow", "signal",
    "silver", "singer", "skeleton", "sorcerer", "spiral", "statue", "storm", "sunset", "temple", "thunder",
    "torch", "tower", "traveler", "treasure", "violet", "voyage", "whisper", "window", "wizard", "wrench",
)

WORDCHAIN_WORDS: tuple[str, ...] = (
    "anchor", "apple", "arrow", "artist", "avenue", "beacon", "bicycle", "bridge", "button", "candle",
    "captain", "castle", "circle", "compass", "crystal", "dragon", "ember", "engine", "falcon", "feather",
    "forest", "garden", "glider", "harbor", "helmet", "island", "jungle", "lantern", "library", "meadow",
    "meteor", "mirror", "mountain", "notebook", "oasis", "orange", "painter", "planet", "pocket", "rocket",
    "sapphire", "signal", "silver", "spiral", "statue", "storm", "sunset", "temple", "thunder", "torch",
    "tower", "traveler", "treasure", "violet", "voyage", "window", "wizard", "wrench",
)
WORDCHAIN_WORD_LOOKUP: frozenset[str] = frozenset(word.lower() for word in WORDCHAIN_WORDS)

RESERVED_TEXT_GAME_WORDS: frozenset[str] = frozenset(
    {
        "drawgame", "hint", "skip", "reveal", "enddrawgame",
        "hangman", "wordchain", "chainword",
        "help", "shop", "market", "shopview", "inventory", "sell", "sellall",
        "blackjack", "bj", "coinflip", "cf", "duel", "guess",
        "work", "fish", "hunt", "search", "mine", "deliver", "scavenge", "freelance", "craft", "repair", "patrol",
    }
)

PROFESSIONS: tuple[dict[str, Any], ...] = (
    {"key": "seal diver", "name": "Seal Diver", "min": 80, "max": 135, "tasks": ("recovered a crate from the cold water", "mapped an icy trench", "salvaged lost gear near the docks")},
    {"key": "fisherman", "name": "Fisherman", "min": 60, "max": 110, "tasks": ("brought in a strong net haul", "fixed torn lines at sunrise", "sold a fresh catch at the pier")},
    {"key": "courier", "name": "Courier", "min": 70, "max": 115, "tasks": ("delivered a sealed parcel on time", "rushed a fragile package across town", "handled a busy route with no delays")},
    {"key": "miner", "name": "Miner", "min": 75, "max": 125, "tasks": ("pulled ore out of a deep shaft", "sorted a cart full of stone", "found a richer mineral vein")},
    {"key": "mechanic", "name": "Mechanic", "min": 80, "max": 130, "tasks": ("repaired a stubborn engine", "tuned a loud scooter", "replaced worn cables and gears")},
    {"key": "chef", "name": "Chef", "min": 70, "max": 120, "tasks": ("served a packed dinner rush", "perfected a signature seafood plate", "kept the kitchen moving smoothly")},
    {"key": "hunter", "name": "Hunter", "min": 75, "max": 125, "tasks": ("tracked prey across a windy ridge", "returned with a clean haul", "set clever traps before sunset")},
    {"key": "barista", "name": "Barista", "min": 60, "max": 100, "tasks": ("handled a long coffee line", "crafted a perfect late-night order", "kept the espresso bar moving")},
    {"key": "streamer", "name": "Streamer", "min": 55, "max": 150, "tasks": ("wrapped a lively stream session", "hit a surprise donation spike", "kept the chat entertained for hours")},
    {"key": "blacksmith", "name": "Blacksmith", "min": 85, "max": 140, "tasks": ("forged a clean steel blade", "hammered out a custom fitting", "finished a tough commission")},
    {"key": "farmer", "name": "Farmer", "min": 60, "max": 105, "tasks": ("worked the fields from dawn", "sorted a fresh harvest", "loaded produce for the market")},
    {"key": "taxi driver", "name": "Taxi Driver", "min": 65, "max": 110, "tasks": ("handled a rush of late fares", "navigated traffic with clean timing", "picked up a generous regular")},
    {"key": "bodyguard", "name": "Bodyguard", "min": 90, "max": 145, "tasks": ("protected a client through a tense event", "held a secure perimeter all shift", "finished a high-risk escort job")},
    {"key": "merchant", "name": "Merchant", "min": 70, "max": 140, "tasks": ("closed a profitable trade", "moved stock before sunset", "found buyers for premium goods")},
    {"key": "programmer", "name": "Programmer", "min": 90, "max": 155, "tasks": ("fixed a nasty production bug", "shipped a feature before the deadline", "cleaned up a tangled code path")},
    {"key": "detective", "name": "Detective", "min": 85, "max": 135, "tasks": ("connected clues on a cold case", "tailed a suspect through the market", "wrapped an investigation cleanly")},
    {"key": "medic", "name": "Medic", "min": 80, "max": 130, "tasks": ("helped stabilize an exhausted worker", "handled a hectic shift", "kept the clinic running calmly")},
    {"key": "librarian", "name": "Librarian", "min": 55, "max": 95, "tasks": ("restored order to a packed archive", "cataloged a rare collection", "assisted readers all afternoon")},
    {"key": "teacher", "name": "Teacher", "min": 65, "max": 110, "tasks": ("guided a tough lesson well", "prepared materials for the next class", "helped students through a busy day")},
    {"key": "artist", "name": "Artist", "min": 50, "max": 140, "tasks": ("finished a commission piece", "sold a striking canvas", "earned praise for a fresh concept")},
    {"key": "tailor", "name": "Tailor", "min": 60, "max": 105, "tasks": ("fitted a sharp coat perfectly", "restored a worn suit", "finished a stack of custom orders")},
    {"key": "jewel crafter", "name": "Jewel Crafter", "min": 85, "max": 150, "tasks": ("set a delicate gem by hand", "completed a premium necklace order", "polished a rare piece for sale")},
    {"key": "ship worker", "name": "Ship Worker", "min": 75, "max": 120, "tasks": ("secured cargo below deck", "helped load a rough outbound run", "kept a busy vessel on schedule")},
    {"key": "dock worker", "name": "Dock Worker", "min": 70, "max": 115, "tasks": ("moved freight across the pier", "stacked a cold morning delivery", "finished a heavy loading shift")},
    {"key": "builder", "name": "Builder", "min": 80, "max": 135, "tasks": ("framed a sturdy new wall", "finished a precise repair", "kept a construction crew moving")},
    {"key": "electrician", "name": "Electrician", "min": 85, "max": 140, "tasks": ("rewired a flickering panel", "restored power to a dark block", "handled a tricky diagnostic call")},
    {"key": "fisherman captain", "name": "Fisherman Captain", "min": 90, "max": 150, "tasks": ("brought a full crew home with a great haul", "read the water better than anyone", "sold the day's biggest catch")},
    {"key": "night guard", "name": "Night Guard", "min": 65, "max": 110, "tasks": ("kept watch through a quiet shift", "caught trouble before it escalated", "secured the grounds until dawn")},
    {"key": "street vendor", "name": "Street Vendor", "min": 50, "max": 100, "tasks": ("sold out a warm tray before noon", "worked a busy corner with charm", "pulled in a steady crowd")},
    {"key": "scavenger", "name": "Scavenger", "min": 45, "max": 95, "tasks": ("found sellable scraps in a forgotten lot", "turned discarded parts into profit", "picked through crates for valuables")},
)

PROFESSION_LOOKUP: dict[str, dict[str, Any]] = {}
for _profession_entry in PROFESSIONS:
    for _alias in {
        _profession_entry["key"],
        _profession_entry["name"],
        _profession_entry["key"].replace(" ", "_"),
        _profession_entry["name"].replace(" ", "_"),
    }:
        PROFESSION_LOOKUP[re.sub(r"\s+", " ", _alias.lower().replace("_", " ").replace("-", " ")).strip()] = _profession_entry

SHOP_ITEMS: tuple[dict[str, Any], ...] = (
    {"key": "small apartment", "name": "Small Apartment", "price": 1400, "category": "Lifestyle", "description": "A modest place to call your own."},
    {"key": "cozy room", "name": "Cozy Room", "price": 650, "category": "Lifestyle", "description": "Small, warm, and easy to keep tidy."},
    {"key": "luxury coat", "name": "Luxury Coat", "price": 950, "category": "Lifestyle", "description": "Clean tailoring with a premium finish."},
    {"key": "compact loft", "name": "Compact Loft", "price": 2400, "category": "Lifestyle", "description": "A sharper space with room for late-night plans."},
    {"key": "oceanview suite", "name": "Oceanview Suite", "price": 6200, "category": "Luxury", "description": "Tall windows, dark wood, and a view worth slowing down for."},
    {"key": "tailored suit", "name": "Tailored Suit", "price": 2100, "category": "Luxury", "description": "Custom fitted and impossible to ignore."},
    {"key": "velvet lounge set", "name": "Velvet Lounge Set", "price": 3800, "category": "Luxury", "description": "A rich seating set with quiet confidence."},
    {"key": "silver signet ring", "name": "Silver Signet Ring", "price": 1750, "category": "Luxury", "description": "A polished ring with a clean engraved face."},
    {"key": "midnight watch", "name": "Midnight Watch", "price": 1600, "category": "Luxury", "description": "A premium watch with a dark reflective dial."},
    {"key": "coastal villa key", "name": "Coastal Villa Key", "price": 9200, "category": "Luxury", "description": "Access to a place people talk about in low voices."},
    {"key": "gaming chair", "name": "Gaming Chair", "price": 720, "category": "Decoration", "description": "A comfortable throne for long sessions."},
    {"key": "coffee machine", "name": "Coffee Machine", "price": 540, "category": "Utility", "description": "A reliable source of strong mornings."},
    {"key": "fish meal", "name": "Fish Meal", "price": 70, "category": "Fun", "description": "A warm meal that disappears quickly.", "consumable": True, "use_text": "You finish the fish meal and feel ready for another round."},
    {"key": "headphones", "name": "Headphones", "price": 420, "category": "Utility", "description": "Clear sound and a little isolation."},
    {"key": "watch", "name": "Watch", "price": 260, "category": "Lifestyle", "description": "A neat watch with a polished face."},
    {"key": "phone", "name": "Phone", "price": 500, "category": "Utility", "description": "A sleek phone with enough storage for playlists."},
    {"key": "seal pillow", "name": "Seal Pillow", "price": 180, "category": "Fun", "description": "Ridiculously soft and impossible to ignore."},
    {"key": "dark lamp", "name": "Dark Lamp", "price": 230, "category": "Decoration", "description": "A low-key lamp with a moody glow."},
    {"key": "bookshelf", "name": "Bookshelf", "price": 380, "category": "Decoration", "description": "A sturdy shelf for books and little trophies."},
    {"key": "scooter", "name": "Scooter", "price": 1100, "category": "Utility", "description": "Fast enough for city errands."},
    {"key": "bike", "name": "Bike", "price": 780, "category": "Utility", "description": "Simple, practical, and quick to trust."},
    {"key": "necklace", "name": "Necklace", "price": 610, "category": "Lifestyle", "description": "A clean finish piece with subtle shine."},
    {"key": "record shelf", "name": "Record Shelf", "price": 440, "category": "Decoration", "description": "A shelf built for your favorite albums."},
    {"key": "thermos", "name": "Thermos", "price": 140, "category": "Utility", "description": "Keeps drinks warm on long shifts."},
    {"key": "desk plant", "name": "Desk Plant", "price": 125, "category": "Decoration", "description": "A small calm touch for your room."},
    {"key": "vinyl player", "name": "Vinyl Player", "price": 860, "category": "Decoration", "description": "Warm sound and a clean centerpiece for the room."},
    {"key": "moonlit rug", "name": "Moonlit Rug", "price": 520, "category": "Decoration", "description": "Soft texture with a deep dark pattern."},
    {"key": "framed skyline art", "name": "Framed Skyline Art", "price": 690, "category": "Decoration", "description": "A bold city print for the wall."},
    {"key": "candle set", "name": "Candle Set", "price": 150, "category": "Decoration", "description": "A calm set for quieter evenings."},
    {"key": "glass display case", "name": "Glass Display Case", "price": 1320, "category": "Decoration", "description": "A premium way to show off your favorite finds."},
    {"key": "wall mirror", "name": "Wall Mirror", "price": 340, "category": "Decoration", "description": "A sharp mirror with a dark metal frame."},
    {"key": "tool kit", "name": "Tool Kit", "price": 310, "category": "Utility", "description": "A reliable set for quick repairs."},
    {"key": "portable heater", "name": "Portable Heater", "price": 460, "category": "Utility", "description": "Keeps a cold room from staying cold for long."},
    {"key": "travel bag", "name": "Travel Bag", "price": 360, "category": "Utility", "description": "A durable bag built for busy routes."},
    {"key": "camera", "name": "Camera", "price": 980, "category": "Technology", "description": "Sharp enough for portraits, streets, and night lights."},
    {"key": "tablet", "name": "Tablet", "price": 1350, "category": "Technology", "description": "Portable, bright, and good for work or downtime."},
    {"key": "smart speaker", "name": "Smart Speaker", "price": 720, "category": "Technology", "description": "Compact sound with a clean finish."},
    {"key": "mechanical keyboard", "name": "Mechanical Keyboard", "price": 890, "category": "Technology", "description": "Responsive keys with a satisfying feel."},
    {"key": "ultrawide monitor", "name": "Ultrawide Monitor", "price": 2450, "category": "Technology", "description": "A wide premium display for serious setups."},
    {"key": "signal booster", "name": "Signal Booster", "price": 640, "category": "Technology", "description": "A practical upgrade for weak corners and dead zones."},
    {"key": "night market noodles", "name": "Night Market Noodles", "price": 85, "category": "Food", "description": "Hot noodles with a little heat.", "consumable": True, "use_text": "You finish the noodles and feel comfortably recharged."},
    {"key": "seafood platter", "name": "Seafood Platter", "price": 210, "category": "Food", "description": "A generous plate worth slowing down for.", "consumable": True, "use_text": "You enjoy the seafood platter and call it a good choice."},
    {"key": "dessert box", "name": "Dessert Box", "price": 140, "category": "Food", "description": "A neat box filled with rich small desserts.", "consumable": True, "use_text": "You finish the dessert box and the mood improves instantly."},
    {"key": "premium coffee beans", "name": "Premium Coffee Beans", "price": 190, "category": "Food", "description": "Dark roast beans with a sharp finish."},
    {"key": "spiced tea set", "name": "Spiced Tea Set", "price": 170, "category": "Food", "description": "A calming tea set with layered flavors."},
    {"key": "midnight chocolate", "name": "Midnight Chocolate", "price": 95, "category": "Food", "description": "Rich, dark, and gone too quickly.", "consumable": True, "use_text": "You eat the chocolate and decide it was worth every coin."},
    {"key": "mini projector", "name": "Mini Projector", "price": 980, "category": "Fun", "description": "Movie nights look better with this around."},
    {"key": "arcade token pack", "name": "Arcade Token Pack", "price": 150, "category": "Fun", "description": "A pouch of tokens for an easy night out."},
    {"key": "card deck", "name": "Card Deck", "price": 60, "category": "Fun", "description": "Simple, portable, and never truly out of use."},
    {"key": "board game set", "name": "Board Game Set", "price": 240, "category": "Fun", "description": "A shelf-ready set for long evenings with friends."},
    {"key": "seal plush", "name": "Seal Plush", "price": 210, "category": "Fun", "description": "Soft, round, and absolutely defenseless against hugs."},
    {"key": "retro console", "name": "Retro Console", "price": 1180, "category": "Fun", "description": "A nostalgic system with more charm than power."},
    {"key": "book subscription", "name": "Book Subscription", "price": 540, "category": "Lifestyle", "description": "Fresh reading delivered without needing to ask twice."},
    {"key": "espresso cart", "name": "Espresso Cart", "price": 1680, "category": "Utility", "description": "A compact setup for serious coffee habits."},
    {"key": "designer headphones", "name": "Designer Headphones", "price": 1780, "category": "Luxury", "description": "Premium sound with a clean studio finish."},
    {"key": "sword", "name": "Sword", "price": 720, "category": "Medieval Fantasy", "description": "A balanced blade fit for a first real duel."},
    {"key": "greatsword", "name": "Greatsword", "price": 1320, "category": "Medieval Fantasy", "description": "Heavy steel with presence and reach."},
    {"key": "dagger", "name": "Dagger", "price": 280, "category": "Medieval Fantasy", "description": "Light, quick, and easier to hide than it should be."},
    {"key": "shield", "name": "Shield", "price": 760, "category": "Medieval Fantasy", "description": "A dependable wall of iron and wood."},
    {"key": "knight armor", "name": "Knight Armor", "price": 1840, "category": "Medieval Fantasy", "description": "Polished plate built to hold a line."},
    {"key": "helmet", "name": "Helmet", "price": 430, "category": "Medieval Fantasy", "description": "Solid protection with a battle-worn finish."},
    {"key": "cloak", "name": "Cloak", "price": 510, "category": "Medieval Fantasy", "description": "A dark cloak that moves like quiet confidence."},
    {"key": "magic ring", "name": "Magic Ring", "price": 1180, "category": "Medieval Fantasy", "description": "A faintly glowing ring with old power in it."},
    {"key": "royal crown", "name": "Royal Crown", "price": 2650, "category": "Medieval Fantasy", "description": "A rare symbol of status, weight, and spectacle."},
    {"key": "lantern", "name": "Lantern", "price": 240, "category": "Medieval Fantasy", "description": "A steady light for dark halls and late roads."},
    {"key": "spellbook", "name": "Spellbook", "price": 980, "category": "Medieval Fantasy", "description": "An annotated tome filled with dangerous margin notes."},
    {"key": "elixir", "name": "Elixir", "price": 170, "category": "Medieval Fantasy", "description": "A glowing restorative with a sharp herbal bite.", "consumable": True, "use_text": "You drink the elixir and feel your focus snap back into place."},
    {"key": "battle boots", "name": "Battle Boots", "price": 390, "category": "Medieval Fantasy", "description": "Heavy boots made for stone halls and rough ground."},
    {"key": "gauntlets", "name": "Gauntlets", "price": 340, "category": "Medieval Fantasy", "description": "Reinforced gloves built for weapon weight and impact."},
    {"key": "war banner", "name": "War Banner", "price": 1480, "category": "Medieval Fantasy", "description": "A tall standard that turns attention into pressure."},
    {"key": "dragon trophy", "name": "Dragon Trophy", "price": 3400, "category": "Medieval Fantasy", "description": "A rare display piece that feels impossible to ignore."},
    {"key": "penthouse suite", "name": "Penthouse Suite", "price": 75000, "category": "Luxury+", "description": "A skyline-level residence with staff, service, and breathtaking views."},
    {"key": "luxury yacht", "name": "Luxury Yacht", "price": 120000, "category": "Luxury+", "description": "A private vessel built for quiet oceans and loud status."},
    {"key": "sports car", "name": "Sports Car", "price": 95000, "category": "Luxury+", "description": "An elite machine that turns every route into an entrance."},
    {"key": "private chef", "name": "Private Chef", "price": 60000, "category": "Luxury+", "description": "A personal culinary upgrade that keeps your routine polished."},
    {"key": "diamond wardrobe", "name": "Diamond Wardrobe", "price": 88000, "category": "Luxury+", "description": "A curated collection of tailored looks for any room you walk into."},
    {"key": "golden throne", "name": "Golden Throne", "price": 180000, "category": "Legendary", "description": "An impossible centerpiece built for rulers, myths, and spectacle."},
    {"key": "dragon statue", "name": "Dragon Statue", "price": 220000, "category": "Legendary", "description": "A towering monument that makes every room feel like a conquered hall."},
    {"key": "diamond armor", "name": "Diamond Armor", "price": 200000, "category": "Legendary", "description": "A gleaming defensive set that looks untouchable and expensive."},
    {"key": "celestial scepter", "name": "Celestial Scepter", "price": 165000, "category": "Legendary", "description": "A radiant command piece with the weight of an old empire behind it."},
    {"key": "private island", "name": "Private Island", "price": 350000, "category": "Prestige", "description": "A distant property where silence itself feels expensive."},
    {"key": "sky palace", "name": "Sky Palace", "price": 500000, "category": "Prestige", "description": "An altitude-defying estate with unmatched scale and prestige."},
    {"key": "elite vault", "name": "Elite Vault", "price": 420000, "category": "Prestige", "description": "A fortress-grade asset room built to protect wealth and influence."},
    {"key": "crypto empire", "name": "Crypto Empire", "price": 300000, "category": "Prestige", "description": "A sprawling digital operation with markets moving under your name."},
    {"key": "phoenix relic", "name": "Phoenix Relic", "price": 550000, "category": "Mythic", "description": "An ember-lit artifact rumored to turn defeat into another attempt."},
    {"key": "time artifact", "name": "Time Artifact", "price": 600000, "category": "Mythic", "description": "A sealed relic that bends precision, timing, and impossible luck."},
    {"key": "eternal crown", "name": "Eternal Crown", "price": 580000, "category": "Mythic", "description": "A final-tier symbol of rule, legend, and permanence."},
    {"key": "void compass", "name": "Void Compass", "price": 530000, "category": "Mythic", "description": "A directionless instrument that still somehow points toward treasure."},
    {"key": "global trade network", "name": "Global Trade Network", "price": 450000, "category": "Empire", "description": "A massive commercial grid that keeps wealth flowing around the clock."},
    {"key": "infinite bank license", "name": "Infinite Bank License", "price": 520000, "category": "Empire", "description": "An elite financial charter with absurd leverage behind every signature."},
    {"key": "kings domain", "name": "Kings Domain", "price": 600000, "category": "Empire", "description": "A sovereign-grade holding that feels less like ownership and more like rule."},
    {"key": "imperial airship", "name": "Imperial Airship", "price": 470000, "category": "Empire", "description": "A flying flagship built to project power over entire regions."},
)

SHOP_ITEM_LOOKUP: dict[str, dict[str, Any]] = {}
for _shop_item in SHOP_ITEMS:
    for _alias in {
        str(_shop_item["key"]),
        str(_shop_item["name"]),
        str(_shop_item["key"]).replace("_", " "),
        str(_shop_item["name"]).replace("_", " "),
        str(_shop_item["key"]).replace("'", ""),
        str(_shop_item["name"]).replace("'", ""),
    }:
        SHOP_ITEM_LOOKUP[re.sub(r"\s+", " ", _alias.lower().replace("_", " ").replace("-", " ")).strip()] = _shop_item

CATEGORY_ORDER: tuple[str, ...] = (
    "Lifestyle",
    "Decoration",
    "Utility",
    "Fun",
    "Pets",
    "Luxury",
    "Luxury+",
    "Legendary",
    "Prestige",
    "Mythic",
    "Empire",
    "Food",
    "Technology",
    "Medieval Fantasy",
)

CATEGORY_EMOJIS: dict[str, str] = {
    "Lifestyle": "🏠",
    "Decoration": "🖼️",
    "Utility": "🧰",
    "Fun": "🎲",
    "Pets": "\U0001F43E",
    "Luxury": "👑",
    "Luxury+": "💎",
    "Legendary": "🏆",
    "Prestige": "⭐",
    "Mythic": "🔮",
    "Empire": "🏛️",
    "Food": "🍜",
    "Technology": "💻",
    "Medieval Fantasy": "🛡️",
}

ITEM_EMOJIS: dict[str, str] = {
    "Small Apartment": "🏠",
    "Cozy Room": "🛏️",
    "Luxury Coat": "🧥",
    "Compact Loft": "🏢",
    "Watch": "⌚",
    "Necklace": "📿",
    "Book Subscription": "📚",
    "Gaming Chair": "🪑",
    "Dark Lamp": "💡",
    "Bookshelf": "📚",
    "Record Shelf": "💿",
    "Desk Plant": "🪴",
    "Vinyl Player": "📀",
    "Moonlit Rug": "🌙",
    "Framed Skyline Art": "🖼️",
    "Candle Set": "🕯️",
    "Glass Display Case": "🪟",
    "Wall Mirror": "🪞",
    "Coffee Machine": "☕",
    "Headphones": "🎧",
    "Phone": "📱",
    "Scooter": "🛴",
    "Bike": "🚲",
    "Thermos": "🧴",
    "Tool Kit": "🧰",
    "Portable Heater": "♨️",
    "Travel Bag": "🎒",
    "Espresso Cart": "🛒",
    "Fish Meal": "🐟",
    "Seal Pillow": "🦭",
    "Mini Projector": "📽️",
    "Arcade Token Pack": "🪙",
    "Card Deck": "🃏",
    "Board Game Set": "🎲",
    "Seal Plush": "🧸",
    "Retro Console": "🕹️",
    "Oceanview Suite": "🌊",
    "Tailored Suit": "👔",
    "Velvet Lounge Set": "🛋️",
    "Silver Signet Ring": "💍",
    "Midnight Watch": "⌚",
    "Coastal Villa Key": "🗝️",
    "Designer Headphones": "🎧",
    "Night Market Noodles": "🍜",
    "Seafood Platter": "🦐",
    "Dessert Box": "🍰",
    "Premium Coffee Beans": "☕",
    "Spiced Tea Set": "🍵",
    "Midnight Chocolate": "🍫",
    "Camera": "📷",
    "Tablet": "💻",
    "Smart Speaker": "🔊",
    "Mechanical Keyboard": "⌨️",
    "Ultrawide Monitor": "🖥️",
    "Signal Booster": "📡",
    "Sword": "⚔️",
    "Greatsword": "🗡️",
    "Dagger": "🔪",
    "Shield": "🛡️",
    "Knight Armor": "🛡️",
    "Helmet": "⛑️",
    "Cloak": "🧥",
    "Magic Ring": "💍",
    "Royal Crown": "👑",
    "Lantern": "🏮",
    "Spellbook": "📘",
    "Elixir": "🧪",
    "Battle Boots": "👢",
    "Gauntlets": "🧤",
    "War Banner": "🚩",
    "Dragon Trophy": "🐉",
    "Penthouse Suite": "🏙️",
    "Luxury Yacht": "🛥️",
    "Sports Car": "🏎️",
    "Private Chef": "👨‍🍳",
    "Diamond Wardrobe": "💎",
    "Golden Throne": "👑",
    "Dragon Statue": "🐉",
    "Diamond Armor": "🛡️",
    "Celestial Scepter": "🔱",
    "Private Island": "🏝️",
    "Sky Palace": "🏰",
    "Elite Vault": "🏦",
    "Crypto Empire": "🪙",
    "Phoenix Relic": "🔥",
    "Time Artifact": "⏳",
    "Eternal Crown": "👑",
    "Void Compass": "🧭",
    "Global Trade Network": "🌐",
    "Infinite Bank License": "🏦",
    "Kings Domain": "🏰",
    "Imperial Airship": "🛩️",
}

SHOP_CATEGORY_NOTES: dict[str, str] = {
    "Lifestyle": "Personal upgrades, clothing, and everyday comforts.",
    "Decoration": "Atmosphere, room style, and display pieces.",
    "Utility": "Practical gear for daily routines and movement.",
    "Fun": "Lighthearted picks for downtime and personality.",
    "Pets": "Companions with small passive bonuses, collectable charm, and long-term value.",
    "Luxury": "Premium status pieces and expensive upgrades.",
    "Luxury+": "Executive comforts, rare status upgrades, and top-tier lifestyle flexes.",
    "Legendary": "Collector-grade trophies, relics, and statement pieces with serious value.",
    "Prestige": "Elite assets, estates, and financial anchors for long-term growth.",
    "Mythic": "Endgame artifacts with rare power, massive prestige, and premium bonuses.",
    "Empire": "Nation-scale holdings, financial engines, and elite infrastructure.",
    "Food": "Consumables and quality comfort picks.",
    "Technology": "Devices and modern setup upgrades.",
    "Medieval Fantasy": "Blades, relics, armor, trophies, and old-world prestige.",
}

ITEM_EFFECTS: dict[str, dict[str, Any]] = {
    "small apartment": {"passive_income": 10, "prestige": 1, "description": "+10 coins every 5 minutes"},
    "cozy room": {"passive_income": 6, "prestige": 1, "description": "+6 coins every 5 minutes"},
    "compact loft": {"passive_income": 18, "prestige": 2, "description": "+18 coins every 5 minutes"},
    "oceanview suite": {"passive_income": 36, "prestige": 5, "description": "+36 coins every 5 minutes"},
    "coastal villa key": {"passive_income": 52, "prestige": 8, "description": "+52 coins every 5 minutes"},
    "coffee machine": {"action_bonus": {"work": 0.05}, "description": "+5% work income"},
    "premium coffee beans": {"action_bonus": {"work": 0.04}, "description": "+4% work income"},
    "espresso cart": {"action_bonus": {"work": 0.08}, "description": "+8% work income"},
    "tool kit": {"action_bonus": {"work": 0.03, "repair": 0.12, "craft": 0.08}, "description": "+repair/craft income"},
    "scooter": {"action_bonus": {"deliver": 0.1}, "description": "+10% delivery income"},
    "bike": {"action_bonus": {"deliver": 0.06}, "description": "+6% delivery income"},
    "gaming chair": {"xp_bonus": 0.1, "description": "+10% XP gain"},
    "bookshelf": {"action_bonus": {"quiz": 0.06}, "description": "+6% quiz rewards"},
    "book subscription": {"action_bonus": {"quiz": 0.1}, "description": "+10% quiz rewards"},
    "headphones": {"action_bonus": {"freelance": 0.05}, "description": "+5% freelance income"},
    "mechanical keyboard": {"action_bonus": {"freelance": 0.08}, "description": "+8% freelance income"},
    "ultrawide monitor": {"action_bonus": {"freelance": 0.12}, "description": "+12% freelance income"},
    "signal booster": {"action_bonus": {"freelance": 0.05}, "description": "+5% freelance income"},
    "travel bag": {"action_bonus": {"search": 0.05, "scavenge": 0.05}, "description": "+5% search and scavenge income"},
    "phone": {"utility": "social", "description": "Unlocks phone interaction scenes"},
    "luxury coat": {"prestige": 2, "description": "+2 prestige"},
    "tailored suit": {"prestige": 3, "description": "+3 prestige"},
    "velvet lounge set": {"prestige": 3, "description": "+3 prestige"},
    "silver signet ring": {"prestige": 2, "description": "+2 prestige"},
    "midnight watch": {"prestige": 2, "description": "+2 prestige"},
    "necklace": {"prestige": 1, "description": "+1 prestige"},
    "designer headphones": {"prestige": 2, "action_bonus": {"freelance": 0.1}, "description": "+10% freelance income, +2 prestige"},
    "sword": {"prestige": 1, "description": "+1 prestige"},
    "greatsword": {"action_bonus": {"rob": 0.04}, "prestige": 2, "description": "+4% rob payout, +2 prestige"},
    "dagger": {"action_bonus": {"steal": 0.06}, "description": "+6% steal payout"},
    "shield": {"prestige": 1, "description": "+1 prestige"},
    "knight armor": {"prestige": 3, "description": "+3 prestige"},
    "helmet": {"prestige": 1, "description": "+1 prestige"},
    "cloak": {"action_bonus": {"steal": 0.03}, "description": "+3% steal payout"},
    "magic ring": {"action_bonus": {"crash": 0.04}, "prestige": 2, "description": "+4% crash value, +2 prestige"},
    "royal crown": {"prestige": 5, "description": "+5 prestige"},
    "lantern": {"action_bonus": {"dungeon": 0.03}, "description": "+3% dungeon edge"},
    "spellbook": {"action_bonus": {"quiz": 0.08}, "prestige": 1, "description": "+8% quiz rewards, +1 prestige"},
    "battle boots": {"action_bonus": {"deliver": 0.04, "dungeon": 0.02}, "description": "+delivery and dungeon mobility"},
    "gauntlets": {"action_bonus": {"repair": 0.04, "dungeon": 0.02}, "description": "+repair and dungeon power"},
    "war banner": {"prestige": 3, "description": "+3 prestige"},
    "dragon trophy": {"prestige": 6, "description": "+6 prestige"},
    "penthouse suite": {"passive_income": 120, "prestige": 12, "description": "+120 coins every 5 minutes, +12 prestige"},
    "luxury yacht": {"passive_income": 145, "prestige": 15, "description": "+145 coins every 5 minutes, +15 prestige"},
    "sports car": {"action_bonus": {"deliver": 0.18, "search": 0.08}, "prestige": 8, "description": "+18% deliver income, +8% search income, +8 prestige"},
    "private chef": {"action_bonus": {"work": 0.12}, "xp_bonus": 0.04, "prestige": 4, "description": "+12% work income, +4% XP gain"},
    "diamond wardrobe": {"prestige": 10, "description": "+10 prestige"},
    "golden throne": {"prestige": 20, "description": "+20 prestige"},
    "dragon statue": {"prestige": 24, "action_bonus": {"dungeon": 0.08}, "description": "+8% dungeon edge, +24 prestige"},
    "diamond armor": {"prestige": 18, "action_bonus": {"dungeon": 0.1}, "description": "+10% dungeon edge, +18 prestige"},
    "celestial scepter": {"prestige": 14, "action_bonus": {"quiz": 0.12, "crash": 0.05}, "description": "+12% quiz rewards, +5% crash value, +14 prestige"},
    "private island": {"passive_income": 180, "prestige": 28, "description": "+180 coins every 5 minutes, +28 prestige"},
    "sky palace": {"passive_income": 220, "prestige": 35, "description": "+220 coins every 5 minutes, +35 prestige"},
    "elite vault": {"passive_income": 160, "prestige": 26, "action_bonus": {"gamble": 0.12}, "description": "+160 coins every 5 minutes, +12% gamble value, +26 prestige"},
    "crypto empire": {"passive_income": 150, "prestige": 22, "action_bonus": {"crash": 0.12, "gamble": 0.1}, "description": "+150 coins every 5 minutes, +crash and gamble value"},
    "phoenix relic": {"prestige": 32, "action_bonus": {"dungeon": 0.15}, "description": "+15% dungeon edge, +32 prestige"},
    "time artifact": {"prestige": 36, "action_bonus": {"work": 0.22, "quiz": 0.14, "crash": 0.08}, "description": "+22% work income, +14% quiz rewards, +36 prestige"},
    "eternal crown": {"prestige": 40, "action_bonus": {"work": 0.18}, "description": "+18% work income, +40 prestige"},
    "void compass": {"prestige": 24, "action_bonus": {"search": 0.18, "scavenge": 0.18, "dungeon": 0.08}, "description": "+search, scavenge, and dungeon bonuses"},
    "global trade network": {"passive_income": 200, "prestige": 30, "action_bonus": {"deliver": 0.16, "freelance": 0.14}, "description": "+200 coins every 5 minutes, +delivery and freelance income"},
    "infinite bank license": {"passive_income": 210, "prestige": 34, "action_bonus": {"gamble": 0.15}, "description": "+210 coins every 5 minutes, +15% gamble value, +34 prestige"},
    "kings domain": {"passive_income": 240, "prestige": 42, "description": "+240 coins every 5 minutes, +42 prestige"},
    "imperial airship": {"passive_income": 175, "prestige": 27, "action_bonus": {"deliver": 0.2, "search": 0.08}, "description": "+175 coins every 5 minutes, +20% deliver income, +27 prestige"},
}

PROPERTY_ITEM_KEYS: frozenset[str] = frozenset(
    key for key, effect in ITEM_EFFECTS.items() if effect.get("passive_income")
)

REWRITE_MODE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^very[\s_-]*simple(?:\s+|$)", "verysimple"),
    (r"^formal(?:\s+|$)", "formal"),
    (r"^simple(?:\s+|$)", "simple"),
    (r"^clean(?:\s+|$)", "clean"),
)

GAMBLE_PREFIXES: tuple[str, ...] = ("gamble", "bet", "coinflipbet")
BLACKJACK_PREFIXES: tuple[str, ...] = ("blackjack", "bj")
CARD_RANKS: tuple[str, ...] = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
CARD_SUITS: tuple[str, ...] = ("♠️", "♥️", "♦️", "♣️")
SLOT_SYMBOLS: tuple[str, ...] = ("🍒", "🍋", "🍇", "💎", "🔔", "⭐", "🪙", "7️⃣")
SLOT_COMMON_SYMBOLS: tuple[str, ...] = ("🍒", "🍋", "🍇")
SLOT_UNCOMMON_SYMBOLS: tuple[str, ...] = ("🔔", "⭐", "🪙")

PVP_ACTION_CONFIGS: dict[str, dict[str, Any]] = {
    "steal": {
        "cooldown": 6 * 60.0,
        "success_chance": 0.54,
        "min_target_wallet": 120,
        "take_range": (0.04, 0.09),
        "take_cap": 180,
        "failure_penalty": (20, 70),
        "success_templates": (
            "You slipped past {target_name}'s guard and stole {amount_phrase}.",
            "A careful move paid off. You stole {amount_phrase} from {target_name}.",
            "You found an opening, took {amount_phrase}, and disappeared before {target_name} noticed.",
            "The theft stayed quiet. You lifted {amount_phrase} from {target_name}.",
            "You kept it subtle and walked away with {amount_phrase} from {target_name}.",
        ),
        "failure_templates": (
            "{target_name} caught you reaching. You lost {amount_phrase} trying to play it off.",
            "Your timing failed and the attempt cost you {amount_phrase}.",
            "{target_name} noticed the move immediately. You dropped {amount_phrase} in the mess.",
            "The steal went cold and you lost {amount_phrase} getting away.",
        ),
    },
    "rob": {
        "cooldown": 10 * 60.0,
        "success_chance": 0.4,
        "min_target_wallet": 220,
        "take_range": (0.08, 0.16),
        "take_cap": 360,
        "failure_penalty": (50, 140),
        "success_templates": (
            "You rushed the moment and robbed {target_name} for {amount_phrase}.",
            "A bold move paid off. You got away with {amount_phrase} from {target_name}.",
            "You forced the opening and came back with {amount_phrase} from {target_name}.",
            "The robbery landed in your favor. You took {amount_phrase} from {target_name}.",
        ),
        "failure_templates": (
            "The robbery failed hard and cost you {amount_phrase}.",
            "{target_name} turned the tables and you lost {amount_phrase}.",
            "Your nerve broke at the worst moment. The failed robbery cost {amount_phrase}.",
            "Security closed in fast. You lost {amount_phrase} and had to back off.",
        ),
    },
    "heist": {
        "cooldown": 18 * 60.0,
        "success_chance": 0.25,
        "min_target_wallet": 450,
        "take_range": (0.16, 0.28),
        "take_cap": 900,
        "failure_penalty": (1, 1),
        "success_templates": (
            "The heist clicked into place. You escaped with {amount_phrase} from {target_name}.",
            "You ran a full heist on {target_name} and secured {amount_phrase}.",
            "Against the odds, the heist worked and paid {amount_phrase}.",
            "Every step lined up. You left the heist with {amount_phrase} from {target_name}.",
        ),
        "failure_templates": (
            "Your heist failed... you lost {amount_phrase} trying to escape.",
            "You got caught and barely escaped. You lost {amount_phrase}.",
            "The heist went wrong. You dropped {amount_phrase} while fleeing.",
            "The heist collapsed at the last second. You lost {amount_phrase} on the way out.",
        ),
    },
}

DAILY_MISSION_DEFS: tuple[dict[str, Any], ...] = (
    {"key": "work_shift", "name": "Shift Hours", "description": "Use work 3 times.", "progress_key": "work", "target": 3, "reward": 180},
    {"key": "street_begging", "name": "Street Begging", "description": "Use beg 2 times.", "progress_key": "beg", "target": 2, "reward": 110},
    {"key": "quiz_clear", "name": "Clear Answer", "description": "Win one quiz.", "progress_key": "quiz_win", "target": 1, "reward": 140},
    {"key": "shop_visit", "name": "Something New", "description": "Buy one item.", "progress_key": "buy_item", "target": 1, "reward": 130},
    {"key": "use_item", "name": "Make Use Of It", "description": "Use one inventory item.", "progress_key": "use_item", "target": 1, "reward": 120},
    {"key": "earn_500", "name": "Steady Income", "description": "Earn 500 coins in total today.", "progress_key": "earn_coins", "target": 500, "reward": 220},
    {"key": "blackjack_round", "name": "Table Visit", "description": "Play one round of blackjack.", "progress_key": "blackjack_play", "target": 1, "reward": 150},
    {"key": "slots_round", "name": "Machine Pull", "description": "Use slots once.", "progress_key": "slots_play", "target": 1, "reward": 120},
    {"key": "gamble_win", "name": "Lucky Turn", "description": "Win one gamble.", "progress_key": "gamble_win", "target": 1, "reward": 170},
    {"key": "delivery_run", "name": "Quick Route", "description": "Use deliver 2 times.", "progress_key": "deliver", "target": 2, "reward": 150},
)

ACHIEVEMENT_DEFS: tuple[dict[str, Any], ...] = (
    {"key": "earn_100", "name": "First Coins", "description": "Earn 100 coins total.", "metric": "total_earned", "target": 100, "prestige_reward": 1},
    {"key": "earn_1000", "name": "Pocket Weight", "description": "Earn 1000 coins total.", "metric": "total_earned", "target": 1000, "prestige_reward": 1},
    {"key": "work_10", "name": "Shift Regular", "description": "Use work 10 times.", "metric": "stat:work_uses", "target": 10, "prestige_reward": 1},
    {"key": "beg_10", "name": "Street Persistence", "description": "Use beg 10 times.", "metric": "stat:beg_uses", "target": 10, "prestige_reward": 1},
    {"key": "blackjack_win", "name": "Table Winner", "description": "Win a blackjack hand.", "metric": "stat:blackjack_wins", "target": 1, "prestige_reward": 1},
    {"key": "slot_jackpot", "name": "Jackpot Hit", "description": "Land a slot jackpot.", "metric": "stat:slot_jackpots", "target": 1, "prestige_reward": 2},
    {"key": "first_item", "name": "First Purchase", "description": "Buy your first shop item.", "metric": "stat:items_bought", "target": 1, "prestige_reward": 1},
    {"key": "property_owner", "name": "Property Holder", "description": "Own at least one property.", "metric": "property_count", "target": 1, "prestige_reward": 2},
    {"key": "daily_runner", "name": "Mission Rhythm", "description": "Complete 5 daily missions.", "metric": "stat:missions_completed", "target": 5, "prestige_reward": 2},
    {"key": "rob_success", "name": "Light Fingers", "description": "Succeed with rob or steal.", "metric": "stat:theft_successes", "target": 1, "prestige_reward": 1},
    {"key": "heist_success", "name": "Master Planner", "description": "Complete a successful heist.", "metric": "stat:heist_successes", "target": 1, "prestige_reward": 2},
    {"key": "profession_level_5", "name": "Career Climb", "description": "Reach profession level 5.", "metric": "profession_level_max", "target": 5, "prestige_reward": 2},
)

ACHIEVEMENT_LOOKUP: dict[str, dict[str, Any]] = {
    str(definition["key"]): definition
    for definition in ACHIEVEMENT_DEFS
}

PETS: tuple[dict[str, Any], ...] = (
    {"key": "seal pup", "name": "Seal Pup", "emoji": "🦭", "price": 850, "description": "A round, loyal little seal with a habit of following your routines.", "bonus_text": "+4% work income", "action_bonus": {"work": 0.04}},
    {"key": "shadow cat", "name": "Shadow Cat", "emoji": "🐈", "price": 980, "description": "A silent cat with cold patience and sharp timing.", "bonus_text": "+4% steal income", "action_bonus": {"steal": 0.04}},
    {"key": "ember fox", "name": "Ember Fox", "emoji": "🦊", "price": 1120, "description": "A warm-eyed fox that thrives in restless nights.", "bonus_text": "+5% gamble payout", "action_bonus": {"gamble": 0.05}},
    {"key": "frost wolf", "name": "Frost Wolf", "emoji": "🐺", "price": 1280, "description": "A calm predator with steady nerves under pressure.", "bonus_text": "+4% dungeon success edge", "dungeon_bonus": 0.04},
    {"key": "tiny wyvern", "name": "Tiny Wyvern", "emoji": "🐉", "price": 1750, "description": "Small, proud, and far more dramatic than its size should allow.", "bonus_text": "+6% crash cash-out value", "crash_bonus": 0.06},
    {"key": "moon owl", "name": "Moon Owl", "emoji": "🦉", "price": 920, "description": "Quiet wings, sharp eyes, and excellent timing.", "bonus_text": "+5% quiz reward", "action_bonus": {"quiz": 0.05}},
    {"key": "skeleton crow", "name": "Skeleton Crow", "emoji": "🐦", "price": 1010, "description": "A strange bird that always notices the shiny things first.", "bonus_text": "+4% search income", "action_bonus": {"search": 0.04}},
    {"key": "golden hound", "name": "Golden Hound", "emoji": "🐕", "price": 1480, "description": "A disciplined hound that never slows the pace.", "bonus_text": "+6% delivery income", "action_bonus": {"deliver": 0.06}},
    {"key": "marsh frog", "name": "Marsh Frog", "emoji": "🐸", "price": 640, "description": "A tiny swamp frog that somehow improves your luck.", "bonus_text": "+3% beg and scavenge income", "action_bonus": {"beg": 0.03, "scavenge": 0.03}},
    {"key": "crimson bat", "name": "Crimson Bat", "emoji": "🦇", "price": 1340, "description": "A quick red shadow with a taste for risky wins.", "bonus_text": "+5% blackjack payout", "action_bonus": {"blackjack": 0.05}},
)

PET_LOOKUP: dict[str, dict[str, Any]] = {
    re.sub(r"\s+", " ", str(pet["key"]).lower().replace("_", " ").replace("-", " ")).strip(): pet
    for pet in PETS
}

DUNGEON_FIGHTERS: tuple[dict[str, Any], ...] = (
    {"key": "rookie", "name": "Rookie", "emoji": "🧛", "bonus_chance": 0.03, "style": "steady"},
    {"key": "fighterjit", "name": "FighterJit", "emoji": "🦄", "bonus_chance": 0.0, "style": "wild"},
)

DUNGEON_FIGHTER_LOOKUP: dict[str, dict[str, Any]] = {
    str(fighter["key"]): fighter
    for fighter in DUNGEON_FIGHTERS
}

DUNGEON_REWARD_BONUS_MULTIPLIER = 1.25
DUNGEON_REWARD_MULTIPLIERS: tuple[float, ...] = (
    1.08,
    1.18,
    1.32,
    1.5,
    1.72,
    1.98,
    2.3,
    2.7,
    3.2,
    4.0,
)
ANCIENT_DUNGEON_REWARD_MULTIPLIERS: tuple[float, ...] = (
    0.65,
    1.0,
    1.45,
    2.0,
    2.8,
)
ANCIENT_DUNGEON_BOSSES: tuple[str, ...] = (
    "FdRxFiratxFdR",
    "-RomanEmpire-",
    "Prime Rookié",
    "Raged Prime Rookie",
    "The Noblesse",
)

DUNGEON_CREATURES: tuple[dict[str, Any], ...] = (
    {"name": "Skeleton Raider", "min_level": 1, "max_level": 3},
    {"name": "Cave Troll", "min_level": 1, "max_level": 4},
    {"name": "Shadow Wolf", "min_level": 1, "max_level": 4},
    {"name": "Bone Archer", "min_level": 1, "max_level": 5},
    {"name": "Grave Knight", "min_level": 2, "max_level": 6},
    {"name": "Swamp Lurker", "min_level": 2, "max_level": 5},
    {"name": "Stone Golem", "min_level": 3, "max_level": 7},
    {"name": "Dark Acolyte", "min_level": 3, "max_level": 7},
    {"name": "Venom Spider", "min_level": 3, "max_level": 6},
    {"name": "Hell Hound", "min_level": 4, "max_level": 8},
    {"name": "Moonfang Beast", "min_level": 5, "max_level": 9},
    {"name": "Wraith Guard", "min_level": 5, "max_level": 9},
    {"name": "Infernal Brute", "min_level": 6, "max_level": 10},
    {"name": "Ancient Wyvern", "min_level": 7, "max_level": 10},
    {"name": "Abyss Watcher", "min_level": 8, "max_level": 10},
)

DUNGEON_WIN_LINES: tuple[str, ...] = (
    "{fighter_name} struck the {enemy_name} and cleared the level.",
    "{fighter_name} pushed through the {enemy_name} and survived the floor.",
    "{fighter_name} broke the {enemy_name}'s defense and advanced the run.",
    "{fighter_name} kept pressure on the {enemy_name} and won the fight.",
    "{fighter_name} outlasted the {enemy_name} and secured the level.",
)

DUNGEON_LOSS_LINES: tuple[str, ...] = (
    "{fighter_name} was overwhelmed by the {enemy_name} and the run collapsed.",
    "The {enemy_name} turned the fight and {fighter_name} could not recover.",
    "{fighter_name} reached too far into danger and fell to the {enemy_name}.",
    "The {enemy_name} broke the pace of the run and {fighter_name} lost the floor.",
    "{fighter_name} made one mistake too many against the {enemy_name}.",
)
SAFE_DUNGEON_FIGHTERS: tuple[dict[str, Any], ...] = (
    {"key": "rookie", "name": "Rookie", "emoji": "\U0001F9DB", "bonus_chance": 0.03, "style": "steady"},
    {"key": "fighterjit", "name": "FighterJit", "emoji": "\U0001F984", "bonus_chance": 0.0, "style": "wild"},
)
SAFE_DUNGEON_FIGHTER_LOOKUP: dict[str, dict[str, Any]] = {
    str(fighter["key"]): fighter
    for fighter in SAFE_DUNGEON_FIGHTERS
}
SAFE_ANCIENT_DUNGEON_BOSSES: tuple[str, ...] = (
    "FdRxFiratxFdR",
    "-RomanEmpire-",
    "Prime Rooki\u00e9",
    "Raged Prime Rookie",
    "The Noblesse",
)
SAFE_DUNGEON_WIN_LINES: tuple[str, ...] = (
    "{fighter_name} cut through the {enemy_name} and claimed the floor.",
    "{fighter_name} landed the finishing blow and advanced past the {enemy_name}.",
    "The {enemy_name} collapsed under {fighter_name}'s final strike.",
    "{fighter_name} broke the {enemy_name}'s last defense and moved the run forward.",
    "A clean finish. {fighter_name} erased the {enemy_name} from the path.",
)
SAFE_DUNGEON_LOSS_LINES: tuple[str, ...] = (
    "{fighter_name} was overwhelmed before the final exchange with the {enemy_name}.",
    "The {enemy_name} countered hard, and {fighter_name} lost the floor.",
    "One mistake was enough. {fighter_name} fell to the {enemy_name}.",
    "The {enemy_name} broke the momentum and the run collapsed around {fighter_name}.",
    "{fighter_name} reached too far into danger and could not recover from the {enemy_name}'s answer.",
)
SAFE_ANCIENT_DUNGEON_WIN_LINES: tuple[str, ...] = (
    "{fighter_name} unleashed a decisive finishing strike on {enemy_name}.",
    "{enemy_name} fell after a brutal final blow from {fighter_name}.",
    "{fighter_name} shattered the final defense of {enemy_name} and cleared the floor.",
    "A clean execution. {enemy_name} has been defeated by {fighter_name}.",
    "The finishing hit landed true. {enemy_name} was erased from the path by {fighter_name}.",
)
SAFE_ANCIENT_DUNGEON_LOSS_LINES: tuple[str, ...] = (
    "{fighter_name} was overwhelmed before the final exchange with {enemy_name}.",
    "{enemy_name} countered with crushing force, and the run cracked apart.",
    "The boss answered the last move and {fighter_name} could not recover.",
    "One opening was all {enemy_name} needed. The Ancient floor was lost.",
    "{fighter_name} was driven back as {enemy_name} seized the last exchange.",
)
SAFE_ANCIENT_DUNGEON_COMPLETION_LINES: tuple[str, ...] = (
    "Ancient Dungeon Cleared.",
    "The gauntlet has fallen.",
    "All Ancient bosses have been defeated.",
    "The final trial is over. Victory is yours.",
)

PHONE_SELF_RESPONSES: tuple[str, ...] = (
    "You unlock your phone, check your messages, and lose a few quiet minutes to the glow.",
    "You scroll through your phone and pause on a note you forgot you wrote.",
    "You open your phone, skim a few notifications, and send a quick text before locking it again.",
    "You check your phone late at night and the screen lights the room just enough to feel cinematic.",
    "You open your phone, clear a few notifications, and end up reading old messages longer than planned.",
)

PHONE_TARGET_RESPONSES: tuple[str, ...] = (
    "You called {target_name} and the conversation drifted on longer than you expected.",
    "You texted {target_name} and the reply pulled you into a surprisingly long conversation.",
    "You opened your phone, messaged {target_name}, and stayed on the chat screen for a while after.",
    "You called {target_name} just to hear their voice for a moment and somehow lost track of time.",
    "You sent {target_name} a late message and the conversation carried the mood of the night with it.",
)

GAMBLE_WIN_MESSAGES: tuple[str, ...] = (
    "Luck broke your way. You risked {risk_phrase} and walked away with a total payout of {payout_phrase}.",
    "You flipped the odds and doubled your stake. {risk_phrase} turned into {payout_phrase}.",
    "The bet landed in your favor. You put up {risk_phrase} and cashed out {payout_phrase}.",
    "You gambled with steady nerves and won. Your {risk_phrase} became {payout_phrase}.",
    "The table turned for you. You risked {risk_phrase} and claimed {payout_phrase}.",
)

GAMBLE_LOSS_MESSAGES: tuple[str, ...] = (
    "Luck turned away at the last second. You lost {risk_phrase}.",
    "The bet slipped out of your hands and cost you {risk_phrase}.",
    "You pushed your luck and the table took {risk_phrase}.",
    "The wager went cold. You dropped {risk_phrase}.",
    "This round did not go your way. You lost {risk_phrase}.",
)

ITEM_USE_FLAVORS: dict[str, dict[str, str]] = {
    "Small Apartment": {"verb": "unlock", "scene": "the quiet inside feels earned", "comfort": "having a place of your own settles your mood", "detail": "you take in the stillness for a minute", "finish": "it makes the whole night feel steadier"},
    "Cozy Room": {"verb": "step into", "scene": "the soft warmth immediately slows everything down", "comfort": "the room feels like an easy reset", "detail": "you take a breath and let the comfort do its work", "finish": "it leaves the evening gentler than before"},
    "Luxury Coat": {"verb": "slip on", "scene": "the fit is sharp and deliberate", "comfort": "it adds instant confidence to the moment", "detail": "you smooth the sleeves and admire the clean finish", "finish": "it makes stepping out feel effortless"},
    "Compact Loft": {"verb": "open up", "scene": "the extra space changes the whole energy of the room", "comfort": "the loft feels polished and practical at once", "detail": "you look across the room and appreciate the upgrade", "finish": "it turns an ordinary evening into something nicer"},
    "Watch": {"verb": "check", "scene": "the face catches the light just right", "comfort": "it makes your timing feel a little cleaner", "detail": "you adjust it on your wrist and admire the finish", "finish": "it gives the moment a sharper edge"},
    "Necklace": {"verb": "fasten", "scene": "the small shine adds exactly enough presence", "comfort": "it pulls your whole look together", "detail": "you touch the pendant for a second before moving on", "finish": "it leaves you looking more composed"},
    "Book Subscription": {"verb": "open", "scene": "a fresh title immediately catches your attention", "comfort": "the stack feels like time well spent", "detail": "you flip through new pages and pick your next read", "finish": "it gives the day a quieter rhythm"},
    "Gaming Chair": {"verb": "sink into", "scene": "the support makes long sessions feel easy", "comfort": "your setup instantly feels more complete", "detail": "you adjust the chair until it feels exactly right", "finish": "it leaves you ready for a long night"},
    "Dark Lamp": {"verb": "switch on", "scene": "the moody glow changes the whole room", "comfort": "the low light makes everything feel calmer", "detail": "you let the shadows settle into place", "finish": "it turns the space cinematic in seconds"},
    "Bookshelf": {"verb": "straighten", "scene": "the shelves look better the longer you stare at them", "comfort": "seeing everything in order feels satisfying", "detail": "you reorganize a few favorites and admire the result", "finish": "it makes the room feel more lived in"},
    "Record Shelf": {"verb": "browse", "scene": "every album feels like a mood waiting to happen", "comfort": "the collection gives the room character", "detail": "you slide a favorite record forward for later", "finish": "it makes the setup feel personal"},
    "Desk Plant": {"verb": "water", "scene": "the small bit of green softens the whole desk", "comfort": "it makes the space feel less mechanical", "detail": "you turn the pot toward the light and tidy the leaves", "finish": "it gives the corner a calmer feel"},
    "Vinyl Player": {"verb": "drop the needle on", "scene": "the warm sound fills the room in a way streaming never quite does", "comfort": "the crackle gives everything more texture", "detail": "you let the opening bars settle in before moving", "finish": "it makes the room feel carefully chosen"},
    "Moonlit Rug": {"verb": "step onto", "scene": "the soft texture changes the whole floor beneath you", "comfort": "it makes the room feel more complete", "detail": "you look down and appreciate how well it ties everything together", "finish": "it quietly upgrades the whole space"},
    "Framed Skyline Art": {"verb": "pause in front of", "scene": "the print gives the wall real presence", "comfort": "it sharpens the mood of the room", "detail": "you straighten the frame and admire the view it suggests", "finish": "it adds a clean city-night energy"},
    "Candle Set": {"verb": "light", "scene": "the flicker softens the edges of the room", "comfort": "the warmer light slows your thoughts a little", "detail": "you watch the flame settle into an even glow", "finish": "it makes the atmosphere feel intentional"},
    "Glass Display Case": {"verb": "arrange", "scene": "the case makes even small items look important", "comfort": "seeing everything displayed this neatly feels good", "detail": "you shift a few pieces until the layout feels perfect", "finish": "it turns your favorites into a proper showcase"},
    "Wall Mirror": {"verb": "glance into", "scene": "the reflection catches the room's best angles", "comfort": "it makes the space feel brighter and larger", "detail": "you adjust the frame and check the result", "finish": "it gives the room a cleaner finish"},
    "Coffee Machine": {"verb": "brew with", "scene": "the aroma fills the room almost immediately", "comfort": "the first sip hits exactly where it should", "detail": "you listen to the machine work while the room wakes up", "finish": "it leaves you more ready for whatever comes next"},
    "Headphones": {"verb": "put on", "scene": "the outside world drops away behind the sound", "comfort": "the clarity makes every track feel sharper", "detail": "you settle them into place and let the audio take over", "finish": "it turns a normal moment into your own space"},
    "Phone": {"verb": "unlock", "scene": "the screen lights up the moment in a familiar way", "comfort": "it pulls you into messages, notes, and quiet little habits", "detail": "you clear a few notifications and linger on the home screen", "finish": "it makes the room feel a little less empty"},
    "Scooter": {"verb": "start up", "scene": "the engine sounds ready before you are", "comfort": "it makes the city feel smaller and easier to cross", "detail": "you take a short ride just to clear your head", "finish": "it leaves you moving lighter than before"},
    "Bike": {"verb": "take out", "scene": "the ride feels clean and steady", "comfort": "a little movement improves everything", "detail": "you coast for a while without needing a reason", "finish": "it makes the air feel better"},
    "Thermos": {"verb": "pour from", "scene": "the drink stays hot exactly as promised", "comfort": "it is the kind of reliability you notice on long days", "detail": "you take a careful sip and let the warmth settle in", "finish": "it makes the shift feel easier"},
    "Tool Kit": {"verb": "open", "scene": "everything inside looks ready for real work", "comfort": "having the right tools nearby is its own relief", "detail": "you tighten a loose part just because you can", "finish": "it makes the place feel more under control"},
    "Portable Heater": {"verb": "switch on", "scene": "the cold edge in the room fades fast", "comfort": "the warmth settles into the space without asking", "detail": "you stay near it a little longer than planned", "finish": "it makes the room feel livable again"},
    "Travel Bag": {"verb": "pack", "scene": "everything fits with room to spare", "comfort": "being ready to leave feels oddly calming", "detail": "you zip it up and appreciate the clean setup", "finish": "it makes short trips feel easy"},
    "Espresso Cart": {"verb": "roll out", "scene": "the setup looks serious in the best way", "comfort": "it turns coffee into a ritual instead of a shortcut", "detail": "you tune the station until it feels perfect", "finish": "it makes the whole routine look premium"},
    "Fish Meal": {"verb": "eat", "scene": "the warmth lands immediately", "comfort": "it tastes like exactly the right kind of simple win", "detail": "you finish the plate without leaving much behind", "finish": "it leaves you properly recharged"},
    "Seal Pillow": {"verb": "hug", "scene": "the softness does the work instantly", "comfort": "it takes the edge off the day in a second", "detail": "you settle into it and let yourself relax", "finish": "it improves the mood immediately"},
    "Mini Projector": {"verb": "switch on", "scene": "the wall turns into a screen in seconds", "comfort": "it makes the room feel larger and more alive", "detail": "you throw on something easy and let it play", "finish": "it turns the evening into a proper night in"},
    "Arcade Token Pack": {"verb": "shake", "scene": "the sound alone feels promising", "comfort": "it carries the energy of a good night out", "detail": "you pocket a few tokens and grin at the thought of using them", "finish": "it makes the night feel more playful"},
    "Card Deck": {"verb": "shuffle", "scene": "the crisp sound never gets old", "comfort": "it invites an easy kind of focus", "detail": "you run through a few hands just for the feel of it", "finish": "it keeps your hands busy in the best way"},
    "Board Game Set": {"verb": "set up", "scene": "the table suddenly feels like a place people gather", "comfort": "it changes the room from quiet to expectant", "detail": "you line up the pieces and admire the board", "finish": "it makes the night feel ready for company"},
    "Seal Plush": {"verb": "pick up", "scene": "it is impossible not to smile at least a little", "comfort": "the softness does exactly what it was bought for", "detail": "you toss it onto the bed and then pull it back closer", "finish": "it adds a small, silly kind of comfort"},
    "Retro Console": {"verb": "boot up", "scene": "the old startup sound hits immediately", "comfort": "the nostalgia makes the whole room warmer", "detail": "you lose a few minutes to a familiar screen", "finish": "it makes the setup feel more alive"},
    "Oceanview Suite": {"verb": "step into", "scene": "the view does most of the talking", "comfort": "everything about it feels expensive in the right way", "detail": "you pause by the window longer than you meant to", "finish": "it makes the city feel far away"},
    "Tailored Suit": {"verb": "button up", "scene": "the fit is sharp enough to change your posture", "comfort": "it makes confidence feel almost automatic", "detail": "you check the lines and appreciate the clean tailoring", "finish": "it turns preparation into a statement"},
    "Velvet Lounge Set": {"verb": "sink into", "scene": "the room instantly feels more refined", "comfort": "it invites you to stay longer than planned", "detail": "you lean back and let the quiet settle around you", "finish": "it makes the whole space feel premium"},
    "Silver Signet Ring": {"verb": "turn over in your hand", "scene": "the polished surface catches a sharp line of light", "comfort": "small details like this change the whole look", "detail": "you slip it on and appreciate the weight", "finish": "it adds just enough presence"},
    "Midnight Watch": {"verb": "fasten", "scene": "the dark dial looks better the closer you check it", "comfort": "it gives every glance at the time a little style", "detail": "you adjust the strap and admire the finish", "finish": "it sharpens the whole outfit"},
    "Coastal Villa Key": {"verb": "hold up", "scene": "it feels more like a promise than an object", "comfort": "knowing what it opens changes the whole mood", "detail": "you let it spin once in your fingers", "finish": "it carries the weight of real progress"},
    "Designer Headphones": {"verb": "put on", "scene": "the sound feels fuller and cleaner than before", "comfort": "the first track alone justifies the purchase", "detail": "you sit back and let the mix unfold", "finish": "it makes every playlist feel more expensive"},
    "Night Market Noodles": {"verb": "finish", "scene": "the broth and heat do exactly what you hoped for", "comfort": "it tastes like a good decision made at the right hour", "detail": "you linger over the last bite for a second", "finish": "it leaves the night warmer"},
    "Seafood Platter": {"verb": "dig into", "scene": "the plate feels generous before the first bite", "comfort": "it turns the meal into a proper reward", "detail": "you slow down enough to enjoy the good parts", "finish": "it feels like money well spent"},
    "Dessert Box": {"verb": "open", "scene": "the presentation alone improves the mood", "comfort": "each piece feels like a small win", "detail": "you choose the best-looking one first", "finish": "it makes the evening softer"},
    "Premium Coffee Beans": {"verb": "grind", "scene": "the aroma is strong enough to change the room", "comfort": "it makes coffee feel like a ritual instead of a habit", "detail": "you take your time setting everything up properly", "finish": "it raises the standard for the whole morning"},
    "Spiced Tea Set": {"verb": "brew", "scene": "the steam carries the spices through the room", "comfort": "the warmth comes with a slower, calmer pace", "detail": "you let the tea steep just a little longer", "finish": "it leaves the room gentler than before"},
    "Midnight Chocolate": {"verb": "unwrap", "scene": "the first bite is richer than expected", "comfort": "it feels like a reward for making it through the day", "detail": "you let it melt slowly instead of rushing it", "finish": "it improves the mood almost immediately"},
    "Camera": {"verb": "raise", "scene": "even ordinary corners start looking deliberate through the lens", "comfort": "it changes the way you notice light", "detail": "you take a few test shots just because you can", "finish": "it makes the night feel worth framing"},
    "Tablet": {"verb": "wake up", "scene": "the screen is bright enough to pull you straight in", "comfort": "it makes reading, browsing, and planning feel effortless", "detail": "you move between apps until something catches you", "finish": "it smooths out the downtime"},
    "Smart Speaker": {"verb": "queue up", "scene": "the room answers with sound almost immediately", "comfort": "it turns empty space into atmosphere", "detail": "you test a few tracks just to hear the balance", "finish": "it makes the room feel occupied"},
    "Mechanical Keyboard": {"verb": "type on", "scene": "the clean clicks are satisfying in a way they should not be", "comfort": "it makes even simple typing feel deliberate", "detail": "you tap out a few lines just for the feel of it", "finish": "it sharpens the whole setup"},
    "Ultrawide Monitor": {"verb": "turn on", "scene": "the extra space changes everything at once", "comfort": "your desk suddenly feels like a command center", "detail": "you spread a few windows out just because you can", "finish": "it makes work and play both feel upgraded"},
    "Signal Booster": {"verb": "set up", "scene": "dead zones stop being part of the room", "comfort": "a stable signal is more satisfying than it should be", "detail": "you check the connection in the far corner just to confirm it worked", "finish": "it makes the whole place run smoother"},
}


@dataclass(slots=True)
class BlackjackSession:
    guild_id: int
    user_id: int
    display_name: str
    bet: int
    original_bet: int
    player_hand: list[tuple[str, str]]
    dealer_hand: list[tuple[str, str]]
    deck: list[tuple[str, str]]
    message: Optional[discord.Message] = None
    resolved: bool = False
    doubled: bool = False
    outcome: Optional[str] = None
    result_note: Optional[str] = None
    payout_amount: int = 0
    wallet_after: Optional[int] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(slots=True)
class MultiplayerBlackjackSession:
    guild_id: int
    challenger_id: int
    challenger_name: str
    target_id: int
    target_name: str
    bet: int
    challenger_hand: list[tuple[str, str]] = field(default_factory=list)
    target_hand: list[tuple[str, str]] = field(default_factory=list)
    deck: list[tuple[str, str]] = field(default_factory=list)
    current_player_id: Optional[int] = None
    pending_acceptance: bool = True
    accepted: bool = False
    challenger_stood: bool = False
    target_stood: bool = False
    challenger_busted: bool = False
    target_busted: bool = False
    message: Optional[discord.Message] = None
    resolved: bool = False
    result_note: Optional[str] = None
    payout_amount: int = 0
    winner_id: Optional[int] = None
    refunded: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(slots=True)
class SlotOutcome:
    reels: tuple[str, str, str]
    outcome: str
    payout_amount: int
    result_text: str


@dataclass(slots=True)
class CrashSession:
    guild_id: int
    user_id: int
    display_name: str
    bet: int
    crash_point: float
    bonus_multiplier: float = 0.0
    current_multiplier: float = 1.6
    peak_multiplier: float = 1.5
    tick_count: int = 0
    trend_label: str = "Taxiing smoothly"
    history: list[float] = field(default_factory=lambda: [1.0])
    message: Optional[discord.Message] = None
    resolved: bool = False
    cashed_out: bool = False
    payout_amount: int = 0
    wallet_after: Optional[int] = None
    result_note: Optional[str] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(slots=True)
class DuelSession:
    guild_id: int
    challenger_id: int
    challenger_name: str
    target_id: int
    target_name: str
    bet: int
    current_round: int = 1
    challenger_score: int = 0
    target_score: int = 0
    challenger_choice: Optional[str] = None
    target_choice: Optional[str] = None
    message: Optional[discord.Message] = None
    resolved: bool = False
    result_note: Optional[str] = None
    winner_id: Optional[int] = None
    payout_amount: int = 0
    refunded: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(slots=True)
class CoinflipSession:
    guild_id: int
    challenger_id: int
    challenger_name: str
    target_id: int
    target_name: str
    bet: int
    side_choice: Optional[str] = None
    accepted: bool = False
    message: Optional[discord.Message] = None
    resolved: bool = False
    result_note: Optional[str] = None
    winner_id: Optional[int] = None
    payout_amount: int = 0
    refunded: bool = False
    revealed_side: Optional[str] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(slots=True)
class GuessSession:
    guild_id: int
    user_id: int
    display_name: str
    bet: int
    target_number: int
    tries_left: int
    max_tries: int
    low_bound: int = 1
    high_bound: int = 100
    message: Optional[discord.Message] = None
    resolved: bool = False
    result_note: Optional[str] = None
    payout_amount: int = 0
    wallet_after: Optional[int] = None
    guesses: list[int] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(slots=True)
class TriviaQuestion:
    question: str
    category: str
    difficulty: str
    options: list[str]
    correct_index: int
    correct_answer: str


@dataclass(slots=True)
class TriviaSession:
    guild_id: int
    channel_id: int
    host_user_id: int
    message: Optional[discord.Message] = None
    current_question: Optional[TriviaQuestion] = None
    round_number: int = 0
    question_resolved: bool = False
    last_activity_at: float = 0.0
    result_note: Optional[str] = None
    payout_amount: int = 0
    xp_reward: int = 0
    winner_id: Optional[int] = None
    resolved: bool = False
    answered_user_ids: set[int] = field(default_factory=set)
    question_task: Optional[asyncio.Task[Any]] = None
    advance_task: Optional[asyncio.Task[Any]] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(slots=True)
class DrawGameSession:
    guild_id: int
    channel_id: int
    host_user_id: int
    answer: str
    normalized_answers: set[str]
    clue: str
    drawing: list[list[list[int]]]
    reward_base: int
    started_at: float
    reveal_phase: int = 0
    hint_level: int = 0
    message: Optional[discord.Message] = None
    resolved: bool = False
    result_note: Optional[str] = None
    winner_id: Optional[int] = None
    payout_amount: int = 0
    reveal_task: Optional[asyncio.Task[Any]] = None
    timeout_task: Optional[asyncio.Task[Any]] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(slots=True)
class HangmanSession:
    guild_id: int
    channel_id: int
    host_user_id: int
    answer: str
    guessed_letters: set[str]
    remaining_attempts: int
    max_attempts: int
    reward_base: int
    started_at: float
    message: Optional[discord.Message] = None
    resolved: bool = False
    result_note: Optional[str] = None
    winner_id: Optional[int] = None
    payout_amount: int = 0
    timeout_task: Optional[asyncio.Task[Any]] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(slots=True)
class WordChainSession:
    guild_id: int
    channel_id: int
    host_user_id: int
    current_word: str
    required_letter: str
    used_words: set[str]
    history: list[tuple[str, str]]
    started_at: float
    message: Optional[discord.Message] = None
    resolved: bool = False
    result_note: Optional[str] = None
    last_contributor_id: Optional[int] = None
    last_contributor_name: Optional[str] = None
    payout_amount: int = 0
    timeout_task: Optional[asyncio.Task[Any]] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(slots=True)
class DungeonSession:
    guild_id: int
    user_id: int
    display_name: str
    bet: int
    fighter_key: Optional[str] = None
    level: int = 1
    enemy_name: Optional[str] = None
    banked_payout: int = 0
    life_charges: int = 0
    companion_key: Optional[str] = None
    ancient_phase: bool = False
    awaiting_ancient_choice: bool = False
    normal_payout_amount: int = 0
    message: Optional[discord.Message] = None
    resolved: bool = False
    result_note: Optional[str] = None
    timed_out_after_start: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def fighterseal_active(self) -> bool:
        return self.companion_key == "fighterseal"

    @fighterseal_active.setter
    def fighterseal_active(self, value: bool) -> None:
        if value:
            self.companion_key = "fighterseal"
        elif self.companion_key == "fighterseal":
            self.companion_key = None

BEG_DONORS = (
    "a tired fisherman",
    "a wealthy merchant",
    "a kind tourist",
    "a quiet dock worker",
    "a sleepy courier",
    "a drifting street artist",
    "a late-night mechanic",
    "a cheerful barista",
    "a bundled-up traveler",
    "a jewel crafter with a soft spot",
    "an old harbor captain",
    "a patient librarian",
    "a seamstress on a break",
    "a programmer leaving the office",
    "a medic carrying spare change",
    "a night guard finishing a shift",
    "a taxi driver waiting for the next ride",
    "a seal diver drying off at the pier",
    "a jeweler checking a velvet case",
    "a street vendor counting the day's notes",
    "a farmer resting by the market gate",
    "a builder covered in dust",
    "a teacher carrying too many papers",
    "a musician packing up after a set",
)

SEARCH_MESSAGES = (
    "You searched under a loose market stall panel and found {amount_phrase}.",
    "You checked a forgotten jacket pocket and found {amount_phrase}.",
    "You searched a quiet bench area and picked up {amount_phrase}.",
    "You searched a cluttered back shelf and came away with {amount_phrase}.",
    "You checked the lost-and-found drawer and turned up {amount_phrase}.",
)

FISH_MESSAGES = (
    "You fished along the cold pier and sold the catch for {amount_phrase}.",
    "You cast a clean line and earned {amount_phrase} from the haul.",
    "A patient afternoon of fishing brought in {amount_phrase}.",
    "You hauled in a better catch than expected and made {amount_phrase}.",
    "A steady morning at the water paid out {amount_phrase}.",
)

HUNT_MESSAGES = (
    "You tracked carefully through the brush and earned {amount_phrase}.",
    "A good hunt paid out {amount_phrase}.",
    "You returned from the hunt with goods worth {amount_phrase}.",
    "You followed a clean trail and brought back {amount_phrase}.",
    "A sharp-eyed hunt ended with {amount_phrase} in rewards.",
)

MINE_MESSAGES = (
    "You mined a rough seam and sold the ore for {amount_phrase}.",
    "A dusty shift underground paid {amount_phrase}.",
    "You brought back a cart of ore worth {amount_phrase}.",
    "You cracked open a promising rock face and earned {amount_phrase}.",
    "A long mining run turned into {amount_phrase}.",
)

DELIVER_MESSAGES = (
    "You completed a rush delivery and earned {amount_phrase}.",
    "A long route across town brought in {amount_phrase}.",
    "You delivered packages without delay and earned {amount_phrase}.",
    "You handled a stack of same-day drop-offs for {amount_phrase}.",
    "A careful delivery run paid out {amount_phrase}.",
)

SCAVENGE_MESSAGES = (
    "You scavenged through forgotten crates and made {amount_phrase}.",
    "A careful scavenging run turned up {amount_phrase}.",
    "You found reusable scraps and sold them for {amount_phrase}.",
    "You sorted through metal piles and cleared {amount_phrase}.",
    "A lucky scavenging route gave you {amount_phrase}.",
)

FREELANCE_MESSAGES = (
    "You picked up a freelance contract and earned {amount_phrase}.",
    "A last-minute client needed help, and you made {amount_phrase}.",
    "You wrapped a quick freelance gig for {amount_phrase}.",
    "You polished a rushed client request and earned {amount_phrase}.",
    "A short remote project paid out {amount_phrase}.",
)

CRAFT_MESSAGES = (
    "You crafted custom pieces and sold them for {amount_phrase}.",
    "A careful crafting session turned into {amount_phrase}.",
    "You finished a small commission and earned {amount_phrase}.",
    "You built something clean by hand and made {amount_phrase}.",
    "A focused crafting run paid {amount_phrase}.",
)

REPAIR_MESSAGES = (
    "You repaired damaged gear and earned {amount_phrase}.",
    "A stack of repair tickets brought in {amount_phrase}.",
    "You fixed a stubborn device and made {amount_phrase}.",
    "You patched cracked equipment for {amount_phrase}.",
    "A good repair shift paid out {amount_phrase}.",
)

PATROL_MESSAGES = (
    "You patrolled a quiet route and earned {amount_phrase}.",
    "A late patrol shift paid {amount_phrase}.",
    "You kept the area clear and collected {amount_phrase}.",
    "You finished a careful patrol round for {amount_phrase}.",
    "A cold watch route ended with {amount_phrase}.",
)

WORK_RESULT_TEMPLATES = (
    "You opened your {job} shift strong and earned {amount_phrase}.",
    "You closed a busy block of work as a {job} and earned {amount_phrase}.",
    "You picked up extra hours as a {job} and earned {amount_phrase}.",
    "You handled a rush as a {job} and earned {amount_phrase}.",
    "You worked a late schedule as a {job} and earned {amount_phrase}.",
    "You kept a demanding {job} shift under control and earned {amount_phrase}.",
    "You stepped into a hectic {job} run and earned {amount_phrase}.",
    "You took a quiet shift as a {job} and still earned {amount_phrase}.",
    "You covered a teammate's hours as a {job} and earned {amount_phrase}.",
    "You stayed sharp through a long {job} shift and earned {amount_phrase}.",
    "You fixed a broken console during your {job} shift and earned {amount_phrase}.",
    "You calmed a messy handoff as a {job} and earned {amount_phrase}.",
    "You carried the pace through a packed afternoon as a {job} and earned {amount_phrase}.",
    "You wrapped up a messy task list as a {job} and earned {amount_phrase}.",
    "You handled premium requests as a {job} and earned {amount_phrase}.",
    "You took on a night rotation as a {job} and earned {amount_phrase}.",
    "You sorted urgent requests as a {job} and earned {amount_phrase}.",
    "You handled fragile work with clean timing as a {job} and earned {amount_phrase}.",
    "You got called in early as a {job} and earned {amount_phrase}.",
    "You stayed after closing as a {job} and earned {amount_phrase}.",
    "You worked through a rough weather shift as a {job} and earned {amount_phrase}.",
    "You cleared a backlog as a {job} and earned {amount_phrase}.",
    "You turned a messy day into a profitable one as a {job} and earned {amount_phrase}.",
    "You delivered consistent work as a {job} and earned {amount_phrase}.",
    "You handled a difficult assignment as a {job} and earned {amount_phrase}.",
    "You came through during the busiest hour as a {job} and earned {amount_phrase}.",
    "You kept everything moving as a {job} and earned {amount_phrase}.",
    "You picked up a premium shift as a {job} and earned {amount_phrase}.",
    "You handled a flood of requests as a {job} and earned {amount_phrase}.",
    "You locked in for a focused shift as a {job} and earned {amount_phrase}.",
    "You kept the pace steady as a {job} and earned {amount_phrase}.",
    "You finished a demanding route as a {job} and earned {amount_phrase}.",
    "You cleaned up a rough schedule as a {job} and earned {amount_phrase}.",
    "You worked a twilight shift as a {job} and earned {amount_phrase}.",
    "You crossed a long checklist as a {job} and earned {amount_phrase}.",
    "You took care of an overflow shift as a {job} and earned {amount_phrase}.",
    "You solved a stubborn problem as a {job} and earned {amount_phrase}.",
    "You kept a high-pressure shift balanced as a {job} and earned {amount_phrase}.",
    "You handled the fine details as a {job} and earned {amount_phrase}.",
    "You worked through a packed schedule as a {job} and earned {amount_phrase}.",
    "You stepped up for a priority order as a {job} and earned {amount_phrase}.",
    "You carried a high-volume shift as a {job} and earned {amount_phrase}.",
    "You handled a late callout as a {job} and earned {amount_phrase}.",
    "You kept quality high through a long shift as a {job} and earned {amount_phrase}.",
    "You managed a difficult run as a {job} and earned {amount_phrase}.",
    "You put in a clean evening shift as a {job} and earned {amount_phrase}.",
    "You kept everything on time as a {job} and earned {amount_phrase}.",
    "You handled a stack of priority work as a {job} and earned {amount_phrase}.",
    "You steadied a chaotic shift as a {job} and earned {amount_phrase}.",
    "You did a precision-heavy run as a {job} and earned {amount_phrase}.",
    "You picked up a demanding assignment as a {job} and earned {amount_phrase}.",
    "You worked the busiest part of the day as a {job} and earned {amount_phrase}.",
    "You carried a full shift without slipping as a {job} and earned {amount_phrase}.",
    "You finished the kind of shift people complain about as a {job} and earned {amount_phrase}.",
    "You stayed reliable under pressure as a {job} and earned {amount_phrase}.",
    "You kept things running when it mattered most as a {job} and earned {amount_phrase}.",
    "You delivered a polished shift as a {job} and earned {amount_phrase}.",
    "You handled a sharp, fast-paced shift as a {job} and earned {amount_phrase}.",
    "You made a demanding day look easy as a {job} and earned {amount_phrase}.",
)


def _utcnow() -> dt.datetime:
    return discord.utils.utcnow()


def _normalize_lookup(value: str) -> str:
    cleaned = (value or "").strip().lower().replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def _normalize_guess_text(value: str) -> str:
    cleaned = (value or "").strip().lower()
    cleaned = cleaned.translate(str.maketrans("", "", string.punctuation))
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _looks_turkish_text(text: str) -> bool:
    lowered = (text or "").lower()
    if any(char in lowered for char in "çğıöşüı"):
        return True
    return any(word in lowered for word in (" bir ", " ve ", " için ", " şu ", "şu ", " gibi ", " ama ", "veya"))


def _format_relative_seconds(seconds: float) -> str:
    remaining = max(0, int(seconds))
    hours, remainder = divmod(remaining, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def _display_name(user: discord.abc.User) -> str:
    for attr in ("display_name", "global_name", "name"):
        value = getattr(user, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Unknown User"


def _format_coin_reward(amount: int) -> str:
    return f"**{int(amount)} coins**"


def _chunk_lines(lines: list[str], *, max_lines: int = 7) -> list[list[str]]:
    return [lines[index:index + max_lines] for index in range(0, len(lines), max_lines)]


def _category_emoji(category: str) -> str:
    return CATEGORY_EMOJIS.get(category, "🛍️")


def _item_emoji(item_name: str) -> str:
    return ITEM_EMOJIS.get(item_name, "🛒")


def page_key_to_title(category_key: str) -> str:
    mapping = {
        "playback": "Playback",
        "filters": "Filters",
        "history": "History",
        "minigame": "Minigame",
        "moderation": "Moderation",
        "profile_xp": "Profile / XP",
        "avatar_tools": "Avatar Tools",
        "text_tools": "Text Tools",
    }
    return mapping.get(category_key, "Help")


class HelpCategoryButton(discord.ui.Button):
    def __init__(self, *, label: str, category_key: str, selected: bool, row: int) -> None:
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary if selected else discord.ButtonStyle.secondary,
            row=row,
        )
        self.category_key = category_key

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, HelpMenuView):
            await view.open_category(interaction, self.category_key)


class HelpMenuView(discord.ui.View):
    def __init__(
        self,
        *,
        cog: "Community",
        author_id: int,
        categories: list[tuple[str, str]],
    ) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.author_id = author_id
        self.categories = categories
        self.current_category: Optional[str] = None
        self.message: Optional[discord.Message] = None
        self._rebuild_buttons()

    def bind_message(self, message: discord.Message) -> None:
        self.message = message

    def _rebuild_buttons(self) -> None:
        self.clear_items()
        for index, (category_key, label) in enumerate(self.categories):
            self.add_item(
                HelpCategoryButton(
                    label=label,
                    category_key=category_key,
                    selected=self.current_category == category_key,
                    row=index // 4,
                )
            )
        nav_row = max(2, len(self.categories) // 4 + 1)
        if self.current_category is not None:
            self.add_item(
                HelpCategoryButton(
                    label="◀ Back",
                    category_key="__home__",
                    selected=False,
                    row=nav_row,
                )
            )
        self.add_item(
            HelpCategoryButton(
                label="⌂ Home",
                category_key="__home__",
                selected=self.current_category is None,
                row=nav_row,
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "This help menu belongs to the original requester.",
            ephemeral=True,
        )
        return False

    async def open_category(self, interaction: discord.Interaction, category_key: str) -> None:
        self.current_category = None if category_key == "__home__" else category_key
        self._rebuild_buttons()
        embed = self.cog.build_help_embed(self.current_category)
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)


class ShopCategoryButton(discord.ui.Button):
    def __init__(self, *, label: str, category_key: str, selected: bool, row: int) -> None:
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary if selected else discord.ButtonStyle.secondary,
            row=row,
        )
        self.category_key = category_key

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, ShopMenuView):
            await view.open_category(interaction, self.category_key)


class ShopMenuView(discord.ui.View):
    def __init__(
        self,
        *,
        cog: "Community",
        author_id: int,
        categories: list[str],
    ) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.author_id = author_id
        self.categories = categories
        self.current_category: Optional[str] = None
        self.message: Optional[discord.Message] = None
        self._rebuild_buttons()

    def bind_message(self, message: discord.Message) -> None:
        self.message = message

    def _rebuild_buttons(self) -> None:
        self.clear_items()
        for index, category in enumerate(self.categories):
            emoji = _category_emoji(category)
            self.add_item(
                ShopCategoryButton(
                    label=f"{emoji} {category}",
                    category_key=category,
                    selected=self.current_category == category,
                    row=index // 4,
                )
            )
        home_row = max(1, len(self.categories) // 4)
        self.add_item(
            ShopCategoryButton(
                label="Home",
                category_key="__home__",
                selected=self.current_category is None,
                row=home_row,
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "This shop menu belongs to the original requester.",
            ephemeral=True,
        )
        return False

    async def open_category(self, interaction: discord.Interaction, category_key: str) -> None:
        self.current_category = None if category_key == "__home__" else category_key
        self._rebuild_buttons()
        embed = self.cog.build_shop_embed(self.current_category)
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)


class ShopViewCategoryButton(discord.ui.Button):
    def __init__(self, *, label: str, category_key: str, selected: bool, row: int) -> None:
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary if selected else discord.ButtonStyle.secondary,
            row=row,
        )
        self.category_key = category_key

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, ShopViewMenu):
            await view.open_category(interaction, self.category_key)


class ShopViewActionButton(discord.ui.Button):
    def __init__(self, *, label: str, action_key: str, disabled: bool, row: int) -> None:
        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            row=row,
            disabled=disabled,
        )
        self.action_key = action_key

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, ShopViewMenu):
            await view.handle_action(interaction, self.action_key)


class ShopViewMenu(discord.ui.View):
    def __init__(
        self,
        *,
        cog: "Community",
        author_id: int,
        categories: list[str],
    ) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.author_id = author_id
        self.categories = categories
        self.current_category: Optional[str] = None
        self.current_page: int = 0
        self.message: Optional[discord.Message] = None
        self._rebuild_buttons()

    def bind_message(self, message: discord.Message) -> None:
        self.message = message

    def _current_page_count(self) -> int:
        if self.current_category is None:
            return 1
        return self.cog._shopview_page_count(self.current_category)

    def _rebuild_buttons(self) -> None:
        self.clear_items()
        for index, category in enumerate(self.categories):
            emoji = _category_emoji(category)
            self.add_item(
                ShopViewCategoryButton(
                    label=f"{emoji} {category}",
                    category_key=category,
                    selected=self.current_category == category,
                    row=index // 4,
                )
            )
        nav_row = max(2, len(self.categories) // 4 + 1)
        self.add_item(
            ShopViewActionButton(
                label="Prev",
                action_key="prev",
                disabled=self.current_category is None or self.current_page <= 0,
                row=nav_row,
            )
        )
        self.add_item(
            ShopViewActionButton(
                label="Home",
                action_key="home",
                disabled=self.current_category is None,
                row=nav_row,
            )
        )
        self.add_item(
            ShopViewActionButton(
                label="Next",
                action_key="next",
                disabled=self.current_category is None or self.current_page >= self._current_page_count() - 1,
                row=nav_row,
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "This shop view belongs to the original requester.",
            ephemeral=True,
        )
        return False

    async def open_category(self, interaction: discord.Interaction, category_key: str) -> None:
        self.current_category = category_key
        self.current_page = 0
        self._rebuild_buttons()
        embed = self.cog.build_shopview_embed(category=category_key, page=self.current_page)
        await interaction.response.edit_message(embed=embed, view=self)

    async def handle_action(self, interaction: discord.Interaction, action_key: str) -> None:
        if action_key == "home":
            self.current_category = None
            self.current_page = 0
        elif action_key == "prev" and self.current_category is not None:
            self.current_page = max(0, self.current_page - 1)
        elif action_key == "next" and self.current_category is not None:
            self.current_page = min(self._current_page_count() - 1, self.current_page + 1)
        self._rebuild_buttons()
        embed = self.cog.build_shopview_embed(category=self.current_category, page=self.current_page)
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)


class QuickEarnButton(discord.ui.Button):
    def __init__(self, *, action_key: str, label: str, emoji: str, row: int) -> None:
        super().__init__(
            label=label,
            emoji=emoji,
            style=discord.ButtonStyle.secondary,
            row=row,
        )
        self.action_key = action_key

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, QuickEarnView):
            await view.trigger_action(interaction, self.action_key)


class QuickEarnView(discord.ui.View):
    def __init__(
        self,
        *,
        cog: "Community",
        author_id: int,
        source_message: discord.Message,
    ) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.author_id = author_id
        self.source_message = source_message
        self.message: Optional[discord.Message] = None
        self.last_action: Optional[str] = None
        self.last_result: Optional[str] = None
        self._busy = False
        for index, action in enumerate(QUICK_EARN_ACTIONS):
            self.add_item(
                QuickEarnButton(
                    action_key=action["key"],
                    label=action["label"],
                    emoji=action["emoji"],
                    row=index // 4,
                )
            )

    def bind_message(self, message: discord.Message) -> None:
        self.message = message

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "This earn panel belongs to the original requester.",
            ephemeral=True,
        )
        return False

    async def trigger_action(self, interaction: discord.Interaction, action_key: str) -> None:
        if self._busy:
            await interaction.response.send_message(
                "That earn panel is already processing an action. Give it a moment.",
                ephemeral=True,
            )
            return
        self._busy = True
        try:
            await interaction.response.defer()
            try:
                result = await self.cog._dispatch_quick_earn_action(self.source_message, action_key)
            except Exception:
                logger.exception("Quick earn action failed for action=%s user=%s", action_key, self.author_id)
                result = "Action failed"
                with contextlib.suppress(discord.HTTPException):
                    await interaction.followup.send(
                        "That earning action failed unexpectedly. Nothing was paid out twice.",
                        ephemeral=True,
                    )
            action_meta = next((entry for entry in QUICK_EARN_ACTIONS if entry["key"] == action_key), None)
            action_label = action_meta["label"] if action_meta else action_key.title()
            self.last_action = action_label
            self.last_result = result
            if self.message is not None:
                with contextlib.suppress(discord.HTTPException):
                    await self.message.edit(embed=self.cog._build_quick_earn_embed(last_action=self.last_action, last_result=self.last_result), view=self)
        finally:
            self._busy = False

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)


class TriviaAnswerButton(discord.ui.Button):
    def __init__(self, *, option_index: int, label: str, row: int) -> None:
        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            row=row,
        )
        self.option_index = option_index

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, TriviaQuestionView):
            await view.submit_answer(interaction, self.option_index)


class TriviaQuestionView(discord.ui.View):
    def __init__(self, *, cog: "Community", session: TriviaSession) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.session = session
        for option_index, label in enumerate(("A", "B", "C", "D")):
            self.add_item(TriviaAnswerButton(option_index=option_index, label=label, row=0 if option_index < 2 else 1))

    def bind_message(self, message: discord.Message) -> None:
        self.session.message = message

    def disable_all(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    async def submit_answer(self, interaction: discord.Interaction, option_index: int) -> None:
        async with self.session.lock:
            if self.session.resolved or self.session.current_question is None:
                await interaction.response.send_message("This trivia round has already ended.", ephemeral=True)
                return
            if self.session.question_resolved:
                await interaction.response.send_message("This question is already resolved. The next one is loading.", ephemeral=True)
                return
            if interaction.user.id in self.session.answered_user_ids:
                await interaction.response.send_message("You already answered this trivia question.", ephemeral=True)
                return
            self.session.last_activity_at = time.monotonic()
            question = self.session.current_question
            if option_index != question.correct_index:
                self.session.answered_user_ids.add(interaction.user.id)
                await interaction.response.send_message("Wrong answer. Someone else can still steal this one.", ephemeral=True)
                return
            reward_coins, reward_xp = self.cog._trivia_rewards_for_difficulty(question.difficulty)
            payout_result = await self.cog._run_db(
                self.cog._settle_blackjack_payout_sync,
                self.session.guild_id,
                interaction.user.id,
                _display_name(interaction.user),
                reward_coins,
            )
            await self.cog._grant_profile_xp(
                guild_id=self.session.guild_id,
                user=interaction.user,
                amount=reward_xp,
            )
            self.session.question_resolved = True
            self.session.result_note = (
                f"**{_display_name(interaction.user)}** answered correctly.\n"
                f"Correct answer: **{question.correct_answer}**"
            )
            self.session.payout_amount = reward_coins if payout_result.get("status") == "success" else 0
            self.session.xp_reward = reward_xp
            self.session.winner_id = interaction.user.id
            self.disable_all()
            self.cog._cancel_session_task(self.session.question_task)
            self.session.question_task = None
            await interaction.response.edit_message(
                embed=self.cog._build_trivia_embed(self.session, state="correct"),
                view=self,
            )
            self.stop()
            self.session.advance_task = self.cog._track_session_task(
                asyncio.create_task(self.cog._advance_trivia_after_delay(self.session))
            )


class BlackjackView(discord.ui.View):
    def __init__(self, *, cog: "Community", session: BlackjackSession, author_id: int) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.session = session
        self.author_id = author_id

    def bind_message(self, message: discord.Message) -> None:
        self.session.message = message

    def _sync_buttons(self) -> None:
        self.hit_button.disabled = self.session.resolved
        self.stand_button.disabled = self.session.resolved
        self.double_button.disabled = self.session.resolved or self.session.doubled or len(self.session.player_hand) != 2

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "This blackjack hand belongs to the original player.",
            ephemeral=True,
        )
        return False

    async def _refresh_message(self, interaction: discord.Interaction, *, note: Optional[str] = None, reveal_dealer: bool = False) -> None:
        self._sync_buttons()
        embed = self.cog._build_blackjack_embed(self.session, note=note, reveal_dealer=reveal_dealer or self.session.resolved)
        if interaction.response.is_done():
            with contextlib.suppress(discord.HTTPException):
                await interaction.message.edit(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)
        if self.session.resolved:
            self.stop()

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary, row=0)
    async def hit_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.session.lock:
            if self.session.resolved:
                await self._refresh_message(interaction, reveal_dealer=True)
                return
            self.cog._blackjack_draw(self.session.player_hand, self.session.deck)
            player_total = self.cog._blackjack_hand_value(self.session.player_hand)
            if player_total > 21:
                await self.cog._finish_blackjack_session(
                    self.session,
                    outcome="loss",
                    note=f"You drew one card too many and busted at **{player_total}**.",
                )
            await self._refresh_message(
                interaction,
                note=None if not self.session.resolved else f"You busted with **{player_total}**.",
                reveal_dealer=self.session.resolved,
            )

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, row=0)
    async def stand_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.session.lock:
            if not self.session.resolved:
                await self.cog._resolve_blackjack_dealer(self.session)
            await self._refresh_message(interaction, note=self.cog._blackjack_result_note(self.session), reveal_dealer=True)

    @discord.ui.button(label="Double Down", style=discord.ButtonStyle.success, row=0)
    async def double_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.session.lock:
            if self.session.resolved:
                await self._refresh_message(interaction, reveal_dealer=True)
                return
            result = await self.cog._run_db(
                self.cog._reserve_blackjack_extra_sync,
                self.session.guild_id,
                self.session.user_id,
                self.session.display_name,
                self.session.original_bet,
            )
            if result["status"] != "success":
                await interaction.response.send_message(
                    "You do not have enough coins to double down on this hand.",
                    ephemeral=True,
                )
                return
            self.session.bet += self.session.original_bet
            self.session.doubled = True
            self.cog._blackjack_draw(self.session.player_hand, self.session.deck)
            player_total = self.cog._blackjack_hand_value(self.session.player_hand)
            if player_total > 21:
                await self.cog._finish_blackjack_session(
                    self.session,
                    outcome="loss",
                    note=f"You doubled down and busted at **{player_total}**.",
                )
            else:
                await self.cog._resolve_blackjack_dealer(self.session)
            await self._refresh_message(interaction, note=self.cog._blackjack_result_note(self.session), reveal_dealer=True)

    async def on_timeout(self) -> None:
        async with self.session.lock:
            if not self.session.resolved:
                await self.cog._resolve_blackjack_dealer(
                    self.session,
                    timeout_note="Time ran out, so the hand was played out as a stand.",
                )
            self._sync_buttons()
            if self.session.message is not None:
                with contextlib.suppress(discord.HTTPException):
                    await self.session.message.edit(
                        embed=self.cog._build_blackjack_embed(
                            self.session,
                            note=self.cog._blackjack_result_note(self.session),
                            reveal_dealer=True,
                        ),
                        view=self,
                    )


class MultiplayerBlackjackChallengeView(discord.ui.View):
    def __init__(self, *, cog: "Community", session: MultiplayerBlackjackSession, author_id: int) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.session = session
        self.author_id = author_id

    def bind_message(self, message: discord.Message) -> None:
        self.session.message = message

    def _sync_buttons(self) -> None:
        resolved = self.session.resolved or self.session.accepted
        self.accept_button.disabled = resolved
        self.decline_button.disabled = resolved

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id in {self.session.challenger_id, self.session.target_id}:
            return True
        await interaction.response.send_message(
            "This blackjack table belongs to the two selected players.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, row=0)
    async def accept_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.session.lock:
            if interaction.user.id != self.session.target_id:
                await interaction.response.send_message(
                    "Only the challenged player can accept this blackjack table.",
                    ephemeral=True,
                )
                return
            if self.session.resolved or self.session.accepted:
                await interaction.response.send_message("This blackjack table is already resolved.", ephemeral=True)
                return
            start_result = await self.cog._start_multiplayer_blackjack(self.session)
            if start_result["status"] != "success":
                await interaction.response.edit_message(embed=self.cog._build_multiplayer_blackjack_embed(self.session), view=self)
                self.stop()
                return
            game_view = MultiplayerBlackjackView(cog=self.cog, session=self.session)
            self._sync_buttons()
            await interaction.response.edit_message(embed=self.cog._build_multiplayer_blackjack_embed(self.session), view=game_view)
            if self.session.message is not None:
                game_view.bind_message(self.session.message)
            self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.secondary, row=0)
    async def decline_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.session.lock:
            if interaction.user.id != self.session.target_id:
                await interaction.response.send_message(
                    "Only the challenged player can decline this blackjack table.",
                    ephemeral=True,
                )
                return
            if self.session.resolved:
                await interaction.response.send_message("This blackjack table is already resolved.", ephemeral=True)
                return
            self.session.resolved = True
            self.session.result_note = f"{self.session.target_name} declined the blackjack challenge."
            self.cog._close_multiplayer_blackjack_session(self.session)
            self._sync_buttons()
            await interaction.response.edit_message(embed=self.cog._build_multiplayer_blackjack_embed(self.session), view=self)
            self.stop()

    async def on_timeout(self) -> None:
        async with self.session.lock:
            if not self.session.resolved and not self.session.accepted:
                self.session.resolved = True
                self.session.result_note = "The blackjack invitation expired before it was accepted."
                self.cog._close_multiplayer_blackjack_session(self.session)
            self._sync_buttons()
            if self.session.message is not None:
                with contextlib.suppress(discord.HTTPException):
                    await self.session.message.edit(embed=self.cog._build_multiplayer_blackjack_embed(self.session), view=self)


class MultiplayerBlackjackView(discord.ui.View):
    def __init__(self, *, cog: "Community", session: MultiplayerBlackjackSession) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.session = session
        self._sync_buttons()

    def bind_message(self, message: discord.Message) -> None:
        self.session.message = message

    def _sync_buttons(self) -> None:
        disabled = self.session.resolved or not self.session.accepted
        self.hit_button.disabled = disabled
        self.stand_button.disabled = disabled

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id in {self.session.challenger_id, self.session.target_id}:
            return True
        await interaction.response.send_message(
            "This blackjack table belongs to the two active players.",
            ephemeral=True,
        )
        return False

    async def _handle_turn_action(self, interaction: discord.Interaction, action: str) -> None:
        async with self.session.lock:
            if self.session.resolved:
                await interaction.response.send_message("This blackjack table is already settled.", ephemeral=True)
                return
            if interaction.user.id != self.session.current_player_id:
                current_name = self.cog._multiplayer_blackjack_player_name(self.session, self.session.current_player_id)
                await interaction.response.send_message(
                    f"It is currently **{current_name}**'s turn.",
                    ephemeral=True,
                )
                return
            note = await self.cog._apply_multiplayer_blackjack_action(self.session, interaction.user.id, action)
            self._sync_buttons()
            await interaction.response.edit_message(
                embed=self.cog._build_multiplayer_blackjack_embed(self.session, note=note),
                view=self,
            )
            if self.session.resolved:
                self.stop()

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary, row=0)
    async def hit_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._handle_turn_action(interaction, "hit")

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, row=0)
    async def stand_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._handle_turn_action(interaction, "stand")

    async def on_timeout(self) -> None:
        async with self.session.lock:
            if not self.session.resolved:
                await self.cog._refund_multiplayer_blackjack_session(
                    self.session,
                    note="The multiplayer blackjack table timed out. Both bets were returned.",
                )
            self._sync_buttons()
            if self.session.message is not None:
                with contextlib.suppress(discord.HTTPException):
                    await self.session.message.edit(
                        embed=self.cog._build_multiplayer_blackjack_embed(self.session),
                        view=self,
                    )


class CoinflipView(discord.ui.View):
    def __init__(self, *, cog: "Community", session: CoinflipSession) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.session = session
        self._sync_buttons()

    def bind_message(self, message: discord.Message) -> None:
        self.session.message = message

    def _sync_buttons(self) -> None:
        locked_side = self.session.side_choice is not None or self.session.resolved
        self.heads_button.disabled = locked_side
        self.tails_button.disabled = locked_side
        self.accept_button.disabled = self.session.accepted or self.session.resolved
        self.decline_button.disabled = self.session.accepted or self.session.resolved

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id in {self.session.challenger_id, self.session.target_id}:
            return True
        await interaction.response.send_message(
            "This coinflip belongs to the two selected players.",
            ephemeral=True,
        )
        return False

    async def _try_resolve(self, interaction: discord.Interaction) -> None:
        if self.session.side_choice is None or not self.session.accepted or self.session.resolved:
            return
        await self.cog._resolve_coinflip_session(self.session)
        self._sync_buttons()
        await interaction.message.edit(embed=self.cog._build_coinflip_embed(self.session), view=self)
        self.stop()

    @discord.ui.button(label="Heads", emoji="🪙", style=discord.ButtonStyle.primary, row=0)
    async def heads_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.session.lock:
            if interaction.user.id != self.session.challenger_id:
                await interaction.response.send_message("Only the challenger chooses heads or tails.", ephemeral=True)
                return
            self.session.side_choice = "heads"
            self.session.result_note = f"{self.session.challenger_name} locked in **Heads**."
            self._sync_buttons()
            await interaction.response.edit_message(embed=self.cog._build_coinflip_embed(self.session), view=self)
            await self._try_resolve(interaction)

    @discord.ui.button(label="Tails", emoji="🪙", style=discord.ButtonStyle.secondary, row=0)
    async def tails_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.session.lock:
            if interaction.user.id != self.session.challenger_id:
                await interaction.response.send_message("Only the challenger chooses heads or tails.", ephemeral=True)
                return
            self.session.side_choice = "tails"
            self.session.result_note = f"{self.session.challenger_name} locked in **Tails**."
            self._sync_buttons()
            await interaction.response.edit_message(embed=self.cog._build_coinflip_embed(self.session), view=self)
            await self._try_resolve(interaction)

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, row=1)
    async def accept_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.session.lock:
            if interaction.user.id != self.session.target_id:
                await interaction.response.send_message("Only the challenged player can accept this coinflip.", ephemeral=True)
                return
            if self.session.resolved:
                await interaction.response.send_message("This coinflip is already settled.", ephemeral=True)
                return
            reserve_result = await self.cog._run_db(
                self.cog._reserve_duel_bets_sync,
                self.session.guild_id,
                self.session.challenger_id,
                self.session.challenger_name,
                self.session.target_id,
                self.session.target_name,
                self.session.bet,
            )
            if reserve_result["status"] != "success":
                self.session.resolved = True
                if reserve_result["status"] == "challenger_insufficient":
                    self.session.result_note = f"{self.session.challenger_name} no longer has enough coins for the coinflip."
                elif reserve_result["status"] == "target_insufficient":
                    self.session.result_note = f"{self.session.target_name} does not have enough coins to match the bet."
                else:
                    self.session.result_note = "The coinflip could not lock both bets right now."
                self.cog._close_coinflip_session(self.session)
                self._sync_buttons()
                await interaction.response.edit_message(embed=self.cog._build_coinflip_embed(self.session), view=self)
                self.stop()
                return
            self.session.accepted = True
            self.session.result_note = f"{self.session.target_name} accepted the coinflip. Waiting for the call..."
            self._sync_buttons()
            await interaction.response.edit_message(embed=self.cog._build_coinflip_embed(self.session), view=self)
            await self._try_resolve(interaction)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, row=1)
    async def decline_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.session.lock:
            if interaction.user.id != self.session.target_id:
                await interaction.response.send_message("Only the challenged player can decline this coinflip.", ephemeral=True)
                return
            self.session.resolved = True
            self.session.result_note = f"{self.session.target_name} declined the coinflip."
            self.cog._close_coinflip_session(self.session)
            self._sync_buttons()
            await interaction.response.edit_message(embed=self.cog._build_coinflip_embed(self.session), view=self)
            self.stop()

    async def on_timeout(self) -> None:
        async with self.session.lock:
            if not self.session.resolved:
                if self.session.accepted:
                    await self.cog._refund_coinflip_session(
                        self.session,
                        note="The coinflip timed out. Both bets were returned.",
                    )
                else:
                    self.session.resolved = True
                    self.session.result_note = "The coinflip invitation expired."
                    self.cog._close_coinflip_session(self.session)
            self._sync_buttons()
            if self.session.message is not None:
                with contextlib.suppress(discord.HTTPException):
                    await self.session.message.edit(embed=self.cog._build_coinflip_embed(self.session), view=self)


class CrashView(discord.ui.View):
    def __init__(self, *, cog: "Community", session: CrashSession, author_id: int) -> None:
        super().__init__(timeout=CRASH_VIEW_TIMEOUT_SECONDS)
        self.cog = cog
        self.session = session
        self.author_id = author_id
        self.timed_out = False

    def bind_message(self, message: discord.Message) -> None:
        self.session.message = message

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "This crash round belongs to the original player.",
            ephemeral=True,
        )
        return False

    def _sync_buttons(self) -> None:
        self.cashout_button.disabled = self.session.resolved or self.timed_out

    async def refresh(self, interaction: Optional[discord.Interaction] = None) -> None:
        self._sync_buttons()
        embed = self.cog._build_crash_embed(self.session)
        if interaction is None:
            if self.session.message is not None:
                with contextlib.suppress(discord.HTTPException):
                    await self.session.message.edit(embed=embed, view=self)
            return
        if interaction.response.is_done():
            with contextlib.suppress(discord.HTTPException):
                await interaction.message.edit(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)
        if self.session.resolved:
            self.stop()

    @discord.ui.button(label="Cash Out", style=discord.ButtonStyle.success, row=0)
    async def cashout_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.session.lock:
            if self.session.resolved:
                await self.refresh(interaction)
                return
            payout = self.cog._calculate_crash_payout(self.session)
            payout_result = await self.cog._run_db(
                self.cog._settle_blackjack_payout_sync,
                self.session.guild_id,
                self.session.user_id,
                self.session.display_name,
                payout,
            )
            wallet_after = payout_result.get("wallet") if payout_result.get("status") == "success" else None
            self.session.resolved = True
            self.session.cashed_out = True
            self.session.payout_amount = payout
            self.session.wallet_after = wallet_after
            self.session.trend_label = "Cashed out cleanly"
            self.session.result_note = f"You cashed out at **x{self.session.current_multiplier:.2f}** and banked the run safely."
            self.cog._crash_sessions.pop(self.cog._blackjack_session_key(self.session.guild_id, self.session.user_id), None)
            await self.cog._run_db(
                self.cog._record_crash_result_sync,
                self.session.guild_id,
                self.session.user_id,
                self.session.display_name,
                True,
                payout,
            )
            await self.refresh(interaction)

    async def on_timeout(self) -> None:
        self.timed_out = True
        self.cashout_button.disabled = True
        if self.session.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.session.message.edit(embed=self.cog._build_crash_embed(self.session), view=self)


class DuelView(discord.ui.View):
    def __init__(self, *, cog: "Community", session: DuelSession) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.session = session

    def bind_message(self, message: discord.Message) -> None:
        self.session.message = message

    def _sync_buttons(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = self.session.resolved

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id in {self.session.challenger_id, self.session.target_id}:
            return True
        await interaction.response.send_message(
            "This duel belongs to the two selected players.",
            ephemeral=True,
        )
        return False

    async def _register_choice(self, interaction: discord.Interaction, choice: str) -> None:
        async with self.session.lock:
            if self.session.resolved:
                await interaction.response.send_message("This duel is already over.", ephemeral=True)
                return
            if interaction.user.id == self.session.challenger_id:
                self.session.challenger_choice = choice
            elif interaction.user.id == self.session.target_id:
                self.session.target_choice = choice
            await interaction.response.send_message(f"You locked in **{choice.title()}**.", ephemeral=True)
            if self.session.challenger_choice and self.session.target_choice:
                await self.cog._resolve_duel_round(self.session)
                self._sync_buttons()
                if self.session.message is not None:
                    with contextlib.suppress(discord.HTTPException):
                        await self.session.message.edit(embed=self.cog._build_duel_embed(self.session), view=self)
                if self.session.resolved:
                    self.stop()
            else:
                if self.session.message is not None:
                    with contextlib.suppress(discord.HTTPException):
                        await self.session.message.edit(embed=self.cog._build_duel_embed(self.session), view=self)

    @discord.ui.button(label="Rock", style=discord.ButtonStyle.secondary, row=0)
    async def rock_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._register_choice(interaction, "rock")

    @discord.ui.button(label="Paper", style=discord.ButtonStyle.primary, row=0)
    async def paper_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._register_choice(interaction, "paper")

    @discord.ui.button(label="Scissors", style=discord.ButtonStyle.success, row=0)
    async def scissors_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._register_choice(interaction, "scissors")

    async def on_timeout(self) -> None:
        async with self.session.lock:
            if not self.session.resolved:
                await self.cog._refund_duel_session(self.session, note="The duel timed out before it could finish. Both wagers were returned.")
            self._sync_buttons()
            if self.session.message is not None:
                with contextlib.suppress(discord.HTTPException):
                    await self.session.message.edit(embed=self.cog._build_duel_embed(self.session), view=self)


class DungeonFighterView(discord.ui.View):
    def __init__(self, *, cog: "Community", session: DungeonSession, author_id: int) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.session = session
        self.author_id = author_id

    def bind_message(self, message: discord.Message) -> None:
        self.session.message = message

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message("This dungeon run belongs to the original player.", ephemeral=True)
        return False

    async def _pick_fighter(self, interaction: discord.Interaction, fighter_key: str) -> None:
        async with self.session.lock:
            if self.session.resolved:
                await interaction.response.send_message("This dungeon run is already over.", ephemeral=True)
                return
            self.session.fighter_key = fighter_key
            self.session.enemy_name = self.cog._pick_dungeon_enemy(self.session.level)
            run_view = DungeonRunView(cog=self.cog, session=self.session, author_id=self.author_id)
            if interaction.response.is_done():
                with contextlib.suppress(discord.HTTPException):
                    await interaction.message.edit(embed=self.cog._build_dungeon_embed(self.session), view=run_view)
            else:
                await interaction.response.edit_message(embed=self.cog._build_dungeon_embed(self.session), view=run_view)
            if self.session.message is not None:
                run_view.bind_message(self.session.message)
            self.stop()

    @discord.ui.button(label="Rookie \U0001F9DB", style=discord.ButtonStyle.primary, row=0)
    async def rookie_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._pick_fighter(interaction, "rookie")

    @discord.ui.button(label="FighterJit \U0001F984", style=discord.ButtonStyle.success, row=0)
    async def fighterjit_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._pick_fighter(interaction, "fighterjit")

    async def on_timeout(self) -> None:
        async with self.session.lock:
            if not self.session.resolved and self.session.fighter_key is None:
                await self.cog._refund_dungeon_session(self.session, note="The fighter selection timed out. Your bet was returned safely.")
            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            if self.session.message is not None:
                with contextlib.suppress(discord.HTTPException):
                    await self.session.message.edit(embed=self.cog._build_dungeon_embed(self.session), view=self)


class DungeonRunView(discord.ui.View):
    def __init__(self, *, cog: "Community", session: DungeonSession, author_id: int) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.session = session
        self.author_id = author_id
        self._sync_buttons()

    def bind_message(self, message: discord.Message) -> None:
        self.session.message = message

    def _sync_buttons(self) -> None:
        self.attack_button.disabled = self.session.resolved
        self.leave_button.disabled = self.session.resolved
        self.buy_life_button.disabled = self.session.resolved or self.session.life_charges >= DUNGEON_LIFE_MAX
        companion_locked = self.session.resolved or self.session.companion_key is not None
        self.fighterseal_button.disabled = companion_locked
        self.kelpy_button.disabled = companion_locked
        self.thibeault_button.disabled = companion_locked
        self.kamil_button.disabled = companion_locked
        self.batman_button.disabled = companion_locked
        self.hessa_king_button.disabled = companion_locked

    async def _activate_companion(self, interaction: discord.Interaction, companion_key: str) -> None:
        async with self.session.lock:
            if self.session.resolved:
                await interaction.response.send_message("This dungeon run has already ended.", ephemeral=True)
                return
            if self.session.companion_key is not None:
                active_companion = self.cog._get_dungeon_companion(self.session.companion_key)
                active_name = str(active_companion.get("name") or "A companion") if active_companion else "A companion"
                await interaction.response.send_message(
                    f"{active_name} is already accompanying this run.",
                    ephemeral=True,
                )
                return
            companion = self.cog._get_dungeon_companion(companion_key)
            if not companion:
                await interaction.response.send_message("That companion could not be called right now.", ephemeral=True)
                return
            result = await self.cog._run_db(
                self.cog._buy_dungeon_companion_sync,
                self.session.guild_id,
                self.session.user_id,
                self.session.display_name,
                companion_key,
            )
            if result["status"] == "insufficient":
                await interaction.response.send_message(
                    f"You need **{int(companion['cost'])} coins** to call {companion['name']}.\n"
                    f"Wallet: **{int(result['wallet'])} coins**",
                    ephemeral=True,
                )
                return
            if result["status"] != "success":
                await interaction.response.send_message(
                    f"{companion['name']} could not join your run right now.",
                    ephemeral=True,
                )
                return
            self.session.companion_key = str(companion["key"])
            self.session.result_note = (
                f"{companion['activation_text']}\n"
                f"Companion bonus: **+{int(round(float(companion['bonus']) * 100))}% win chance** for this run."
            )
            self._sync_buttons()
            await interaction.response.edit_message(embed=self.cog._build_dungeon_embed(self.session), view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message("This dungeon run belongs to the original player.", ephemeral=True)
        return False

    @discord.ui.button(label="Attack", style=discord.ButtonStyle.danger, row=0)
    async def attack_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.session.lock:
            if self.session.resolved:
                await interaction.response.send_message("This dungeon run has already ended.", ephemeral=True)
                return
            await self.cog._resolve_dungeon_attack(self.session)
            if self.session.awaiting_ancient_choice and not self.session.resolved:
                invite_view = AncientDungeonInviteView(cog=self.cog, session=self.session, author_id=self.author_id)
                if interaction.response.is_done():
                    with contextlib.suppress(discord.HTTPException):
                        await interaction.message.edit(embed=self.cog._build_dungeon_embed(self.session), view=invite_view)
                else:
                    await interaction.response.edit_message(embed=self.cog._build_dungeon_embed(self.session), view=invite_view)
                if self.session.message is not None:
                    invite_view.bind_message(self.session.message)
                self.stop()
                return
            self._sync_buttons()
            if interaction.response.is_done():
                with contextlib.suppress(discord.HTTPException):
                    await interaction.message.edit(embed=self.cog._build_dungeon_embed(self.session), view=self)
            else:
                await interaction.response.edit_message(embed=self.cog._build_dungeon_embed(self.session), view=self)
            if self.session.resolved:
                self.stop()

    @discord.ui.button(label="Leave", style=discord.ButtonStyle.secondary, row=0)
    async def leave_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.session.lock:
            if self.session.resolved:
                await interaction.response.send_message("This dungeon run has already ended.", ephemeral=True)
                return
            await self.cog._leave_dungeon_session(self.session)
            self._sync_buttons()
            if interaction.response.is_done():
                with contextlib.suppress(discord.HTTPException):
                    await interaction.message.edit(embed=self.cog._build_dungeon_embed(self.session), view=self)
            else:
                await interaction.response.edit_message(embed=self.cog._build_dungeon_embed(self.session), view=self)
            self.stop()

    @discord.ui.button(label="+1 Life (150)", style=discord.ButtonStyle.success, row=1)
    async def buy_life_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.session.lock:
            if self.session.resolved:
                await interaction.response.send_message("This dungeon run has already ended.", ephemeral=True)
                return
            result = await self.cog._run_db(
                self.cog._buy_dungeon_life_sync,
                self.session.guild_id,
                self.session.user_id,
                self.session.display_name,
            )
            if result["status"] == "maxed":
                await interaction.response.send_message("You already have the maximum 3 dungeon life charges.", ephemeral=True)
                return
            if result["status"] == "insufficient":
                await interaction.response.send_message(
                    f"You need **{DUNGEON_LIFE_COST} coins** to buy a life charge.\nWallet: **{int(result['wallet'])} coins**",
                    ephemeral=True,
                )
                return
            if result["status"] != "success":
                await interaction.response.send_message("That life charge could not be purchased right now.", ephemeral=True)
                return
            self.session.life_charges = int(result["lives"])
            self.session.result_note = (
                f"You bought **+1 dungeon life** for **{DUNGEON_LIFE_COST} coins**.\n"
                f"Lives: **{self.session.life_charges}/{DUNGEON_LIFE_MAX}**."
            )
            self._sync_buttons()
            await interaction.response.edit_message(embed=self.cog._build_dungeon_embed(self.session), view=self)

    @discord.ui.button(label="FighterSeal (1000)", style=discord.ButtonStyle.primary, row=1)
    async def fighterseal_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._activate_companion(interaction, "fighterseal")

    @discord.ui.button(label="Kelpy (1000)", style=discord.ButtonStyle.primary, row=1)
    async def kelpy_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._activate_companion(interaction, "kelpy")

    @discord.ui.button(label="Thibeault (FisherKing) (1000)", style=discord.ButtonStyle.primary, row=1)
    async def thibeault_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._activate_companion(interaction, "thibeault")

    @discord.ui.button(label="Kamil (2500)", style=discord.ButtonStyle.success, row=2)
    async def kamil_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._activate_companion(interaction, "kamil")

    @discord.ui.button(label="Batman (1000)", style=discord.ButtonStyle.primary, row=2)
    async def batman_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._activate_companion(interaction, "batman")

    @discord.ui.button(label="Hessa King (400)", style=discord.ButtonStyle.secondary, row=2)
    async def hessa_king_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._activate_companion(interaction, "hessa_king")

    async def on_timeout(self) -> None:
        async with self.session.lock:
            if not self.session.resolved:
                await self.cog._fail_dungeon_session(self.session, note="The dungeon run timed out and the floor closed behind you.")
            self._sync_buttons()
            if self.session.message is not None:
                with contextlib.suppress(discord.HTTPException):
                    await self.session.message.edit(embed=self.cog._build_dungeon_embed(self.session), view=self)


class AncientDungeonInviteView(discord.ui.View):
    def __init__(self, *, cog: "Community", session: DungeonSession, author_id: int) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.session = session
        self.author_id = author_id

    def bind_message(self, message: discord.Message) -> None:
        self.session.message = message

    def _disable_buttons(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message("This dungeon run belongs to the original player.", ephemeral=True)
        return False

    @discord.ui.button(label="Enter Ancient Dungeon", style=discord.ButtonStyle.danger, row=0)
    async def enter_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.session.lock:
            if self.session.resolved or not self.session.awaiting_ancient_choice:
                await interaction.response.send_message("That Ancient Dungeon offer is no longer available.", ephemeral=True)
                return
            self.cog._enter_ancient_dungeon(self.session)
            run_view = DungeonRunView(cog=self.cog, session=self.session, author_id=self.author_id)
            if interaction.response.is_done():
                with contextlib.suppress(discord.HTTPException):
                    await interaction.message.edit(embed=self.cog._build_dungeon_embed(self.session), view=run_view)
            else:
                await interaction.response.edit_message(embed=self.cog._build_dungeon_embed(self.session), view=run_view)
            if self.session.message is not None:
                run_view.bind_message(self.session.message)
            self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.secondary, row=0)
    async def decline_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.session.lock:
            if self.session.resolved or not self.session.awaiting_ancient_choice:
                await interaction.response.send_message("That Ancient Dungeon offer is no longer available.", ephemeral=True)
                return
            await self.cog._decline_ancient_dungeon(
                self.session,
                note=(
                    "You kept your normal dungeon payout and declined the Ancient Dungeon.\n"
                    "The run ends here with your reward secured."
                ),
            )
            self._disable_buttons()
            await interaction.response.edit_message(embed=self.cog._build_dungeon_embed(self.session), view=self)
            self.stop()

    async def on_timeout(self) -> None:
        async with self.session.lock:
            if not self.session.resolved and self.session.awaiting_ancient_choice:
                await self.cog._decline_ancient_dungeon(
                    self.session,
                    note=(
                        "The Ancient Dungeon gate closed before you answered.\n"
                        "Your normal dungeon payout remains secured."
                    ),
                )
            self._disable_buttons()
            if self.session.message is not None:
                with contextlib.suppress(discord.HTTPException):
                    await self.session.message.edit(embed=self.cog._build_dungeon_embed(self.session), view=self)


class Community(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.repo_root = Path(__file__).resolve().parents[1]
        self.data_dir = self.repo_root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._quickdraw_cache_path = self.data_dir / "quickdraw_cache.json"
        self._quickdraw_raw_dir = self.data_dir / "quickdraw_raw"
        self._quickdraw_runtime = QuickDrawCacheManager(
            cache_path=self._quickdraw_cache_path,
            fallback_entries=FALLBACK_QUICKDRAW_ENTRIES,
        )
        self._drawgame_loading_channels: set[tuple[int, int]] = set()
        self._profile_xp_path = self.data_dir / PROFILE_XP_FILENAME
        self._economy_db_path = self.data_dir / ECONOMY_DB_FILENAME
        self._profile_lock = asyncio.Lock()
        self._db_lock = asyncio.Lock()
        self._xp_cooldowns: dict[tuple[int, int], float] = {}
        self._blackjack_sessions: dict[tuple[int, int], BlackjackSession] = {}
        self._multiplayer_blackjack_sessions: dict[tuple[int, int], MultiplayerBlackjackSession] = {}
        self._trivia_sessions: dict[tuple[int, int], TriviaSession] = {}
        self._slot_spins: set[tuple[int, int]] = set()
        self._crash_sessions: dict[tuple[int, int], CrashSession] = {}
        self._duel_sessions: dict[tuple[int, int], DuelSession] = {}
        self._coinflip_sessions: dict[tuple[int, int], CoinflipSession] = {}
        self._guess_sessions: dict[tuple[int, int], GuessSession] = {}
        self._drawgame_sessions: dict[tuple[int, int], DrawGameSession] = {}
        self._hangman_sessions: dict[tuple[int, int], HangmanSession] = {}
        self._wordchain_sessions: dict[tuple[int, int], WordChainSession] = {}
        self._dungeon_sessions: dict[tuple[int, int], DungeonSession] = {}
        self._activity_cooldowns: dict[tuple[int, int], float] = {}
        self._reminder_tasks: set[asyncio.Task[Any]] = set()
        self._session_tasks: set[asyncio.Task[Any]] = set()
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._trivia_token: Optional[str] = None
        self._trivia_questions: list[TriviaQuestion] = []
        self._trivia_index: int = 0
        self._trivia_fetch_lock = asyncio.Lock()
        self._started_at = _utcnow()
        self._profile_data = self._load_profile_data_sync()
        self._init_economy_db_sync()

    def _load_profile_data_sync(self) -> dict[str, dict[str, dict[str, Any]]]:
        if not self._profile_xp_path.exists():
            return {}

        try:
            payload = json.loads(self._profile_xp_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to load profile XP data from %s", self._profile_xp_path, exc_info=True)
            return {}

        if not isinstance(payload, dict):
            return {}

        normalized: dict[str, dict[str, dict[str, Any]]] = {}
        for guild_key, guild_entry in payload.items():
            if not isinstance(guild_entry, dict):
                continue
            clean_users: dict[str, dict[str, Any]] = {}
            for user_key, user_entry in guild_entry.items():
                if not isinstance(user_entry, dict):
                    continue
                xp_value = user_entry.get("xp", 0)
                try:
                    xp = max(0, int(xp_value))
                except (TypeError, ValueError):
                    xp = 0
                display_name = user_entry.get("last_display_name")
                clean_users[str(user_key)] = {
                    "xp": xp,
                    "last_display_name": display_name.strip() if isinstance(display_name, str) and display_name.strip() else None,
                }
            if clean_users:
                normalized[str(guild_key)] = clean_users
        return normalized

    def _save_profile_data_sync(self) -> None:
        temp_path = self._profile_xp_path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(self._profile_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self._profile_xp_path)

    async def _save_profile_data(self) -> None:
        await asyncio.to_thread(self._save_profile_data_sync)

    def _ensure_profile_entry(self, guild_id: int, user: discord.abc.User) -> dict[str, Any]:
        guild_bucket = self._profile_data.setdefault(str(guild_id), {})
        return guild_bucket.setdefault(
            str(user.id),
            {
                "xp": 0,
                "last_display_name": _display_name(user),
            },
        )

    def _xp_required_for_level(self, level: int) -> int:
        safe_level = max(1, level)
        return (safe_level - 1) * (safe_level - 1) * 100

    def _level_from_xp(self, xp: int) -> int:
        level = 1
        while xp >= self._xp_required_for_level(level + 1):
            level += 1
        return level

    def _profile_snapshot(
        self,
        *,
        guild: discord.Guild,
        target_user: discord.abc.User,
    ) -> dict[str, Any]:
        entry = self._ensure_profile_entry(guild.id, target_user)
        xp = max(0, int(entry.get("xp", 0)))
        level = self._level_from_xp(xp)
        current_floor = self._xp_required_for_level(level)
        next_level_total = self._xp_required_for_level(level + 1)
        xp_into_level = xp - current_floor
        xp_needed = next_level_total - xp
        guild_profiles = self._profile_data.setdefault(str(guild.id), {})
        ranking = sorted(
            (
                (int(profile.get("xp", 0)), int(user_id))
                for user_id, profile in guild_profiles.items()
            ),
            key=lambda item: (-item[0], item[1]),
        )
        rank_position = next(
            (index for index, (_, user_id) in enumerate(ranking, start=1) if user_id == target_user.id),
            len(ranking) + 1,
        )
        return {
            "xp": xp,
            "level": level,
            "xp_into_level": xp_into_level,
            "xp_needed": xp_needed,
            "xp_next_total": next_level_total,
            "rank_position": rank_position,
        }

    def _build_profile_embed(
        self,
        *,
        guild: discord.Guild,
        target_user: discord.abc.User,
        snapshot: dict[str, Any],
        economy_profile: Optional[dict[str, Any]] = None,
    ) -> discord.Embed:
        display_name = _display_name(target_user)
        embed = discord.Embed(
            title="Cadis Etrama Di Raizel",
            description=f"Profile overview for **{display_name}**.",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Profile / XP")
        avatar = getattr(target_user, "display_avatar", None)
        if avatar:
            embed.set_thumbnail(url=avatar.url)
        embed.add_field(name="Level", value=str(snapshot["level"]), inline=True)
        embed.add_field(name="XP", value=str(snapshot["xp"]), inline=True)
        embed.add_field(name="Server Rank", value=f"#{snapshot['rank_position']}", inline=True)
        embed.add_field(name="Next Level", value=f"{snapshot['xp_needed']} XP needed", inline=False)
        embed.add_field(
            name="Progress",
            value=f"{snapshot['xp_into_level']} / {snapshot['xp_next_total'] - self._xp_required_for_level(snapshot['level'])} XP in this level",
            inline=False,
        )
        if economy_profile:
            profession = self._resolve_profession(economy_profile.get("profession"))
            embed.add_field(
                name="Economy Snapshot",
                value=(
                    f"Profession: **{profession['name']} (Lv {int(economy_profile.get('profession_level', 1))})**\n"
                    f"Prestige: **{int(economy_profile.get('prestige', 0))}** ({self._format_prestige_bonus_text(int(economy_profile.get('prestige', 0)))})\n"
                    f"Wallet: **{int(economy_profile.get('wallet', 0))} coins**"
                ),
                inline=False,
            )
            if economy_profile.get("equipped_pet"):
                pet = economy_profile["equipped_pet"]
                embed.add_field(
                    name="Equipped Pet",
                    value=f"{pet['emoji']} **{pet['name']}** — {economy_profile.get('pet_bonus_text') or pet.get('bonus_text', '')}",
                    inline=False,
                )
        embed.set_footer(text=f"Guild: {guild.name}")
        return embed

    def _build_xp_leaderboard_embed(self, *, guild: discord.Guild, page: int) -> discord.Embed:
        guild_profiles = self._profile_data.get(str(guild.id), {})
        ranked = sorted(
            guild_profiles.items(),
            key=lambda item: (-int(item[1].get("xp", 0)), int(item[0])),
        )
        total_pages = max(1, (len(ranked) + PROFILE_LEADERBOARD_PAGE_SIZE - 1) // PROFILE_LEADERBOARD_PAGE_SIZE)
        safe_page = max(1, min(page, total_pages))
        start_index = (safe_page - 1) * PROFILE_LEADERBOARD_PAGE_SIZE
        slice_entries = ranked[start_index:start_index + PROFILE_LEADERBOARD_PAGE_SIZE]
        lines: list[str] = []
        for offset, (user_id, entry) in enumerate(slice_entries, start=start_index + 1):
            member = guild.get_member(int(user_id))
            name = _display_name(member) if member else entry.get("last_display_name") or f"User {user_id}"
            xp = int(entry.get("xp", 0))
            level = self._level_from_xp(xp)
            lines.append(f"`{offset}.` {name} - Level {level} ({xp} XP)")
        embed = discord.Embed(
            title="Cadis Etrama Di Raizel",
            description="\n".join(lines) or "No XP data has been recorded yet.",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Server XP Leaderboard")
        embed.set_footer(text=f"Page {safe_page}/{total_pages}")
        return embed

    async def _award_xp(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        if not (message.content or "").strip() and not message.attachments:
            return
        if len((message.content or "").strip()) < 3 and not message.attachments:
            return
        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        last_awarded = self._xp_cooldowns.get(key)
        if last_awarded is not None and (now - last_awarded) < XP_GAIN_COOLDOWN_SECONDS:
            return
        xp_bonus = 0.0
        with contextlib.suppress(Exception):
            xp_bonus = await self._run_db(
                self._get_xp_bonus_sync,
                message.guild.id,
                message.author.id,
                _display_name(message.author),
            )
        gained = int(round(random.randint(XP_GAIN_MIN, XP_GAIN_MAX) * (1.0 + min(float(xp_bonus), 0.5))))
        async with self._profile_lock:
            entry = self._ensure_profile_entry(message.guild.id, message.author)
            entry["xp"] = max(0, int(entry.get("xp", 0))) + gained
            entry["last_display_name"] = _display_name(message.author)
            self._xp_cooldowns[key] = now
            await self._save_profile_data()

    def _connect_db(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._economy_db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _ensure_column_sync(self, conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
        existing = {
            str(row["name"])
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    def _init_economy_db_sync(self) -> None:
        with self._connect_db() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS economy_profiles (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    last_known_name TEXT,
                    wallet INTEGER NOT NULL DEFAULT 0,
                    profession TEXT NOT NULL DEFAULT '',
                    total_earned INTEGER NOT NULL DEFAULT 0,
                    total_spent INTEGER NOT NULL DEFAULT 0,
                    daily_claimed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            self._ensure_column_sync(conn, "economy_profiles", "passive_last_at", "TEXT")
            self._ensure_column_sync(conn, "economy_profiles", "total_passive_collected", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column_sync(conn, "economy_profiles", "prestige_points", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column_sync(conn, "economy_profiles", "dungeon_lives", "INTEGER NOT NULL DEFAULT 0")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS economy_inventory (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    item_key TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id, item_key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS economy_cooldowns (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    PRIMARY KEY (guild_id, user_id, action)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS economy_quiz_sessions (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    question TEXT NOT NULL,
                    answer INTEGER NOT NULL,
                    reward INTEGER NOT NULL,
                    expires_at REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS economy_profession_progress (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    profession_key TEXT NOT NULL,
                    level INTEGER NOT NULL DEFAULT 1,
                    xp INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id, profession_key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS economy_user_stats (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    stat_key TEXT NOT NULL,
                    value INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id, stat_key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS economy_achievements (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    achievement_key TEXT NOT NULL,
                    unlocked_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id, achievement_key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS economy_daily_missions (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    mission_key TEXT NOT NULL,
                    mission_date TEXT NOT NULL,
                    progress_key TEXT NOT NULL,
                    target INTEGER NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    reward INTEGER NOT NULL DEFAULT 0,
                    claimed INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id, mission_key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS economy_pets (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    pet_key TEXT NOT NULL,
                    equipped INTEGER NOT NULL DEFAULT 0,
                    last_fed_at TEXT,
                    acquired_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id, pet_key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS utility_notes (
                    note_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL DEFAULT 0,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS marriage_relationships (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    spouse_id INTEGER NOT NULL,
                    spouse_name TEXT,
                    married_at TEXT NOT NULL,
                    love_score INTEGER NOT NULL DEFAULT 10,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS marriage_proposals (
                    guild_id INTEGER NOT NULL,
                    target_user_id INTEGER NOT NULL,
                    proposer_user_id INTEGER NOT NULL,
                    proposer_name TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, target_user_id)
                )
                """
            )

    async def _run_db(self, func, *args):
        async with self._db_lock:
            return await asyncio.to_thread(func, *args)

    def _today_key(self) -> str:
        return _utcnow().date().isoformat()

    def _channel_game_key(self, guild_id: int, channel_id: int) -> tuple[int, int]:
        return guild_id, channel_id

    def _track_session_task(self, task: asyncio.Task[Any]) -> asyncio.Task[Any]:
        self._session_tasks.add(task)
        task.add_done_callback(self._session_tasks.discard)
        return task

    def _get_active_text_game(self, guild_id: int, channel_id: int) -> Optional[tuple[str, Any]]:
        key = self._channel_game_key(guild_id, channel_id)
        for label, mapping in (
            ("drawgame", self._drawgame_sessions),
            ("hangman", self._hangman_sessions),
            ("wordchain", self._wordchain_sessions),
        ):
            session = mapping.get(key)
            if session is not None and not getattr(session, "resolved", False):
                return label, session
        return None

    def _cancel_session_task(self, task: Optional[asyncio.Task[Any]]) -> None:
        if task is not None and not task.done():
            task.cancel()

    def _close_drawgame_session(self, session: DrawGameSession) -> None:
        self._cancel_session_task(session.reveal_task)
        self._cancel_session_task(session.timeout_task)
        self._drawgame_sessions.pop(self._channel_game_key(session.guild_id, session.channel_id), None)

    def _close_trivia_session(self, session: TriviaSession) -> None:
        self._cancel_session_task(session.question_task)
        self._cancel_session_task(session.advance_task)
        self._trivia_sessions.pop(self._channel_game_key(session.guild_id, session.channel_id), None)

    def _close_hangman_session(self, session: HangmanSession) -> None:
        self._cancel_session_task(session.timeout_task)
        self._hangman_sessions.pop(self._channel_game_key(session.guild_id, session.channel_id), None)

    def _close_wordchain_session(self, session: WordChainSession) -> None:
        self._cancel_session_task(session.timeout_task)
        self._wordchain_sessions.pop(self._channel_game_key(session.guild_id, session.channel_id), None)

    def _get_active_chat_guessing_session(self, guild_id: int, channel_id: int) -> Optional[tuple[str, Any]]:
        trivia_session = self._trivia_sessions.get(self._channel_game_key(guild_id, channel_id))
        if trivia_session is not None and not getattr(trivia_session, "resolved", False):
            return "trivia", trivia_session
        return self._get_active_text_game(guild_id, channel_id)

    def _quickdraw_categories_path(self) -> Path:
        return self._quickdraw_cache_path

    def _quickdraw_raw_path(self) -> Path:
        return self._quickdraw_raw_dir

    def _load_quickdraw_categories_sync(self) -> list[str]:
        return self._quickdraw_runtime.categories()

    def _load_quickdraw_samples_sync(self, category: str) -> list[dict[str, Any]]:
        return self._quickdraw_runtime.get_entries_for_category(category)

    def _normalize_quickdraw_strokes(self, drawing: list[list[list[int]]]) -> list[list[tuple[float, float]]]:
        return normalize_quickdraw_strokes(drawing)

    def _quickdraw_entry_is_drawable(self, entry: dict[str, Any]) -> bool:
        return quickdraw_entry_is_drawable(entry)

    def _prepare_quickdraw_entry(self, entry: dict[str, Any], *, fallback_answer: str | None = None) -> dict[str, Any] | None:
        prepared = sanitize_quickdraw_entry(
            entry,
            fallback_answer=fallback_answer,
            fallback_category=str(entry.get("category") or fallback_answer or entry.get("answer") or ""),
            clue=QUICKDRAW_CLUES.get(
                _normalize_lookup(str(entry.get("answer") or fallback_answer or "")),
                "It is a common object, animal, or idea from Quick Draw.",
            ),
        )
        if prepared is None:
            return None
        answer = str(prepared["answer"]).strip()
        aliases = {_normalize_guess_text(answer), _normalize_guess_text(answer.replace(" ", ""))}
        for alias in prepared.get("aliases", []) or []:
            normalized = _normalize_guess_text(str(alias))
            if normalized:
                aliases.add(normalized)
        prepared["normalized_answers"] = aliases
        return prepared

    def _get_random_quickdraw_entry_sync(self) -> dict[str, Any]:
        entry = self._quickdraw_runtime.choose_entry(
            category_attempt_limit=min(QUICKDRAW_CATEGORY_ATTEMPT_LIMIT, DEFAULT_CATEGORY_ATTEMPT_LIMIT),
            sample_attempt_limit=min(QUICKDRAW_SAMPLE_ATTEMPT_LIMIT, DEFAULT_SAMPLE_ATTEMPT_LIMIT),
        )
        prepared = self._prepare_quickdraw_entry(entry, fallback_answer=str(entry.get("answer") or ""))
        if prepared is None:
            raise RuntimeError("Quick Draw runtime returned a non-drawable cached entry.")
        return prepared

    def _prepare_drawgame_startup_sync(self) -> tuple[dict[str, Any], io.BytesIO]:
        entry = self._get_random_quickdraw_entry_sync()
        normalized_strokes = self._normalize_quickdraw_strokes(entry["drawing"])
        if not normalized_strokes:
            raise RuntimeError("Quick Draw startup selected an entry without drawable strokes.")
        first_fraction = self._drawgame_phase_fraction(0)
        visible_stroke_count = max(1, math.ceil(len(normalized_strokes) * first_fraction))
        logger.info(
            "Quick Draw startup: cache category='%s' answer='%s' drawable_strokes=%s visible_strokes=%s cache_entries=%s",
            entry.get("category"),
            entry.get("answer"),
            len(normalized_strokes),
            visible_stroke_count,
            self._quickdraw_runtime.stats.entry_count,
        )
        image_bytes = self._render_quickdraw_png(entry["drawing"], fraction=first_fraction)
        logger.info("Quick Draw startup: render succeeded for answer='%s'.", entry.get("answer"))
        return entry, image_bytes

    def _render_quickdraw_png(self, drawing: list[list[list[int]]], *, fraction: float) -> io.BytesIO:
        safe_fraction = max(0.05, min(1.0, float(fraction)))
        image = Image.new("RGB", (DRAWSHARE_CANVAS_SIZE, DRAWSHARE_CANVAS_SIZE), "white")
        draw = ImageDraw.Draw(image)
        strokes = self._normalize_quickdraw_strokes(drawing)
        total_strokes = len(strokes)
        visible_stroke_count = max(1, math.ceil(total_strokes * safe_fraction)) if total_strokes else 0
        preview_points = [stroke[:3] for stroke in strokes[:2]]
        logger.debug(
            "Quick Draw render: total_raw_strokes=%s drawable_strokes=%s visible_strokes=%s fraction=%.2f preview=%s",
            len(drawing or []),
            total_strokes,
            visible_stroke_count,
            safe_fraction,
            preview_points,
        )

        if not strokes:
            logger.warning("Quick Draw render received no drawable strokes.")
            draw.rectangle((88, 88, DRAWSHARE_CANVAS_SIZE - 88, DRAWSHARE_CANVAS_SIZE - 88), outline="black", width=5)
            draw.line(
                ((116, 116), (DRAWSHARE_CANVAS_SIZE - 116, DRAWSHARE_CANVAS_SIZE - 116)),
                fill="black",
                width=5,
            )
            draw.line(
                ((DRAWSHARE_CANVAS_SIZE - 116, 116), (116, DRAWSHARE_CANVAS_SIZE - 116)),
                fill="black",
                width=5,
            )
            output = io.BytesIO()
            image.save(output, format="PNG")
            output.seek(0)
            return output

        all_x = [point[0] for stroke in strokes for point in stroke]
        all_y = [point[1] for stroke in strokes for point in stroke]
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)
        drawing_width = max(max_x - min_x, 1.0)
        drawing_height = max(max_y - min_y, 1.0)
        margin = 28
        usable_size = max(1, DRAWSHARE_CANVAS_SIZE - margin * 2)
        scale = min(usable_size / drawing_width, usable_size / drawing_height)
        offset_x = (DRAWSHARE_CANVAS_SIZE - drawing_width * scale) / 2
        offset_y = (DRAWSHARE_CANVAS_SIZE - drawing_height * scale) / 2

        drawn_segments = 0
        for stroke in strokes[:visible_stroke_count]:
            points = [
                (
                    max(0, min(DRAWSHARE_CANVAS_SIZE - 1, int(round(offset_x + (x_value - min_x) * scale)))),
                    max(0, min(DRAWSHARE_CANVAS_SIZE - 1, int(round(offset_y + (y_value - min_y) * scale)))),
                )
                for x_value, y_value in stroke
            ]
            if not points:
                continue
            if len(points) == 1:
                x_pos, y_pos = points[0]
                draw.ellipse((x_pos - 2, y_pos - 2, x_pos + 2, y_pos + 2), fill="black", outline="black")
                drawn_segments += 1
                continue
            draw.line(points, fill="black", width=5, joint="curve")
            drawn_segments += 1

        if drawn_segments <= 0:
            logger.warning(
                "Quick Draw render produced no visible segments; total_strokes=%s visible_strokes=%s preview=%s",
                total_strokes,
                visible_stroke_count,
                preview_points,
            )
            draw.rectangle((96, 96, DRAWSHARE_CANVAS_SIZE - 96, DRAWSHARE_CANVAS_SIZE - 96), outline="black", width=4)

        white_reference = Image.new("RGB", (DRAWSHARE_CANVAS_SIZE, DRAWSHARE_CANVAS_SIZE), "white")
        if ImageChops.difference(image, white_reference).getbbox() is None:
            logger.warning(
                "Quick Draw render still blank after drawing; total_strokes=%s visible_strokes=%s",
                total_strokes,
                visible_stroke_count,
            )
            draw.line(((112, 112), (DRAWSHARE_CANVAS_SIZE - 112, DRAWSHARE_CANVAS_SIZE - 112)), fill="black", width=5)
            draw.line(((DRAWSHARE_CANVAS_SIZE - 112, 112), (112, DRAWSHARE_CANVAS_SIZE - 112)), fill="black", width=5)

        output = io.BytesIO()
        image.save(output, format="PNG")
        output.seek(0)
        return output

    def _profession_xp_required(self, level: int) -> int:
        safe_level = max(1, level)
        return 120 + (safe_level - 1) * 80

    def _profession_upgrade_cost(self, level: int) -> int:
        safe_level = max(1, level)
        return 250 + (safe_level - 1) * 175

    def _profession_income_multiplier(self, level: int) -> float:
        safe_level = max(1, level)
        return 1.0 + (safe_level - 1) * 0.08

    def _wallet_work_bonus_multiplier(self, wallet: int) -> float:
        safe_wallet = max(0, int(wallet))
        if safe_wallet >= 2_500_000:
            return 0.18
        if safe_wallet >= 1_250_000:
            return 0.15
        if safe_wallet >= 750_000:
            return 0.12
        if safe_wallet >= 300_000:
            return 0.09
        if safe_wallet >= 125_000:
            return 0.07
        if safe_wallet >= 50_000:
            return 0.05
        if safe_wallet >= 15_000:
            return 0.03
        if safe_wallet >= 5_000:
            return 0.015
        return 0.0

    def _prestige_work_bonus_multiplier(self, prestige: int) -> float:
        safe_prestige = max(0, int(prestige))
        if safe_prestige >= 10:
            return safe_prestige * 0.03
        return safe_prestige * 0.02

    def _format_prestige_bonus_text(self, prestige: int) -> str:
        bonus_percent = int(round(self._prestige_work_bonus_multiplier(prestige) * 100))
        return f"+{bonus_percent}% work income"

    def _award_prestige_conn(
        self,
        conn: sqlite3.Connection,
        *,
        guild_id: int,
        user_id: int,
        display_name: str,
        amount: int,
    ) -> int:
        self._ensure_economy_profile_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name)
        safe_amount = max(0, int(amount))
        if safe_amount <= 0:
            row = conn.execute(
                "SELECT prestige_points FROM economy_profiles WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
            return int(row["prestige_points"]) if row is not None and row["prestige_points"] is not None else 0
        conn.execute(
            """
            UPDATE economy_profiles
            SET prestige_points = prestige_points + ?,
                last_known_name = ?,
                updated_at = ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (safe_amount, display_name, _utcnow().isoformat(), guild_id, user_id),
        )
        row = conn.execute(
            "SELECT prestige_points FROM economy_profiles WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        return int(row["prestige_points"]) if row is not None and row["prestige_points"] is not None else 0

    def _get_achievement_prestige_conn(
        self,
        conn: sqlite3.Connection,
        *,
        guild_id: int,
        user_id: int,
    ) -> int:
        rows = conn.execute(
            "SELECT achievement_key FROM economy_achievements WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchall()
        total = 0
        for row in rows:
            definition = ACHIEVEMENT_LOOKUP.get(str(row["achievement_key"]))
            if definition is None:
                continue
            total += max(0, int(definition.get("prestige_reward", 0)))
        return total

    def _get_stat_value_conn(self, conn: sqlite3.Connection, *, guild_id: int, user_id: int, stat_key: str) -> int:
        row = conn.execute(
            "SELECT value FROM economy_user_stats WHERE guild_id = ? AND user_id = ? AND stat_key = ?",
            (guild_id, user_id, stat_key),
        ).fetchone()
        return int(row["value"]) if row is not None else 0

    def _increment_stat_conn(
        self,
        conn: sqlite3.Connection,
        *,
        guild_id: int,
        user_id: int,
        stat_key: str,
        delta: int = 1,
    ) -> int:
        timestamp = _utcnow().isoformat()
        conn.execute(
            """
            INSERT INTO economy_user_stats (guild_id, user_id, stat_key, value, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, stat_key) DO UPDATE SET
                value = value + excluded.value,
                updated_at = excluded.updated_at
            """,
            (guild_id, user_id, stat_key, delta, timestamp),
        )
        return self._get_stat_value_conn(conn, guild_id=guild_id, user_id=user_id, stat_key=stat_key)

    def _get_stats_map_conn(
        self,
        conn: sqlite3.Connection,
        *,
        guild_id: int,
        user_id: int,
    ) -> dict[str, int]:
        rows = conn.execute(
            "SELECT stat_key, value FROM economy_user_stats WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchall()
        return {str(row["stat_key"]): int(row["value"]) for row in rows}

    def _ensure_profession_progress_conn(
        self,
        conn: sqlite3.Connection,
        *,
        guild_id: int,
        user_id: int,
        profession_key: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO economy_profession_progress (guild_id, user_id, profession_key, level, xp, updated_at)
            VALUES (?, ?, ?, 1, 0, ?)
            ON CONFLICT(guild_id, user_id, profession_key) DO NOTHING
            """,
            (guild_id, user_id, profession_key, _utcnow().isoformat()),
        )

    def _get_profession_progress_conn(
        self,
        conn: sqlite3.Connection,
        *,
        guild_id: int,
        user_id: int,
        profession_key: str,
    ) -> dict[str, int]:
        self._ensure_profession_progress_conn(
            conn,
            guild_id=guild_id,
            user_id=user_id,
            profession_key=profession_key,
        )
        row = conn.execute(
            """
            SELECT level, xp
            FROM economy_profession_progress
            WHERE guild_id = ? AND user_id = ? AND profession_key = ?
            """,
            (guild_id, user_id, profession_key),
        ).fetchone()
        return {
            "level": int(row["level"]) if row is not None else 1,
            "xp": int(row["xp"]) if row is not None else 0,
        }

    def _add_profession_xp_conn(
        self,
        conn: sqlite3.Connection,
        *,
        guild_id: int,
        user_id: int,
        profession_key: str,
        amount: int,
    ) -> dict[str, int]:
        self._ensure_profession_progress_conn(
            conn,
            guild_id=guild_id,
            user_id=user_id,
            profession_key=profession_key,
        )
        conn.execute(
            """
            UPDATE economy_profession_progress
            SET xp = xp + ?, updated_at = ?
            WHERE guild_id = ? AND user_id = ? AND profession_key = ?
            """,
            (amount, _utcnow().isoformat(), guild_id, user_id, profession_key),
        )
        return self._get_profession_progress_conn(
            conn,
            guild_id=guild_id,
            user_id=user_id,
            profession_key=profession_key,
        )

    def _get_item_effect_summary_conn(
        self,
        conn: sqlite3.Connection,
        *,
        guild_id: int,
        user_id: int,
    ) -> dict[str, Any]:
        rows = conn.execute(
            """
            SELECT item_key, quantity
            FROM economy_inventory
            WHERE guild_id = ? AND user_id = ? AND quantity > 0
            """,
            (guild_id, user_id),
        ).fetchall()
        action_bonus: dict[str, float] = {}
        descriptions: list[str] = []
        passive_sources: list[dict[str, Any]] = []
        xp_bonus = 0.0
        prestige = 0
        property_count = 0
        for row in rows:
            item_key = _normalize_lookup(str(row["item_key"]))
            quantity = max(0, int(row["quantity"]))
            effect = ITEM_EFFECTS.get(item_key)
            if effect is None or quantity <= 0:
                continue
            item = SHOP_ITEM_LOOKUP.get(item_key)
            item_name = str(item["name"]) if item else item_key.title()
            if effect.get("xp_bonus"):
                xp_bonus += float(effect["xp_bonus"]) * quantity
            if effect.get("prestige"):
                prestige += int(effect["prestige"]) * quantity
            for action, bonus in effect.get("action_bonus", {}).items():
                action_bonus[action] = action_bonus.get(action, 0.0) + (float(bonus) * quantity)
            if effect.get("passive_income"):
                income_amount = int(effect["passive_income"]) * quantity
                passive_sources.append(
                    {
                        "item_name": item_name,
                        "quantity": quantity,
                        "amount_per_tick": income_amount,
                    }
                )
                property_count += quantity
            if effect.get("description"):
                descriptions.append(f"{item_name}: {effect['description']}")
        return {
            "action_bonus": action_bonus,
            "xp_bonus": min(xp_bonus, 0.5),
            "prestige": prestige,
            "passive_sources": passive_sources,
            "property_count": property_count,
            "descriptions": descriptions,
            "passive_rate_per_tick": sum(source["amount_per_tick"] for source in passive_sources),
        }

    def _get_pet_effect_summary_conn(
        self,
        conn: sqlite3.Connection,
        *,
        guild_id: int,
        user_id: int,
    ) -> dict[str, Any]:
        row = conn.execute(
            """
            SELECT pet_key, last_fed_at
            FROM economy_pets
            WHERE guild_id = ? AND user_id = ? AND equipped = 1
            LIMIT 1
            """,
            (guild_id, user_id),
        ).fetchone()
        if row is None:
            return {"equipped_pet": None, "action_bonus": {}, "xp_bonus": 0.0, "prestige": 0, "bonus_text": None, "dungeon_bonus": 0.0, "crash_bonus": 0.0}
        pet = PET_LOOKUP.get(_normalize_lookup(str(row["pet_key"])))
        if pet is None:
            return {"equipped_pet": None, "action_bonus": {}, "xp_bonus": 0.0, "prestige": 0, "bonus_text": None, "dungeon_bonus": 0.0, "crash_bonus": 0.0}
        return {
            "equipped_pet": pet,
            "action_bonus": dict(pet.get("action_bonus", {})),
            "xp_bonus": float(pet.get("xp_bonus", 0.0)),
            "prestige": int(pet.get("prestige", 0)),
            "bonus_text": pet.get("bonus_text"),
            "dungeon_bonus": float(pet.get("dungeon_bonus", 0.0)),
            "crash_bonus": float(pet.get("crash_bonus", 0.0)),
        }

    def _apply_passive_income_conn(
        self,
        conn: sqlite3.Connection,
        *,
        guild_id: int,
        user_id: int,
        display_name: str,
    ) -> dict[str, Any]:
        self._ensure_economy_profile_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name)
        effects = self._get_item_effect_summary_conn(conn, guild_id=guild_id, user_id=user_id)
        now = _utcnow()
        row = conn.execute(
            """
            SELECT passive_last_at, total_passive_collected
            FROM economy_profiles
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        ).fetchone()
        last_raw = str(row["passive_last_at"]) if row is not None and row["passive_last_at"] else ""
        if effects["passive_rate_per_tick"] <= 0:
            conn.execute(
                "UPDATE economy_profiles SET passive_last_at = ?, updated_at = ? WHERE guild_id = ? AND user_id = ?",
                (now.isoformat(), now.isoformat(), guild_id, user_id),
            )
            return {"collected": 0, "effects": effects}
        if not last_raw:
            conn.execute(
                "UPDATE economy_profiles SET passive_last_at = ?, updated_at = ? WHERE guild_id = ? AND user_id = ?",
                (now.isoformat(), now.isoformat(), guild_id, user_id),
            )
            return {"collected": 0, "effects": effects}
        with contextlib.suppress(ValueError):
            last_at = dt.datetime.fromisoformat(last_raw)
            elapsed = max(0.0, (now - last_at).total_seconds())
            cycles = int(elapsed // PASSIVE_INCOME_TICK_SECONDS)
            if cycles <= 0:
                return {"collected": 0, "effects": effects}
            collected = cycles * int(effects["passive_rate_per_tick"])
            if collected > 0:
                self._adjust_wallet_conn(
                    conn,
                    guild_id=guild_id,
                    user_id=user_id,
                    display_name=display_name,
                    delta=collected,
                )
            new_last_at = last_at + dt.timedelta(seconds=cycles * PASSIVE_INCOME_TICK_SECONDS)
            conn.execute(
                """
                UPDATE economy_profiles
                SET passive_last_at = ?, total_passive_collected = total_passive_collected + ?, updated_at = ?, last_known_name = ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (new_last_at.isoformat(), collected, now.isoformat(), display_name, guild_id, user_id),
            )
            return {"collected": collected, "effects": effects}
        conn.execute(
            "UPDATE economy_profiles SET passive_last_at = ?, updated_at = ? WHERE guild_id = ? AND user_id = ?",
            (now.isoformat(), now.isoformat(), guild_id, user_id),
        )
        return {"collected": 0, "effects": effects}

    def _prepare_profile_conn(
        self,
        conn: sqlite3.Connection,
        *,
        guild_id: int,
        user_id: int,
        display_name: str,
    ) -> dict[str, Any]:
        passive_result = self._apply_passive_income_conn(
            conn,
            guild_id=guild_id,
            user_id=user_id,
            display_name=display_name,
        )
        row = conn.execute(
            "SELECT * FROM economy_profiles WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        profile = dict(row) if row else {}
        profession_key = str(profile.get("profession") or DEFAULT_PROFESSION_KEY)
        profession_progress = self._get_profession_progress_conn(
            conn,
            guild_id=guild_id,
            user_id=user_id,
            profession_key=profession_key,
        )
        effects = passive_result["effects"]
        pet_effects = self._get_pet_effect_summary_conn(
            conn,
            guild_id=guild_id,
            user_id=user_id,
        )
        for action, bonus in pet_effects.get("action_bonus", {}).items():
            effects["action_bonus"][action] = effects["action_bonus"].get(action, 0.0) + float(bonus)
        effects["xp_bonus"] = float(effects.get("xp_bonus", 0.0)) + float(pet_effects.get("xp_bonus", 0.0))
        effects["prestige"] = int(effects.get("prestige", 0)) + int(pet_effects.get("prestige", 0))
        base_prestige = int(profile.get("prestige_points", 0) or 0)
        achievement_prestige = self._get_achievement_prestige_conn(
            conn,
            guild_id=guild_id,
            user_id=user_id,
        )
        item_prestige = int(effects.get("prestige", 0))
        total_prestige = base_prestige + achievement_prestige + item_prestige
        profile["profession_level"] = profession_progress["level"]
        profile["profession_xp"] = profession_progress["xp"]
        profile["profession_xp_needed"] = self._profession_xp_required(profession_progress["level"])
        profile["profession_upgrade_cost"] = self._profession_upgrade_cost(profession_progress["level"])
        profile["prestige_points"] = base_prestige
        profile["achievement_prestige"] = achievement_prestige
        profile["item_prestige"] = item_prestige
        profile["prestige"] = total_prestige
        profile["prestige_work_bonus"] = self._prestige_work_bonus_multiplier(total_prestige)
        profile["property_count"] = effects["property_count"]
        profile["passive_sources"] = effects["passive_sources"]
        profile["passive_rate_per_tick"] = effects["passive_rate_per_tick"]
        profile["passive_per_hour"] = int((effects["passive_rate_per_tick"] * 3600) / PASSIVE_INCOME_TICK_SECONDS)
        profile["dungeon_lives"] = max(0, min(DUNGEON_LIFE_MAX, int(profile.get("dungeon_lives", 0) or 0)))
        profile["item_effect_descriptions"] = effects["descriptions"]
        profile["item_effects"] = effects
        profile["equipped_pet"] = pet_effects.get("equipped_pet")
        profile["pet_bonus_text"] = pet_effects.get("bonus_text")
        profile["dungeon_bonus"] = pet_effects.get("dungeon_bonus", 0.0)
        profile["crash_bonus"] = pet_effects.get("crash_bonus", 0.0)
        profile["auto_collected_passive"] = passive_result["collected"]
        return profile

    def _evaluate_achievement_metric_conn(
        self,
        conn: sqlite3.Connection,
        *,
        guild_id: int,
        user_id: int,
        display_name: str,
        definition: dict[str, Any],
        profile: Optional[dict[str, Any]] = None,
    ) -> int:
        profile_data = profile or self._prepare_profile_conn(
            conn,
            guild_id=guild_id,
            user_id=user_id,
            display_name=display_name,
        )
        metric = str(definition["metric"])
        if metric == "total_earned":
            return int(profile_data.get("total_earned", 0))
        if metric == "property_count":
            return int(profile_data.get("property_count", 0))
        if metric == "profession_level_max":
            row = conn.execute(
                "SELECT MAX(level) AS max_level FROM economy_profession_progress WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
            return int(row["max_level"]) if row is not None and row["max_level"] is not None else 1
        if metric.startswith("stat:"):
            return self._get_stat_value_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                stat_key=metric.split(":", 1)[1],
            )
        return 0

    def _refresh_achievements_conn(
        self,
        conn: sqlite3.Connection,
        *,
        guild_id: int,
        user_id: int,
        display_name: str,
    ) -> list[dict[str, Any]]:
        profile = self._prepare_profile_conn(
            conn,
            guild_id=guild_id,
            user_id=user_id,
            display_name=display_name,
        )
        unlocked_rows = conn.execute(
            "SELECT achievement_key FROM economy_achievements WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchall()
        unlocked = {str(row["achievement_key"]) for row in unlocked_rows}
        newly_unlocked: list[dict[str, Any]] = []
        for definition in ACHIEVEMENT_DEFS:
            if definition["key"] in unlocked:
                continue
            progress = self._evaluate_achievement_metric_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                definition=definition,
                profile=profile,
            )
            if progress >= int(definition["target"]):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO economy_achievements (guild_id, user_id, achievement_key, unlocked_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (guild_id, user_id, definition["key"], _utcnow().isoformat()),
                )
                newly_unlocked.append(definition)
        return newly_unlocked

    def _ensure_daily_missions_conn(
        self,
        conn: sqlite3.Connection,
        *,
        guild_id: int,
        user_id: int,
    ) -> list[dict[str, Any]]:
        today_key = self._today_key()
        rows = conn.execute(
            "SELECT * FROM economy_daily_missions WHERE guild_id = ? AND user_id = ? ORDER BY mission_key ASC",
            (guild_id, user_id),
        ).fetchall()
        if rows and all(str(row["mission_date"]) == today_key for row in rows):
            return [dict(row) for row in rows]
        conn.execute(
            "DELETE FROM economy_daily_missions WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        selected = random.sample(list(DAILY_MISSION_DEFS), k=min(3, len(DAILY_MISSION_DEFS)))
        for definition in selected:
            conn.execute(
                """
                INSERT INTO economy_daily_missions (
                    guild_id, user_id, mission_key, mission_date, progress_key, target, progress, reward, claimed
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, 0)
                """,
                (
                    guild_id,
                    user_id,
                    definition["key"],
                    today_key,
                    definition["progress_key"],
                    int(definition["target"]),
                    int(definition["reward"]),
                ),
            )
        rows = conn.execute(
            "SELECT * FROM economy_daily_missions WHERE guild_id = ? AND user_id = ? ORDER BY mission_key ASC",
            (guild_id, user_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def _increment_daily_progress_conn(
        self,
        conn: sqlite3.Connection,
        *,
        guild_id: int,
        user_id: int,
        progress_key: str,
        delta: int,
    ) -> None:
        if delta <= 0:
            return
        missions = self._ensure_daily_missions_conn(conn, guild_id=guild_id, user_id=user_id)
        for mission in missions:
            if str(mission["progress_key"]) != progress_key:
                continue
            conn.execute(
                """
                UPDATE economy_daily_missions
                SET progress = MIN(target, progress + ?)
                WHERE guild_id = ? AND user_id = ? AND mission_key = ?
                """,
                (delta, guild_id, user_id, mission["mission_key"]),
            )

    def _auto_claim_completed_missions_conn(
        self,
        conn: sqlite3.Connection,
        *,
        guild_id: int,
        user_id: int,
        display_name: str,
    ) -> dict[str, Any]:
        missions = self._ensure_daily_missions_conn(conn, guild_id=guild_id, user_id=user_id)
        claimable = [mission for mission in missions if int(mission["claimed"]) == 0 and int(mission["progress"]) >= int(mission["target"])]
        total_reward = sum(int(mission["reward"]) for mission in claimable)
        claimed_count = len(claimable)
        if total_reward > 0:
            self._adjust_wallet_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                delta=total_reward,
            )
            for mission in claimable:
                conn.execute(
                    """
                    UPDATE economy_daily_missions
                    SET claimed = 1
                    WHERE guild_id = ? AND user_id = ? AND mission_key = ?
                    """,
                    (guild_id, user_id, mission["mission_key"]),
                )
            self._increment_stat_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                stat_key="missions_completed",
                delta=claimed_count,
            )
            self._refresh_achievements_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
        missions = self._ensure_daily_missions_conn(conn, guild_id=guild_id, user_id=user_id)
        return {"missions": missions, "claimed_reward": total_reward, "claimed_count": claimed_count}

    def _record_progress_event_conn(
        self,
        conn: sqlite3.Connection,
        *,
        guild_id: int,
        user_id: int,
        display_name: str,
        stat_updates: Optional[dict[str, int]] = None,
        mission_updates: Optional[dict[str, int]] = None,
    ) -> None:
        for stat_key, delta in (stat_updates or {}).items():
            self._increment_stat_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                stat_key=stat_key,
                delta=delta,
            )
        for progress_key, delta in (mission_updates or {}).items():
            self._increment_daily_progress_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                progress_key=progress_key,
                delta=delta,
            )
        self._refresh_achievements_conn(
            conn,
            guild_id=guild_id,
            user_id=user_id,
            display_name=display_name,
        )

    def _ensure_economy_profile_conn(self, conn: sqlite3.Connection, *, guild_id: int, user_id: int, display_name: str) -> None:
        timestamp = _utcnow().isoformat()
        conn.execute(
            """
            INSERT INTO economy_profiles (
                guild_id, user_id, last_known_name, wallet, profession,
                total_earned, total_spent, daily_claimed_at, created_at, updated_at
            )
            VALUES (?, ?, ?, 0, ?, 0, 0, NULL, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                last_known_name = excluded.last_known_name,
                updated_at = excluded.updated_at
            """,
            (
                guild_id,
                user_id,
                display_name,
                DEFAULT_PROFESSION_KEY,
                timestamp,
                timestamp,
            ),
        )

    def _get_economy_profile_sync(self, guild_id: int, user_id: int, display_name: str) -> dict[str, Any]:
        with self._connect_db() as conn:
            return self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )

    def _get_cooldown_remaining_conn(self, conn: sqlite3.Connection, *, guild_id: int, user_id: int, action: str) -> float:
        now = time.time()
        row = conn.execute(
            "SELECT expires_at FROM economy_cooldowns WHERE guild_id = ? AND user_id = ? AND action = ?",
            (guild_id, user_id, action),
        ).fetchone()
        if row is None:
            return 0.0
        remaining = float(row["expires_at"]) - now
        if remaining <= 0:
            conn.execute(
                "DELETE FROM economy_cooldowns WHERE guild_id = ? AND user_id = ? AND action = ?",
                (guild_id, user_id, action),
            )
            return 0.0
        return remaining

    def _set_cooldown_conn(self, conn: sqlite3.Connection, *, guild_id: int, user_id: int, action: str, seconds: float) -> None:
        conn.execute(
            """
            INSERT INTO economy_cooldowns (guild_id, user_id, action, expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, action) DO UPDATE SET
                expires_at = excluded.expires_at
            """,
            (guild_id, user_id, action, time.time() + seconds),
        )

    def _adjust_wallet_conn(self, conn: sqlite3.Connection, *, guild_id: int, user_id: int, display_name: str, delta: int) -> tuple[bool, int]:
        self._ensure_economy_profile_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name)
        row = conn.execute(
            "SELECT wallet FROM economy_profiles WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        if row is None:
            return False, 0
        current_wallet = int(row["wallet"])
        new_wallet = current_wallet + delta
        if new_wallet < 0:
            return False, current_wallet
        conn.execute(
            """
            UPDATE economy_profiles
            SET wallet = ?,
                total_earned = total_earned + ?,
                total_spent = total_spent + ?,
                last_known_name = ?,
                updated_at = ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (
                new_wallet,
                max(delta, 0),
                max(-delta, 0),
                display_name,
                _utcnow().isoformat(),
                guild_id,
                user_id,
            ),
        )
        return True, new_wallet

    def _get_wallet_conn(self, conn: sqlite3.Connection, *, guild_id: int, user_id: int) -> int:
        row = conn.execute(
            "SELECT wallet FROM economy_profiles WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        if row is None:
            return 0
        return int(row["wallet"])

    def _get_dungeon_lives_conn(self, conn: sqlite3.Connection, *, guild_id: int, user_id: int) -> int:
        row = conn.execute(
            "SELECT dungeon_lives FROM economy_profiles WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        if row is None or row["dungeon_lives"] is None:
            return 0
        return max(0, min(DUNGEON_LIFE_MAX, int(row["dungeon_lives"])))

    def _buy_dungeon_life_sync(self, guild_id: int, user_id: int, display_name: str) -> dict[str, Any]:
        with self._connect_db() as conn:
            self._prepare_profile_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name)
            lives = self._get_dungeon_lives_conn(conn, guild_id=guild_id, user_id=user_id)
            wallet = self._get_wallet_conn(conn, guild_id=guild_id, user_id=user_id)
            if lives >= DUNGEON_LIFE_MAX:
                return {"status": "maxed", "lives": lives, "wallet": wallet}
            if wallet < DUNGEON_LIFE_COST:
                return {"status": "insufficient", "lives": lives, "wallet": wallet}
            ok, wallet_after = self._adjust_wallet_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                delta=-DUNGEON_LIFE_COST,
            )
            if not ok:
                return {"status": "error", "lives": lives, "wallet": wallet}
            conn.execute(
                """
                UPDATE economy_profiles
                SET dungeon_lives = MIN(?, dungeon_lives + ?), updated_at = ?, last_known_name = ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (
                    DUNGEON_LIFE_MAX,
                    1,
                    _utcnow().isoformat(),
                    display_name,
                    guild_id,
                    user_id,
                ),
            )
            return {
                "status": "success",
                "lives": self._get_dungeon_lives_conn(conn, guild_id=guild_id, user_id=user_id),
                "wallet": wallet_after,
            }

    def _consume_dungeon_life_sync(self, guild_id: int, user_id: int, display_name: str) -> dict[str, Any]:
        with self._connect_db() as conn:
            self._prepare_profile_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name)
            lives = self._get_dungeon_lives_conn(conn, guild_id=guild_id, user_id=user_id)
            if lives <= 0:
                return {"status": "empty", "lives": 0}
            conn.execute(
                """
                UPDATE economy_profiles
                SET dungeon_lives = MAX(0, dungeon_lives - 1), updated_at = ?, last_known_name = ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (_utcnow().isoformat(), display_name, guild_id, user_id),
            )
            return {
                "status": "success",
                "lives": self._get_dungeon_lives_conn(conn, guild_id=guild_id, user_id=user_id),
            }

    def _get_dungeon_companion(self, companion_key: Optional[str]) -> Optional[dict[str, Any]]:
        if not companion_key:
            return None
        return DUNGEON_COMPANION_LOOKUP.get(str(companion_key).strip().lower())

    def _buy_dungeon_companion_sync(
        self,
        guild_id: int,
        user_id: int,
        display_name: str,
        companion_key: str,
    ) -> dict[str, Any]:
        companion = self._get_dungeon_companion(companion_key)
        if not companion:
            return {"status": "invalid", "wallet": 0}
        with self._connect_db() as conn:
            self._prepare_profile_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name)
            wallet = self._get_wallet_conn(conn, guild_id=guild_id, user_id=user_id)
            cost = int(companion["cost"])
            if wallet < cost:
                return {"status": "insufficient", "wallet": wallet}
            ok, wallet_after = self._adjust_wallet_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                delta=-cost,
            )
            if not ok:
                return {"status": "error", "wallet": wallet}
            return {"status": "success", "wallet": wallet_after}

    def _buy_dungeon_fighterseal_sync(self, guild_id: int, user_id: int, display_name: str) -> dict[str, Any]:
        return self._buy_dungeon_companion_sync(
            guild_id=guild_id,
            user_id=user_id,
            display_name=display_name,
            companion_key="fighterseal",
        )

    def _resolve_profession(self, raw_name: Optional[str]) -> dict[str, Any]:
        if not raw_name:
            return PROFESSION_LOOKUP[DEFAULT_PROFESSION_KEY]
        return PROFESSION_LOOKUP.get(_normalize_lookup(raw_name), PROFESSION_LOOKUP[DEFAULT_PROFESSION_KEY])

    def _shop_categories(self) -> list[str]:
        present_categories = {str(item["category"]) for item in SHOP_ITEMS}
        if PETS:
            present_categories.add("Pets")
        ordered = [category for category in CATEGORY_ORDER if category in present_categories]
        ordered.extend(sorted(present_categories - set(ordered)))
        return ordered

    def _shop_items_for_category(self, category: str) -> list[dict[str, Any]]:
        return [item for item in SHOP_ITEMS if str(item["category"]) == category]

    def _shop_category_entry_count(self, category: str) -> int:
        if category == "Pets":
            return len(PETS)
        return len(self._shop_items_for_category(category))

    def _shop_item_effect_text(self, item: dict[str, Any]) -> str:
        effect = ITEM_EFFECTS.get(_normalize_lookup(str(item["key"])))
        if effect and effect.get("description"):
            return str(effect["description"])
        description = str(item.get("description", "")).strip()
        if description:
            return description
        return "Collection value and style."

    def _item_sell_price(self, item: dict[str, Any]) -> int:
        return max(1, int(round(int(item["price"]) * 0.7)))

    def _shop_pet_effect_text(self, pet: dict[str, Any]) -> str:
        return str(pet.get("bonus_text") or pet.get("description") or "Companion bonus")

    def _format_shop_item_line(self, item: dict[str, Any]) -> str:
        emoji = _item_emoji(str(item["name"]))
        return f"{emoji} **{item['name']}** — `{item['price']} coins`"

    def _format_pet_shop_line(self, pet: dict[str, Any], *, show_details: bool = False) -> str:
        line = f"{pet['emoji']} **{pet['name']}** — `{int(pet['price'])} coins`"
        if show_details:
            return f"{line}\n{pet['description']}\nBonus: {pet['bonus_text']}"
        return line

    def _format_shop_preview_block(self, category: str) -> str:
        if category == "Pets":
            preview_pets = list(PETS[:3])
            lines = [self._format_pet_shop_line(pet) for pet in preview_pets]
            hidden_count = max(0, len(PETS) - len(preview_pets))
            if hidden_count:
                lines.append(f"*+{hidden_count} more pets*")
            return "\n".join(lines)
        items = self._shop_items_for_category(category)
        preview_items = items[:3]
        lines = [self._format_shop_item_line(item) for item in preview_items]
        hidden_count = max(0, len(items) - len(preview_items))
        if hidden_count:
            lines.append(f"*+{hidden_count} more items*")
        return "\n".join(lines)

    # Re-declare the shop formatting helpers here so the active implementation
    # always includes visible effect text in shop output.
    def _format_shop_item_line(self, item: dict[str, Any]) -> str:
        emoji = _item_emoji(str(item["name"]))
        return f"{emoji} **{item['name']}** â€” `{item['price']} coins`\nEffect: {self._shop_item_effect_text(item)}"

    def _format_pet_shop_line(self, pet: dict[str, Any], *, show_details: bool = False) -> str:
        line = f"{pet['emoji']} **{pet['name']}** â€” `{int(pet['price'])} coins`"
        if show_details:
            return f"{line}\nEffect: {self._shop_pet_effect_text(pet)}\n{pet['description']}"
        return f"{line}\nEffect: {self._shop_pet_effect_text(pet)}"

    def _format_shop_preview_block(self, category: str) -> str:
        if category == "Pets":
            preview_pets = list(PETS[:2])
            lines = [self._format_pet_shop_line(pet) for pet in preview_pets]
            hidden_count = max(0, len(PETS) - len(preview_pets))
            if hidden_count:
                lines.append(f"*+{hidden_count} more pets*")
            return "\n\n".join(lines)
        items = self._shop_items_for_category(category)
        preview_items = items[:2]
        lines = [self._format_shop_item_line(item) for item in preview_items]
        hidden_count = max(0, len(items) - len(preview_items))
        if hidden_count:
            lines.append(f"*+{hidden_count} more items*")
        return "\n\n".join(lines)

    # Final ASCII-safe shop formatters so market output stays clean even on
    # consoles or Discord clients that previously surfaced mojibake dash chars.
    def _format_shop_item_line(self, item: dict[str, Any]) -> str:
        emoji = _item_emoji(str(item["name"]))
        return (
            f"{emoji} **{item['name']}** - `{item['price']} coins`\n"
            f"Effect: {self._shop_item_effect_text(item)}\n"
            f"Sell Value: {self._item_sell_price(item)} coins"
        )

    def _format_pet_shop_line(self, pet: dict[str, Any], *, show_details: bool = False) -> str:
        line = f"{pet['emoji']} **{pet['name']}** - `{int(pet['price'])} coins`"
        if show_details:
            return f"{line}\nEffect: {self._shop_pet_effect_text(pet)}\n{pet['description']}"
        return f"{line}\nEffect: {self._shop_pet_effect_text(pet)}"

    def _shopview_entries_for_category(self, category: str) -> list[dict[str, Any]]:
        if category == "Pets":
            return [{"kind": "pet", "payload": pet} for pet in PETS]
        return [{"kind": "item", "payload": item} for item in self._shop_items_for_category(category)]

    def _shopview_page_count(self, category: str) -> int:
        entries = self._shopview_entries_for_category(category)
        return max(1, (len(entries) + SHOPVIEW_PAGE_SIZE - 1) // SHOPVIEW_PAGE_SIZE)

    def _build_shopview_entry_field(self, entry: dict[str, Any]) -> tuple[str, str]:
        kind = str(entry["kind"])
        payload = dict(entry["payload"])
        if kind == "pet":
            return (
                f"{payload['emoji']} {payload['name']}",
                f"Category: **Pets**\nPrice: **{int(payload['price'])} coins**\nEffect: {self._shop_pet_effect_text(payload)}\n{payload['description']}",
            )
        return (
            f"{_item_emoji(str(payload['name']))} {payload['name']}",
            f"Category: **{payload['category']}**\nPrice: **{int(payload['price'])} coins**\nSell Value: **{self._item_sell_price(payload)} coins**\nEffect: {self._shop_item_effect_text(payload)}",
        )

    def _strip_mention_markup(self, text: str) -> str:
        return re.sub(r"<@!?\d+>", "", text or "").strip()

    def _build_item_use_messages(self, item_name: str) -> tuple[str, ...]:
        flavor = ITEM_USE_FLAVORS.get(item_name)
        if not flavor:
            return (
                f"You use your {item_name} and it makes the moment a little better.",
                f"You spend a moment with your {item_name} and enjoy the upgrade.",
                f"Your {item_name} does exactly what you hoped it would.",
                f"You make good use of your {item_name} for a while.",
                f"Your {item_name} earns its place in your inventory again.",
            )
        return (
            f"You {flavor['verb']} your {item_name}, and {flavor['scene']}.",
            f"Time with your {item_name} reminds you why you bought it; {flavor['comfort']}.",
            f"You {flavor['verb']} your {item_name} and {flavor['detail']}.",
            f"Your {item_name} settles in naturally, and {flavor['finish']}.",
            f"You spend a little time with your {item_name}, and {flavor['comfort']}.",
        )

    def _choose_item_use_message(self, item_name: str, *, target_user: Optional[discord.abc.User] = None) -> str:
        if item_name == "Phone":
            if target_user is not None:
                return random.choice(PHONE_TARGET_RESPONSES).format(target_name=_display_name(target_user))
            return random.choice(PHONE_SELF_RESPONSES)
        return random.choice(self._build_item_use_messages(item_name))

    def _create_blackjack_deck(self) -> list[tuple[str, str]]:
        deck = [(rank, suit) for suit in CARD_SUITS for rank in CARD_RANKS]
        random.shuffle(deck)
        return deck

    def _blackjack_draw(self, hand: list[tuple[str, str]], deck: list[tuple[str, str]]) -> tuple[str, str]:
        card = deck.pop()
        hand.append(card)
        return card

    def _blackjack_card_label(self, card: tuple[str, str]) -> str:
        rank, suit = card
        return f"{rank}{suit}"

    def _blackjack_hand_value(self, hand: list[tuple[str, str]]) -> int:
        total = 0
        aces = 0
        for rank, _ in hand:
            if rank in {"J", "Q", "K"}:
                total += 10
            elif rank == "A":
                total += 11
                aces += 1
            else:
                total += int(rank)
        while total > 21 and aces > 0:
            total -= 10
            aces -= 1
        return total

    def _format_blackjack_hand(self, hand: list[tuple[str, str]], *, hide_hole_card: bool = False) -> str:
        if hide_hole_card and len(hand) > 1:
            visible = [self._blackjack_card_label(hand[0]), "🂠"]
            visible.extend(self._blackjack_card_label(card) for card in hand[2:])
            return " ".join(visible)
        return " ".join(self._blackjack_card_label(card) for card in hand)

    def _blackjack_session_key(self, guild_id: int, user_id: int) -> tuple[int, int]:
        return guild_id, user_id

    def _active_game_label_for_user(self, guild_id: int, user_id: int) -> Optional[str]:
        session_key = (guild_id, user_id)
        checks = (
            (self._blackjack_sessions.get(self._blackjack_session_key(guild_id, user_id)), "blackjack"),
            (self._multiplayer_blackjack_sessions.get(session_key), "multiplayer blackjack"),
            (self._coinflip_sessions.get(session_key), "coinflip"),
            (self._duel_sessions.get(session_key), "duel"),
            (self._crash_sessions.get(self._blackjack_session_key(guild_id, user_id)), "crash"),
            (self._guess_sessions.get(session_key), "number guess"),
            (self._dungeon_sessions.get(session_key), "dungeon"),
        )
        for session, label in checks:
            if session is not None and not getattr(session, "resolved", False):
                return label
        if self._blackjack_session_key(guild_id, user_id) in self._slot_spins:
            return "slots"
        return None

    def _multiplayer_blackjack_player_name(self, session: MultiplayerBlackjackSession, user_id: Optional[int]) -> str:
        if user_id == session.challenger_id:
            return session.challenger_name
        if user_id == session.target_id:
            return session.target_name
        return "Unknown Player"

    def _multiplayer_blackjack_player_hand(self, session: MultiplayerBlackjackSession, user_id: int) -> list[tuple[str, str]]:
        return session.challenger_hand if user_id == session.challenger_id else session.target_hand

    def _multiplayer_blackjack_player_flags(self, session: MultiplayerBlackjackSession, user_id: int) -> tuple[bool, bool]:
        if user_id == session.challenger_id:
            return session.challenger_stood, session.challenger_busted
        return session.target_stood, session.target_busted

    def _set_multiplayer_blackjack_flags(
        self,
        session: MultiplayerBlackjackSession,
        user_id: int,
        *,
        stood: Optional[bool] = None,
        busted: Optional[bool] = None,
    ) -> None:
        if user_id == session.challenger_id:
            if stood is not None:
                session.challenger_stood = stood
            if busted is not None:
                session.challenger_busted = busted
            return
        if stood is not None:
            session.target_stood = stood
        if busted is not None:
            session.target_busted = busted

    def _advance_multiplayer_blackjack_turn(self, session: MultiplayerBlackjackSession) -> Optional[int]:
        order = [session.challenger_id, session.target_id]
        for player_id in order:
            stood, busted = self._multiplayer_blackjack_player_flags(session, player_id)
            if not stood and not busted:
                session.current_player_id = player_id
                return player_id
        session.current_player_id = None
        return None

    def _close_multiplayer_blackjack_session(self, session: MultiplayerBlackjackSession) -> None:
        self._multiplayer_blackjack_sessions.pop((session.guild_id, session.challenger_id), None)
        self._multiplayer_blackjack_sessions.pop((session.guild_id, session.target_id), None)

    def _close_coinflip_session(self, session: CoinflipSession) -> None:
        self._coinflip_sessions.pop((session.guild_id, session.challenger_id), None)
        self._coinflip_sessions.pop((session.guild_id, session.target_id), None)

    def _blackjack_result_note(self, session: BlackjackSession) -> Optional[str]:
        return getattr(session, "result_note", None)

    def _random_slot_reels(self) -> tuple[str, str, str]:
        return tuple(random.choice(SLOT_SYMBOLS) for _ in range(3))

    def _roll_slot_outcome(self, bet: int) -> SlotOutcome:
        roll = random.random()
        if roll < 0.005:
            payout = bet * 15
            return SlotOutcome(("7️⃣", "7️⃣", "7️⃣"), "jackpot", payout, f"**Jackpot! You won {payout} coins**")
        if roll < 0.03:
            payout = bet * 9
            return SlotOutcome(("💎", "💎", "💎"), "big_win", payout, f"**Big win! You won {payout} coins**")
        if roll < 0.10:
            symbol = random.choice(("⭐", "🪙", "🔔"))
            multiplier = {"⭐": 6, "🪙": 5, "🔔": 4}[symbol]
            payout = bet * multiplier
            return SlotOutcome((symbol, symbol, symbol), "medium_win", payout, f"**You won {payout} coins**")
        if roll < 0.35:
            if random.random() < 0.55:
                symbol = random.choice(SLOT_COMMON_SYMBOLS)
                third = random.choice(tuple(s for s in SLOT_SYMBOLS if s != symbol))
                reels = [symbol, symbol, third]
                random.shuffle(reels)
                payout = max(1, int(round(bet * 1.5)))
                return SlotOutcome(tuple(reels), "small_win", payout, f"**You won {payout} coins**")
            symbol = random.choice(SLOT_COMMON_SYMBOLS)
            multiplier = {"🍒": 3, "🍋": 3, "🍇": 4}[symbol]
            payout = bet * multiplier
            return SlotOutcome((symbol, symbol, symbol), "small_win", payout, f"**You won {payout} coins**")
        return SlotOutcome(self._random_slot_reels(), "loss", 0, f"**You lost {bet} coins**")

    def _build_slots_embed(
        self,
        *,
        bet: int,
        reels: tuple[str, str, str],
        state_text: str,
        payout_text: Optional[str] = None,
    ) -> discord.Embed:
        embed = discord.Embed(
            title="Slot Machine",
            description="A quick spin on a three-reel machine.",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Cadis Etrama Di Raizel")
        embed.add_field(name="Bet", value=_format_coin_reward(bet), inline=True)
        embed.add_field(name="Reels", value=f"{reels[0]} | {reels[1]} | {reels[2]}", inline=False)
        embed.add_field(name="Status", value=state_text, inline=False)
        if payout_text:
            embed.add_field(name="Result", value=payout_text, inline=False)
        embed.set_footer(text="One message, one spin, one result.")
        return embed

    # Final slot balance pass: keep the existing animation/UI, but rebalance the
    # actual outcome roll to around 55% total wins, 45% losses, with jackpot
    # showing up around 15% of all spins.
    def _roll_slot_outcome(self, bet: int) -> SlotOutcome:
        roll = random.random()
        if roll < 0.15:
            payout = bet * 15
            return SlotOutcome(("7️⃣", "7️⃣", "7️⃣"), "jackpot", payout, f"**Jackpot! You won {payout} coins**")
        if roll < 0.40:
            symbol = random.choice(("💎", "⭐", "🪙", "🔔"))
            multiplier = {"💎": 9, "⭐": 7, "🪙": 6, "🔔": 5}[symbol]
            payout = bet * multiplier
            return SlotOutcome((symbol, symbol, symbol), "medium_win", payout, f"**You won {payout} coins**")
        if roll < 0.55:
            if random.random() < 0.70:
                symbol = random.choice(SLOT_COMMON_SYMBOLS)
                third = random.choice(tuple(s for s in SLOT_SYMBOLS if s != symbol))
                reels = [symbol, symbol, third]
                random.shuffle(reels)
                payout = max(1, int(round(bet * 1.5)))
                return SlotOutcome(tuple(reels), "small_win", payout, f"**You won {payout} coins**")
            symbol = random.choice(SLOT_COMMON_SYMBOLS)
            multiplier = {"🍒": 3, "🍋": 3, "🍇": 4}[symbol]
            payout = bet * multiplier
            return SlotOutcome((symbol, symbol, symbol), "small_win", payout, f"**You won {payout} coins**")
        return SlotOutcome(self._random_slot_reels(), "loss", 0, f"**You lost {bet} coins**")

    def _roll_crash_point(self) -> float:
        roll = random.random()
        if roll < 0.10:
            return round(random.uniform(5.0, 9.0), 2)
        if roll < 0.35:
            return round(random.uniform(2.8, 4.8), 2)
        if roll < 0.72:
            return round(random.uniform(1.9, 2.8), 2)
        return round(random.uniform(1.18, 1.75), 2)

    def _calculate_crash_payout(self, session: CrashSession) -> int:
        payout = max(session.bet, int(round(session.bet * session.current_multiplier)))
        return int(round(payout * (1.0 + min(session.bonus_multiplier, 0.25))))

    def _advance_crash_multiplier(self, session: CrashSession) -> None:
        session.tick_count += 1
        pressure = min(0.22, session.tick_count * 0.012)
        base_gain = random.uniform(0.03, 0.11) + pressure
        wobble = random.uniform(-0.18, 0.14)
        if session.current_multiplier < 1.5:
            wobble *= 0.7
        if random.random() < 0.22:
            wobble -= random.uniform(0.03, 0.09)
        if random.random() < 0.18:
            wobble += random.uniform(0.04, 0.10)
        delta = round(max(-0.16, min(0.32, base_gain + wobble)), 2)
        next_multiplier = round(max(1.0, session.current_multiplier + delta), 2)
        if next_multiplier <= session.current_multiplier and session.current_multiplier < 1.12:
            next_multiplier = round(session.current_multiplier + 0.02, 2)
            delta = round(next_multiplier - session.current_multiplier, 2)
        session.current_multiplier = next_multiplier
        session.peak_multiplier = max(session.peak_multiplier, next_multiplier)
        if delta >= 0.12:
            session.trend_label = "Surging upward"
        elif delta > 0.0:
            session.trend_label = "Climbing"
        elif delta <= -0.10:
            session.trend_label = "Dipping hard"
        else:
            session.trend_label = "Wobbling"
        session.history.append(session.current_multiplier)
        if len(session.history) > 8:
            session.history = session.history[-8:]

    async def _update_crash_message(self, session: CrashSession, view: CrashView) -> None:
        if session.message is None:
            return
        view._sync_buttons()
        with contextlib.suppress(discord.HTTPException):
            await session.message.edit(embed=self._build_crash_embed(session), view=view)

    async def _resolve_crash_loss(self, session: CrashSession, view: CrashView, *, note: str) -> None:
        async with session.lock:
            if session.resolved:
                return
            session.resolved = True
            session.cashed_out = False
            session.result_note = note
            self._crash_sessions.pop(self._blackjack_session_key(session.guild_id, session.user_id), None)
            await self._run_db(
                self._record_crash_result_sync,
                session.guild_id,
                session.user_id,
                session.display_name,
                False,
                0,
            )
            await self._update_crash_message(session, view)
            view.stop()

    async def _run_crash_loop(self, session: CrashSession, view: CrashView) -> None:
        try:
            while not session.resolved:
                await asyncio.sleep(CRASH_TICK_SECONDS)
                async with session.lock:
                    if session.resolved:
                        break
                    self._advance_crash_multiplier(session)
                    if session.current_multiplier >= session.crash_point:
                        session.current_multiplier = session.crash_point
                        session.peak_multiplier = max(session.peak_multiplier, session.current_multiplier)
                        session.history.append(session.current_multiplier)
                        if len(session.history) > 8:
                            session.history = session.history[-8:]
                        session.resolved = True
                        session.cashed_out = False
                        session.trend_label = "Flight ended"
                        session.result_note = f"The flight broke apart at **x{session.crash_point:.2f}** before you could cash out."
                        self._crash_sessions.pop(self._blackjack_session_key(session.guild_id, session.user_id), None)
                        await self._run_db(
                            self._record_crash_result_sync,
                            session.guild_id,
                            session.user_id,
                            session.display_name,
                            False,
                            0,
                        )
                        await self._update_crash_message(session, view)
                        view.stop()
                        return
                await self._update_crash_message(session, view)
        except Exception:
            logger.exception("Crash loop failed for guild=%s user=%s", session.guild_id, session.user_id)
            await self._run_db(
                self._settle_blackjack_payout_sync,
                session.guild_id,
                session.user_id,
                session.display_name,
                session.bet,
            )
            await self._resolve_crash_loss(session, view, note="The crash game stalled, so your bet was returned safely.")

    def _build_pet_shop_embed(self, *, owned_keys: Optional[set[str]] = None) -> discord.Embed:
        embed = discord.Embed(
            title="Cadis Etrama Di Raizel",
            description="Pet companions with light passive bonuses. Use `buypet <name>` to adopt one.",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Pet Shop")
        lines = []
        owned = owned_keys or set()
        for pet in PETS:
            marker = "Owned" if str(pet["key"]) in owned else f"{int(pet['price'])} coins"
            lines.append(
                f"{pet['emoji']} **{pet['name']}** — `{marker}`\n"
                f"{pet['description']}\n"
                f"Bonus: {pet['bonus_text']}"
            )
        for chunk in _chunk_lines(lines, max_lines=3):
            embed.add_field(name="Available Pets", value="\n\n".join(chunk), inline=False)
        embed.set_footer(text="Use `equippet <name>` after buying a pet.")
        return embed

    def _build_my_pet_embed(self, *, owned_rows: list[dict[str, Any]]) -> discord.Embed:
        embed = discord.Embed(
            title="Cadis Etrama Di Raizel",
            description="Your current pet roster.",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Pets")
        if not owned_rows:
            embed.add_field(name="Owned Pets", value="You do not own any pets yet. Open `shop` and browse the Pets category.", inline=False)
            return embed
        lines = []
        equipped_line = "No pet equipped."
        for row in owned_rows:
            pet = PET_LOOKUP.get(_normalize_lookup(str(row["pet_key"])))
            if pet is None:
                continue
            status = "Equipped" if int(row.get("equipped", 0)) else "Owned"
            line = f"{pet['emoji']} **{pet['name']}** — {pet['bonus_text']} ({status})"
            lines.append(line)
            if int(row.get("equipped", 0)):
                equipped_line = f"{pet['emoji']} **{pet['name']}** — {pet['description']}"
        embed.add_field(name="Equipped", value=equipped_line, inline=False)
        embed.add_field(name="Collection", value="\n".join(lines), inline=False)
        embed.set_footer(text="Use `feedpet`, `equippet <name>`, `unequippet`, or browse pets in `shop`.")
        return embed

    def _build_quick_earn_embed(
        self,
        *,
        last_action: Optional[str] = None,
        last_result: Optional[str] = None,
    ) -> discord.Embed:
        embed = discord.Embed(
            title="Quick Earn Panel",
            description=(
                "A one-click shortcut for the standard earning commands.\n"
                "Typed commands still work exactly the same."
            ),
            color=EMBED_COLOR,
        )
        embed.set_author(name="Cadis Etrama Di Raizel")
        lines = [
            f"{entry['emoji']} `{entry['key']}`"
            for entry in QUICK_EARN_ACTIONS
        ]
        for chunk in _chunk_lines(lines, max_lines=4):
            embed.add_field(name="Actions", value=" • ".join(chunk), inline=False)
        embed.add_field(
            name="How It Works",
            value="Click any button below to run the same earning logic, cooldowns, rewards, and persistence as the typed command.",
            inline=False,
        )
        if last_action:
            embed.add_field(name="Last Action", value=f"**{last_action}**", inline=True)
        if last_result:
            embed.add_field(name="Last Result", value=last_result, inline=True)
        embed.set_footer(text="Only the user who opened this panel can use it.")
        return embed

    async def _dispatch_quick_earn_action(self, message: discord.Message, action_key: str) -> str:
        handler = getattr(self, f"{action_key}_func", None)
        if not callable(handler):
            raise ValueError(f"Unknown earn action: {action_key}")
        return await handler(message)

    def _build_duel_embed(self, session: DuelSession) -> discord.Embed:
        embed = discord.Embed(
            title="Duel",
            description="Rock / Paper / Scissors. Best of 3. Both wagers are already locked in.",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Cadis Etrama Di Raizel")
        embed.add_field(name="Player 1", value=session.challenger_name, inline=True)
        embed.add_field(name="Player 2", value=session.target_name, inline=True)
        embed.add_field(name="Pot", value=f"{session.bet * 2} coins", inline=True)
        embed.add_field(name="Round", value=str(session.current_round), inline=True)
        embed.add_field(name="Score", value=f"{session.challenger_score} - {session.target_score}", inline=True)
        choices_locked = int(bool(session.challenger_choice)) + int(bool(session.target_choice))
        embed.add_field(name="Choices Locked", value=f"{choices_locked}/2", inline=True)
        if session.result_note:
            embed.add_field(name="Result", value=session.result_note, inline=False)
        else:
            embed.add_field(name="Status", value="Waiting for both players to choose.", inline=False)
        if session.resolved and session.winner_id is not None:
            winner_name = session.challenger_name if session.winner_id == session.challenger_id else session.target_name
            embed.add_field(name="Final", value=f"**{winner_name} wins the duel and takes {session.payout_amount} coins.**", inline=False)
        elif session.resolved and session.refunded:
            embed.add_field(name="Final", value="**The duel expired. Both wagers were returned.**", inline=False)
        embed.set_footer(text="Only the two duel players can use these buttons.")
        return embed

    def _build_dungeon_embed(self, session: DungeonSession) -> discord.Embed:
        fighter = self._get_dungeon_fighter(session.fighter_key)
        fighter_label = f"{fighter.get('name', 'Unchosen')} {fighter.get('emoji', '')}".strip()
        enemy_label = session.enemy_name or "Awaiting fighter selection"
        current_cashout = max(int(session.bet), int(session.banked_payout))
        earned_levels = max(0, current_cashout - int(session.bet))
        companion = self._get_dungeon_companion(session.companion_key)
        if companion:
            companion_status = f"{companion['name']} (+{int(round(float(companion['bonus']) * 100))}% win chance)"
        else:
            companion_status = "None"
        embed = discord.Embed(
            title="Dungeon Run",
            description="A fantasy dungeon climb with escalating danger and a rising reward bank.",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Cadis Etrama Di Raizel")
        embed.add_field(name="Fighter", value=fighter_label, inline=True)
        embed.add_field(name="Level", value=f"{session.level}/10", inline=True)
        embed.add_field(name="Bet", value=_format_coin_reward(session.bet), inline=True)
        embed.add_field(name="Enemy", value=enemy_label, inline=True)
        embed.add_field(name="Earned Levels", value=f"{earned_levels} coins", inline=True)
        embed.add_field(name="Leave Cashout", value=f"{current_cashout} coins", inline=True)
        embed.add_field(name="Lives", value=f"{int(session.life_charges)}/{DUNGEON_LIFE_MAX}", inline=True)
        embed.add_field(name="Companion", value=companion_status, inline=True)
        embed.add_field(name="Final Goal", value=f"{int(round(session.bet * 4))} coins", inline=True)
        if session.result_note:
            embed.add_field(name="Result", value=session.result_note, inline=False)
        elif session.fighter_key is None:
            embed.add_field(name="Choose Fighter", value="Pick **Rookie 🧛** or **FighterJit 🦄** to begin the run.", inline=False)
        else:
            if session.level <= 1:
                status_text = (
                    "Press **Attack** to commit to the first floor, or **Leave** to cancel cleanly and take your bet back.\n"
                    "You can also buy up to 3 life charges or call one companion before the run turns rough."
                )
            else:
                status_text = (
                    "Press **Attack** to push deeper, or **Leave** to cash out your original bet plus the rewards from cleared floors.\n"
                    "Lives revive you on defeat, and companions add +10% or +20% win chance for this run."
                )
            embed.add_field(name="Status", value=status_text, inline=False)
        embed.set_footer(text="Only the initiating player can control this run.")
        return embed

    async def _resolve_duel_round(self, session: DuelSession) -> None:
        challenger_choice = session.challenger_choice or ""
        target_choice = session.target_choice or ""
        beats = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
        if challenger_choice == target_choice:
            session.result_note = (
                f"{session.challenger_name} chose **{challenger_choice.title()}** and "
                f"{session.target_name} chose **{target_choice.title()}**. The round is a tie."
            )
            session.current_round += 1
            session.challenger_choice = None
            session.target_choice = None
            return
        challenger_wins = beats[challenger_choice] == target_choice
        if challenger_wins:
            session.challenger_score += 1
            winner_name = session.challenger_name
        else:
            session.target_score += 1
            winner_name = session.target_name
        session.result_note = (
            f"{session.challenger_name} chose **{challenger_choice.title()}**.\n"
            f"{session.target_name} chose **{target_choice.title()}**.\n"
            f"**{winner_name} wins round {session.current_round}.**"
        )
        if session.challenger_score >= 2 or session.target_score >= 2:
            session.resolved = True
            session.winner_id = session.challenger_id if session.challenger_score > session.target_score else session.target_id
            winner_name = session.challenger_name if session.winner_id == session.challenger_id else session.target_name
            loser_id = session.target_id if session.winner_id == session.challenger_id else session.challenger_id
            loser_name = session.target_name if session.winner_id == session.challenger_id else session.challenger_name
            payout_amount = session.bet * 2
            payout_result = await self._run_db(
                self._settle_duel_winner_sync,
                session.guild_id,
                session.winner_id,
                winner_name,
                payout_amount,
            )
            session.payout_amount = payout_amount if payout_result.get("status") == "success" else 0
            await self._run_db(
                self._record_duel_win_sync,
                session.guild_id,
                session.winner_id,
                winner_name,
                payout_amount,
            )
            await self._run_db(
                self._record_duel_loss_sync,
                session.guild_id,
                loser_id,
                loser_name,
            )
            self._close_duel_session(session)
        else:
            session.current_round += 1
            session.challenger_choice = None
            session.target_choice = None

    def _close_duel_session(self, session: DuelSession) -> None:
        self._duel_sessions.pop((session.guild_id, session.challenger_id), None)
        self._duel_sessions.pop((session.guild_id, session.target_id), None)

    async def _refund_duel_session(self, session: DuelSession, *, note: str) -> None:
        if session.resolved:
            return
        await self._run_db(
            self._refund_duel_bets_sync,
            session.guild_id,
            session.challenger_id,
            session.challenger_name,
            session.target_id,
            session.target_name,
            session.bet,
        )
        session.resolved = True
        session.refunded = True
        session.result_note = note
        self._close_duel_session(session)

    def _dungeon_level_cap(self, session: DungeonSession) -> int:
        return len(ANCIENT_DUNGEON_BOSSES) if session.ancient_phase else len(DUNGEON_REWARD_MULTIPLIERS)

    def _get_dungeon_reward_amount(self, *, base_reward: int, level: int, ancient: bool = False) -> int:
        multipliers = ANCIENT_DUNGEON_REWARD_MULTIPLIERS if ancient else DUNGEON_REWARD_MULTIPLIERS
        safe_index = max(0, min(int(level) - 1, len(multipliers) - 1))
        base_multiplier = float(multipliers[safe_index])
        # Apply the +25% reward increase exactly once from the original base reward reference.
        final_multiplier = base_multiplier * DUNGEON_REWARD_BONUS_MULTIPLIER
        return int(round(int(base_reward) * final_multiplier))

    def _pick_dungeon_enemy(self, level: int, *, ancient: bool = False) -> str:
        if ancient:
            safe_index = max(0, min(int(level) - 1, len(SAFE_ANCIENT_DUNGEON_BOSSES) - 1))
            return SAFE_ANCIENT_DUNGEON_BOSSES[safe_index]
        pool = [
            creature["name"]
            for creature in DUNGEON_CREATURES
            if int(creature["min_level"]) <= level <= int(creature["max_level"])
        ]
        if not pool:
            pool = [str(creature["name"]) for creature in DUNGEON_CREATURES]
        return random.choice(pool)

    def _enter_ancient_dungeon(self, session: DungeonSession) -> None:
        session.awaiting_ancient_choice = False
        session.ancient_phase = True
        session.level = 1
        session.enemy_name = self._pick_dungeon_enemy(1, ancient=True)
        session.banked_payout = 0
        session.result_note = (
            "You step beyond the broken gate into the Ancient 5-Level Dungeon.\n"
            f"Normal payout secured: **{session.normal_payout_amount} coins**.\n"
            f"Boss ahead: **{session.enemy_name}**."
        )

    async def _decline_ancient_dungeon(self, session: DungeonSession, *, note: str) -> None:
        session.awaiting_ancient_choice = False
        session.resolved = True
        session.result_note = note
        self._dungeon_sessions.pop((session.guild_id, session.user_id), None)

    def _get_dungeon_fighter(self, fighter_key: Optional[str]) -> dict[str, Any]:
        return SAFE_DUNGEON_FIGHTER_LOOKUP.get(str(fighter_key or "").strip().lower(), SAFE_DUNGEON_FIGHTER_LOOKUP["rookie"])

    def _get_dungeon_win_line(self, *, fighter_name: str, enemy_name: str, ancient: bool) -> str:
        lines = SAFE_ANCIENT_DUNGEON_WIN_LINES if ancient else SAFE_DUNGEON_WIN_LINES
        return random.choice(lines).format(fighter_name=fighter_name, enemy_name=enemy_name)

    def _get_dungeon_loss_line(self, *, fighter_name: str, enemy_name: str, ancient: bool) -> str:
        lines = SAFE_ANCIENT_DUNGEON_LOSS_LINES if ancient else SAFE_DUNGEON_LOSS_LINES
        return random.choice(lines).format(fighter_name=fighter_name, enemy_name=enemy_name)

    def _get_ancient_completion_line(self) -> str:
        return random.choice(SAFE_ANCIENT_DUNGEON_COMPLETION_LINES)

    async def _finish_dungeon_success(self, session: DungeonSession, *, note: str) -> None:
        payout_result = await self._run_db(
            self._settle_blackjack_payout_sync,
            session.guild_id,
            session.user_id,
            session.display_name,
            session.banked_payout,
        )
        session.resolved = True
        session.result_note = note
        if payout_result.get("status") == "success":
            await self._run_db(
                self._record_dungeon_win_sync,
                session.guild_id,
                session.user_id,
                session.display_name,
                session.banked_payout,
                session.level,
            )
        self._dungeon_sessions.pop((session.guild_id, session.user_id), None)

    async def _fail_dungeon_session(self, session: DungeonSession, *, note: str) -> None:
        session.resolved = True
        session.result_note = note
        await self._run_db(
            self._record_dungeon_failure_sync,
            session.guild_id,
            session.user_id,
            session.display_name,
        )
        self._dungeon_sessions.pop((session.guild_id, session.user_id), None)

    async def _leave_dungeon_session(self, session: DungeonSession, *, note: Optional[str] = None) -> None:
        if session.resolved:
            return
        payout_amount = max(int(session.bet), int(session.banked_payout))
        earned_amount = max(0, payout_amount - int(session.bet))
        await self._run_db(
            self._settle_blackjack_payout_sync,
            session.guild_id,
            session.user_id,
            session.display_name,
            payout_amount,
        )
        session.resolved = True
        if session.level <= 1 or earned_amount <= 0:
            session.result_note = note or (
                f"You backed out before committing to the dungeon.\n"
                f"Original bet returned: **{session.bet} coins**\n"
                f"Earned from cleared levels: **0 coins**\n"
                f"Total cashout: **{payout_amount} coins**"
            )
        else:
            session.result_note = note or (
                f"You fled the dungeon and secured your progress.\n"
                f"Original bet returned: **{session.bet} coins**\n"
                f"Earned from cleared levels: **{earned_amount} coins**\n"
                f"Total cashout: **{payout_amount} coins**"
            )
        self._dungeon_sessions.pop((session.guild_id, session.user_id), None)

    async def _refund_dungeon_session(self, session: DungeonSession, *, note: str) -> None:
        await self._run_db(
            self._settle_blackjack_payout_sync,
            session.guild_id,
            session.user_id,
            session.display_name,
            session.bet,
        )
        session.resolved = True
        session.result_note = note
        self._dungeon_sessions.pop((session.guild_id, session.user_id), None)

    async def _resolve_dungeon_attack(self, session: DungeonSession) -> None:
        fighter = self._get_dungeon_fighter(session.fighter_key)
        profile = await self._run_db(
            self._get_income_snapshot_sync,
            session.guild_id,
            session.user_id,
            session.display_name,
        )
        pet_bonus = float(profile.get("dungeon_bonus", 0.0))
        item_bonus = 0.0
        if isinstance(profile.get("item_effects"), dict):
            item_bonus = float(profile["item_effects"].get("action_bonus", {}).get("dungeon", 0.0))
        companion = self._get_dungeon_companion(session.companion_key)
        companion_bonus = float(companion.get("bonus", 0.0)) if companion else 0.0
        chance = min(
            0.95,
            max(
                0.57,
                0.83
                - ((session.level - 1) * 0.015)
                + float(fighter.get("bonus_chance", 0.0))
                + pet_bonus
                + item_bonus
                + companion_bonus,
            ),
        )
        if random.random() < chance:
            session.banked_payout = int(round(session.bet * DUNGEON_REWARD_MULTIPLIERS[session.level - 1]))
            win_line = random.choice(DUNGEON_WIN_LINES).format(
                fighter_name=f"{fighter['name']} {fighter['emoji']}",
                enemy_name=session.enemy_name or "enemy",
            )
            if session.level >= 10:
                await self._finish_dungeon_success(
                    session,
                    note=f"{win_line}\n**The run is complete. Final payout: {session.banked_payout} coins.**",
                )
                return
            session.level += 1
            session.enemy_name = self._pick_dungeon_enemy(session.level)
            session.result_note = f"{win_line}\nReward bank climbed to **{session.banked_payout} coins**."
            return
        loss_line = random.choice(DUNGEON_LOSS_LINES).format(
            fighter_name=f"{fighter['name']} {fighter['emoji']}",
            enemy_name=session.enemy_name or "enemy",
        )
        if session.life_charges > 0:
            consume_result = await self._run_db(
                self._consume_dungeon_life_sync,
                session.guild_id,
                session.user_id,
                session.display_name,
            )
            if consume_result.get("status") == "success":
                session.life_charges = int(consume_result.get("lives", 0))
                session.result_note = (
                    f"{loss_line}\n"
                    f"A life charge was consumed. The run continues.\n"
                    f"Lives remaining: **{session.life_charges}/{DUNGEON_LIFE_MAX}**"
                )
                return
        await self._fail_dungeon_session(session, note=f"{loss_line}\nYou fell in battle and had no life charges left.")

    def _build_dungeon_embed(self, session: DungeonSession) -> discord.Embed:
        fighter = DUNGEON_FIGHTER_LOOKUP.get(session.fighter_key or "", {})
        fighter_label = f"{fighter.get('name', 'Unchosen')} {fighter.get('emoji', '')}".strip()
        phase_title = "Ancient Dungeon" if session.ancient_phase else "Dungeon Run"
        phase_description = (
            "An elite five-floor gauntlet of fixed ancient bosses."
            if session.ancient_phase
            else "A fantasy dungeon climb with escalating danger and a rising reward bank."
        )
        if session.ancient_phase and session.enemy_name:
            enemy_label = f"{session.enemy_name}\nAncient Boss"
        else:
            enemy_label = session.enemy_name or "Awaiting fighter selection"
        current_cashout = int(session.banked_payout) if session.ancient_phase else max(int(session.bet), int(session.banked_payout))
        earned_levels = int(session.banked_payout) if session.ancient_phase else max(0, current_cashout - int(session.bet))
        level_cap = self._dungeon_level_cap(session)
        companion = self._get_dungeon_companion(session.companion_key)
        if companion:
            companion_status = f"{companion['name']} (+{int(round(float(companion['bonus']) * 100))}% win chance)"
        else:
            companion_status = "None"
        embed = discord.Embed(title=phase_title, description=phase_description, color=EMBED_COLOR)
        embed.set_author(name="Cadis Etrama Di Raizel")
        embed.add_field(name="Fighter", value=fighter_label, inline=True)
        embed.add_field(name="Level", value=f"{session.level}/{level_cap}" + (" Ancient" if session.ancient_phase else ""), inline=True)
        embed.add_field(name="Base Bet", value=_format_coin_reward(session.bet), inline=True)
        embed.add_field(name="Enemy", value=enemy_label, inline=True)
        embed.add_field(name="Earned Levels", value=f"{earned_levels} coins", inline=True)
        embed.add_field(name="Leave Cashout", value=f"{current_cashout} coins", inline=True)
        embed.add_field(name="Lives", value=f"{int(session.life_charges)}/{DUNGEON_LIFE_MAX}", inline=True)
        embed.add_field(name="Companion", value=companion_status, inline=True)
        embed.add_field(
            name="Final Goal",
            value=f"{self._get_dungeon_reward_amount(base_reward=session.bet, level=level_cap, ancient=session.ancient_phase)} coins",
            inline=True,
        )
        if session.normal_payout_amount > 0:
            embed.add_field(name="Normal Payout Secured", value=f"{session.normal_payout_amount} coins", inline=True)
        if session.result_note:
            embed.add_field(name="Result", value=session.result_note, inline=False)
        if session.awaiting_ancient_choice:
            embed.add_field(
                name="Ancient Gate",
                value=(
                    "You have earned the right to enter the Ancient 5-Level Dungeon.\n"
                    "Choose **Enter Ancient Dungeon** to continue, or **Decline** to end cleanly."
                ),
                inline=False,
            )
        elif session.fighter_key is None:
            embed.add_field(
                name="Choose Fighter",
                value="Pick **Rookie \U0001F9DB** or **FighterJit \U0001F984** to begin the run.",
                inline=False,
            )
        else:
            if session.ancient_phase:
                status_text = (
                    "Press **Attack** to challenge the next Ancient boss, or **Leave** to cash out your Ancient reward bank.\n"
                    "Ancient rewards are always calculated from your original entered dungeon amount."
                )
            elif session.level <= 1:
                status_text = (
                    "Press **Attack** to commit to the first floor, or **Leave** to cancel cleanly and take your bet back.\n"
                    "You can also buy up to 3 life charges or call one companion before the run turns rough."
                )
            else:
                status_text = (
                    "Press **Attack** to push deeper, or **Leave** to cash out your original bet plus the rewards from cleared floors.\n"
                    "Lives revive you on defeat, and companions add +10% or +20% win chance for this run."
                )
            embed.add_field(name="Status", value=status_text, inline=False)
        embed.set_footer(text="Only the initiating player can control this run.")
        return embed

    async def _finish_dungeon_success(self, session: DungeonSession, *, note: str) -> None:
        payout_amount = int(session.banked_payout)
        payout_result = await self._run_db(
            self._settle_blackjack_payout_sync,
            session.guild_id,
            session.user_id,
            session.display_name,
            payout_amount,
        )
        if payout_result.get("status") == "success":
            cleared_level = session.level if not session.ancient_phase else len(ANCIENT_DUNGEON_BOSSES)
            await self._run_db(
                self._record_dungeon_win_sync,
                session.guild_id,
                session.user_id,
                session.display_name,
                payout_amount,
                cleared_level,
            )
        if session.ancient_phase:
            session.resolved = True
            combined_total = int(session.normal_payout_amount) + payout_amount
            completion_line = self._get_ancient_completion_line()
            session.result_note = (
                f"{note}\n"
                f"**{completion_line}**\n"
                f"**Ancient payout secured: {payout_amount} coins.**\n"
                f"**Combined dungeon total: {combined_total} coins.**"
            )
            self._dungeon_sessions.pop((session.guild_id, session.user_id), None)
            return
        session.normal_payout_amount = payout_amount
        session.awaiting_ancient_choice = True
        session.result_note = (
            f"{note}\n"
            f"**Normal dungeon payout secured: {payout_amount} coins.**\n"
            "You have earned the right to enter the Ancient 5-Level Dungeon. Do you want to enter?"
        )

    async def _leave_dungeon_session(self, session: DungeonSession, *, note: Optional[str] = None) -> None:
        if session.resolved:
            return
        if session.ancient_phase:
            payout_amount = max(0, int(session.banked_payout))
            if payout_amount > 0:
                await self._run_db(
                    self._settle_blackjack_payout_sync,
                    session.guild_id,
                    session.user_id,
                    session.display_name,
                    payout_amount,
                )
            session.resolved = True
            session.result_note = note or (
                f"You left the Ancient Dungeon with your gains intact.\n"
                f"Normal payout already secured: **{session.normal_payout_amount} coins**\n"
                f"Ancient rewards earned: **{payout_amount} coins**\n"
                f"Combined total: **{session.normal_payout_amount + payout_amount} coins**"
            )
            self._dungeon_sessions.pop((session.guild_id, session.user_id), None)
            return
        payout_amount = max(int(session.bet), int(session.banked_payout))
        earned_amount = max(0, payout_amount - int(session.bet))
        await self._run_db(
            self._settle_blackjack_payout_sync,
            session.guild_id,
            session.user_id,
            session.display_name,
            payout_amount,
        )
        session.resolved = True
        if session.level <= 1 or earned_amount <= 0:
            session.result_note = note or (
                f"You backed out before committing to the dungeon.\n"
                f"Original bet returned: **{session.bet} coins**\n"
                f"Earned from cleared levels: **0 coins**\n"
                f"Total cashout: **{payout_amount} coins**"
            )
        else:
            session.result_note = note or (
                f"You fled the dungeon and secured your progress.\n"
                f"Original bet returned: **{session.bet} coins**\n"
                f"Earned from cleared levels: **{earned_amount} coins**\n"
                f"Total cashout: **{payout_amount} coins**"
            )
        self._dungeon_sessions.pop((session.guild_id, session.user_id), None)

    async def _resolve_dungeon_attack(self, session: DungeonSession) -> None:
        fighter = DUNGEON_FIGHTER_LOOKUP.get(session.fighter_key or "", DUNGEON_FIGHTER_LOOKUP["rookie"])
        profile = await self._run_db(
            self._get_income_snapshot_sync,
            session.guild_id,
            session.user_id,
            session.display_name,
        )
        pet_bonus = float(profile.get("dungeon_bonus", 0.0))
        item_bonus = 0.0
        if isinstance(profile.get("item_effects"), dict):
            item_bonus = float(profile["item_effects"].get("action_bonus", {}).get("dungeon", 0.0))
        companion = self._get_dungeon_companion(session.companion_key)
        companion_bonus = float(companion.get("bonus", 0.0)) if companion else 0.0
        if session.ancient_phase:
            chance = min(
                0.90,
                max(
                    0.38,
                    0.74
                    - ((session.level - 1) * 0.045)
                    + float(fighter.get("bonus_chance", 0.0))
                    + pet_bonus
                    + item_bonus
                    + companion_bonus,
                ),
            )
        else:
            chance = min(
                0.95,
                max(
                    0.57,
                    0.83
                    - ((session.level - 1) * 0.015)
                    + float(fighter.get("bonus_chance", 0.0))
                    + pet_bonus
                    + item_bonus
                    + companion_bonus,
                ),
            )
        if random.random() < chance:
            session.banked_payout = self._get_dungeon_reward_amount(
                base_reward=session.bet,
                level=session.level,
                ancient=session.ancient_phase,
            )
            win_line = self._get_dungeon_win_line(
                fighter_name=f"{fighter['name']} {fighter['emoji']}",
                enemy_name=session.enemy_name or "enemy",
                ancient=session.ancient_phase,
            )
            if session.level >= self._dungeon_level_cap(session):
                if session.ancient_phase:
                    await self._finish_dungeon_success(
                        session,
                        note=f"{win_line}\n**Ancient payout ready: {session.banked_payout} coins.**",
                    )
                else:
                    await self._finish_dungeon_success(
                        session,
                        note=f"{win_line}\n**Dungeon cleared. Payout ready: {session.banked_payout} coins.**",
                    )
                return
            session.level += 1
            session.enemy_name = self._pick_dungeon_enemy(session.level, ancient=session.ancient_phase)
            if session.ancient_phase:
                session.result_note = (
                    f"{win_line}\n"
                    f"**Ancient reward bank:** {session.banked_payout} coins\n"
                    f"Next boss: **{session.enemy_name}**."
                )
            else:
                session.result_note = (
                    f"{win_line}\n"
                    f"**Reward bank:** {session.banked_payout} coins"
                )
            return
        loss_line = self._get_dungeon_loss_line(
            fighter_name=f"{fighter['name']} {fighter['emoji']}",
            enemy_name=session.enemy_name or "enemy",
            ancient=session.ancient_phase,
        )
        if session.life_charges > 0:
            consume_result = await self._run_db(
                self._consume_dungeon_life_sync,
                session.guild_id,
                session.user_id,
                session.display_name,
            )
            if consume_result.get("status") == "success":
                session.life_charges = int(consume_result.get("lives", 0))
                session.result_note = (
                    f"{loss_line}\n"
                    f"**A life charge was consumed. The run continues.**\n"
                    f"Lives remaining: **{session.life_charges}/{DUNGEON_LIFE_MAX}**"
                )
                return
        await self._fail_dungeon_session(session, note=f"{loss_line}\nYou fell in battle and had no life charges left.")

    def _available_help_categories(self) -> list[tuple[str, str]]:
        return [
            ("playback", "Playback"),
            ("filters", "Filters"),
            ("history", "History"),
            ("minigame", "Minigame"),
            ("moderation", "Moderation"),
            ("profile_xp", "Profile / XP"),
            ("avatar_tools", "Avatar Tools"),
            ("text_tools", "Text Tools"),
        ]

    def build_help_embed(self, category: Optional[str] = None) -> discord.Embed:
        title = "Cadis Etrama Di Raizel"
        if category is None:
            embed = discord.Embed(
                title=title,
                description="A clean interactive guide for the current bot systems.\nSelect a category below to view commands.",
                color=EMBED_COLOR,
            )
            embed.set_author(name="Interactive Help Menu")
            embed.add_field(
                name="Categories",
                value="\n".join(f"- {label}" for _, label in self._available_help_categories()),
                inline=False,
            )
            embed.set_footer(text="Choose a category with the buttons below.")
            return embed

        pages = {
            "playback": {
                "description": "Core music playback, queue, seek, and playlist commands.",
                "commands": "`play <song>`\n`pause` `resume` `skip` `stop`\n`queue` `shuffle` `clearqueue`\n`seek 1:20` `forward 10` `back 10`\n`nowplaying` `np`\n`play <playlist url>` `playlist <url>`",
                "examples": "`play Breaking Benjamin`\n`çal not strong enough`\n`forward 15`\n`playlist <url>`",
            },
            "filters": {
                "description": "Real FFmpeg-based audio effects with per-filter off support.",
                "commands": "`nightcore` `bassboost` `slow` `reverb` `echo`\n`speed 1.15` `pitch 0.9`\n`lowpass 300` `highpass 200`\n`equalizer 100 3` `show filters`\n`nightcore off` `reverb off`\n`filter off` `reset filters`",
                "examples": "`nightcore`\n`speed 1.25`\n`lowpass 300`\n`bassboost off`",
            },
            "history": {
                "description": "See per-user song history and most-played tracks.",
                "commands": "`history @user` `history me`\n`mostplayed @user` `mostplayed me`\n`songs @user` `favorites @user`\n`history @user page 2`\n`mostplayed me 2`",
                "examples": "`history @Raizel`\n`geçmişim`\n`mostplayed me`",
            },
            "minigame": {
                "description": "English-only economy, jobs, inventory, pets, and live-risk minigames.",
                "commands": "`balance` `bal` `wallet`\n`jobs` `choosejob <name>` `job choose <name>` `myjob`\n`job upgrade` `level job` `profession upgrade`\n`work` `beg` `quiz` `answer <number>`\n`fish` `hunt` `search` `mine` `deliver` `scavenge`\n`freelance` `craft` `repair` `patrol`\n`earn` `quickearn` `workpanel` `jobs panel`\n`daily` `quests` `missions`\n`achievements` `badges`\n`shop` `market` `shopview` `inventory` `buy <item>` `use <item>`\n`shop` and `shopview` both show visible item effects\n`shop` -> browse the `Pets` category for companions\n`buypet <name>` `mypet` `equippet <name>`\n`unequippet` `feedpet` `petinfo`\n`use phone` `use phone @user`\n`income` `collect` `property`\n`gamble <amount>` `bet <amount>`\n`blackjack <amount>` `bj <amount>`\n`slots <amount>` `slot <amount>` `spin <amount>`\n`crash <amount>` (live multiplier + cash out)\n`duel @user <amount>`\n`dungeon <amount>` `dungeon run <amount>` `pve <amount>`\n`dungeon` -> level 10 can unlock the Ancient 5-Level Dungeon after payout\n`steal @user` `rob @user` `heist @user`\n`gift @user <amount>` `richest`",
                "examples": "`earn`\n`shop`\n`shopview`\n`buy seal pup`\n`duel @user 500`\n`job upgrade`\n`crash 500`\n`dungeon 750`\n`heist @user`",
            },
            "moderation": {
                "description": "A small moderation page for quick channel cleanup.",
                "commands": "`purge <amount>`",
                "examples": "`purge 5`\n`purge 20`",
            },
            "profile_xp": {
                "description": "Local server XP, rank, and profile tracking.",
                "commands": "`profile` `profile @user`\n`rank` `xp` `level`\n`leaderboard` `topxp`\n`profil` `seviye` `sıralama`",
                "examples": "`profile`\n`rank @user`\n`leaderboard`",
            },
            "avatar_tools": {
                "description": "Avatar, banner, and user information tools.",
                "commands": "`avatar` `avatar @user`\n`pfp` `pp`\n`banner` `afiş`\n`userinfo` `kullanıcıbilgi`",
                "examples": "`avatar @user`\n`banner`\n`userinfo @user`",
            },
            "text_tools": {
                "description": "Local utility tools for translation, rewrite, and explain.",
                "commands": "`translate <text>` `tr <text>` `çevir <text>`\n`translate tr->en <text>` `translate en->tr <text>`\n`rewrite <text>` `rewrite formal <text>`\n`rewrite simple <text>` `rewrite verysimple <text>`\n`düzelt <text>` `yenidenyaz <text>`\n`explain <text>` `explain verysimple <text>`\n`açıkla <text>` `basitanlat <text>`",
                "examples": "`translate tr->en Merhaba dünya`\n`rewrite verysimple I lve Pinja so much`\n`explain verysimple cache invalidation is hard`",
            },
        }
        page = pages[category]
        embed = discord.Embed(title=title, description=page["description"], color=EMBED_COLOR)
        embed.set_author(name=page_key_to_title(category))
        embed.add_field(name="Commands", value=page["commands"], inline=False)
        embed.add_field(name="Examples", value=page["examples"], inline=False)
        embed.set_footer(text=f"Category: {page_key_to_title(category)}")
        return embed

    def _help_page_sections(self, category: str) -> list[tuple[str, str]]:
        pages: dict[str, list[tuple[str, str]]] = {
            "playback": [
                ("Commands", "`play <song>` `pause` `resume` `skip` `stop`\n`queue` `shuffle` `clearqueue`\n`seek 1:20` `forward 10` `back 10`\n`nowplaying` `np`\n`play <playlist url>` `playlist <url>`"),
                ("Examples", "`play Breaking Benjamin`\n`çal not strong enough`\n`forward 15`\n`playlist <url>`"),
            ],
            "filters": [
                ("Commands", "`nightcore` `bassboost` `slow` `reverb` `echo`\n`speed 1.15` `pitch 0.9`\n`lowpass 300` `highpass 200`\n`equalizer 100 3` `show filters`\n`nightcore off` `reverb off`\n`filter off` `reset filters`"),
                ("Examples", "`nightcore`\n`speed 1.25`\n`lowpass 300`\n`bassboost off`"),
            ],
            "history": [
                ("Commands", "`history @user` `history me`\n`mostplayed @user` `mostplayed me`\n`songs @user` `favorites @user`\n`history @user page 2`\n`mostplayed me 2`"),
                ("Examples", "`history @Raizel`\n`geçmişim`\n`mostplayed me`"),
            ],
            "minigame": [
                ("Economy", "`balance` `bal` `wallet`\n`daily` `quests` `missions`\n`achievements` `badges`\n`income` `collect` `property`\n`gift @user <amount>` `richest`"),
                ("Jobs", "`jobs` `choosejob <name>` `job choose <name>`\n`myjob` `job upgrade` `level job`\n`work` `beg` `quiz` `answer <number>`\n`fish` `hunt` `search` `mine`\n`deliver` `scavenge` `freelance`\n`craft` `repair` `patrol`\n`earn` `quickearn` `workpanel`"),
                ("Casino", "`gamble <amount>` `bet <amount>`\n`blackjack <amount>` `bj <amount>`\n`slots <amount>` `slot <amount>` `spin <amount>`\n`crash <amount>`"),
                ("PvP / Dungeon", "`duel @user <amount>`\n`dungeon <amount>` `dungeon run <amount>` `pve <amount>`\n`steal @user` `rob @user` `heist @user`\nDungeon note: leave cashes out your original bet plus cleared-floor rewards.\nClearing level 10 pays first, then unlocks the Ancient 5-Level Dungeon choice.\nDungeon UI also supports buying lives and activating one companion per run.\nCompanions: FighterSeal, Kelpy, Thibeault (FisherKing), Kamil, Batman, Hessa King."),
                ("Extras", "`shop` `market` `shopview`\n`inventory` `buy <item>` `use <item>`\nBrowse the `Pets` category in `shop` or `shopview`\n`buypet <name>` `mypet` `equippet <name>`\n`unequippet` `feedpet` `petinfo`\n`use phone` `use phone @user`\n`shopview` is the advanced interactive shop."),
                ("Examples", "`earn`\n`shopview`\n`buy seal pup`\n`duel @user 500`\n`job upgrade`\n`crash 500`\n`dungeon 750`\n`heist @user`"),
            ],
            "moderation": [
                ("Commands", "`purge <amount>`"),
                ("Examples", "`purge 5`\n`purge 20`"),
            ],
            "profile_xp": [
                ("Commands", "`profile` `profile @user`\n`rank` `xp` `level`\n`leaderboard` `topxp`\n`profil` `seviye` `sıralama`"),
                ("Examples", "`profile`\n`rank @user`\n`leaderboard`"),
            ],
            "avatar_tools": [
                ("Commands", "`avatar` `avatar @user`\n`pfp` `pp`\n`banner` `afiş`\n`userinfo` `kullanıcıbilgi`"),
                ("Examples", "`avatar @user`\n`banner`\n`userinfo @user`"),
            ],
            "text_tools": [
                ("Commands", "`translate <text>` `tr <text>` `çevir <text>`\n`translate tr->en <text>` `translate en->tr <text>`\n`rewrite <text>` `rewrite formal <text>`\n`rewrite simple <text>` `rewrite verysimple <text>`\n`düzelt <text>` `yenidenyaz <text>`\n`explain <text>` `explain verysimple <text>`\n`açıkla <text>` `basitanlat <text>`"),
                ("Examples", "`translate tr->en Merhaba dünya`\n`rewrite verysimple I lve Pinja so much`\n`explain verysimple cache invalidation is hard`"),
            ],
        }
        return pages.get(category, [])

    # Final help embed override: split large categories into multiple fields so
    # every field stays safely under Discord's 1024 character limit.
    def build_help_embed(self, category: Optional[str] = None) -> discord.Embed:
        title = "Cadis Etrama Di Raizel"
        if category is None:
            embed = discord.Embed(
                title=title,
                description="A clean interactive guide for the current bot systems.\nSelect a category below to view commands.",
                color=EMBED_COLOR,
            )
            embed.set_author(name="Interactive Help Menu")
            embed.add_field(
                name="Categories",
                value="\n".join(f"- {label}" for _, label in self._available_help_categories()),
                inline=False,
            )
            embed.set_footer(text="Choose a category with the buttons below.")
            return embed

        descriptions = {
            "playback": "Core music playback, queue, seek, and playlist commands.",
            "filters": "Real FFmpeg-based audio effects with per-filter off support.",
            "history": "See per-user song history and most-played tracks.",
            "minigame": "English-only economy, jobs, inventory, pets, and live-risk minigames.",
            "moderation": "A small moderation page for quick channel cleanup.",
            "profile_xp": "Local server XP, rank, and profile tracking.",
            "avatar_tools": "Avatar, banner, and user information tools.",
            "text_tools": "Local utility tools for translation, rewrite, and explain.",
        }

        embed = discord.Embed(
            title=title,
            description=descriptions.get(category, "Command reference."),
            color=EMBED_COLOR,
        )
        embed.set_author(name=page_key_to_title(category))
        for field_name, field_value in self._help_page_sections(category):
            safe_value = field_value[:1024]
            embed.add_field(name=field_name, value=safe_value, inline=False)
        embed.set_footer(text=f"Category: {page_key_to_title(category)}")
        return embed

    def _parse_translate_request(self, raw_text: str) -> tuple[str, str, str]:
        cleaned = (raw_text or "").strip()
        if not cleaned:
            raise ValueError("Usage: translate <text> or translate tr->en <text>")
        direction_match = re.match(r"^([a-z]{2})\s*->\s*([a-z]{2})\s+(.+)$", cleaned, flags=re.IGNORECASE)
        if direction_match:
            source = direction_match.group(1).lower()
            target = direction_match.group(2).lower()
            return source, target, direction_match.group(3).strip()
        if _looks_turkish_text(cleaned):
            return "tr", "en", cleaned
        return "en", "tr", cleaned

    def _parse_rewrite_request(self, raw_text: str) -> tuple[str, str]:
        content = (raw_text or "").strip()
        if not content:
            raise ValueError("Usage: rewrite <text> or rewrite verysimple <text>")
        for pattern, mode in REWRITE_MODE_PATTERNS:
            match = re.match(pattern, content, flags=re.IGNORECASE)
            if match:
                remainder = content[match.end():].strip()
                return mode, remainder
        return "clean", content

    def _apply_typo_corrections(self, text: str) -> str:
        replacements = {
            r"\blve\b": "love",
            r"\bdont\b": "don't",
            r"\bcant\b": "can't",
            r"\bdoesnt\b": "doesn't",
            r"\bdidnt\b": "didn't",
            r"\bisnt\b": "isn't",
            r"\bwasnt\b": "wasn't",
            r"\bi\b": "I",
            r"\bim\b": "I'm",
            r"\bive\b": "I've",
            r"\byoure\b": "you're",
            r"\bu\b": "you",
            r"\bur\b": "your",
            r"\bpls\b": "please",
            r"\bpls+\b": "please",
            r"\bthx\b": "thanks",
        }
        result = text
        for pattern, replacement in replacements.items():
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        return result

    def _expand_chat_shorthand(self, text: str) -> str:
        replacements = {
            r"\bu\b": "you",
            r"\bur\b": "your",
            r"\bpls\b": "please",
            r"\bplz\b": "please",
            r"\bthx\b": "thanks",
            r"\bimo\b": "in my opinion",
            r"\bidk\b": "I do not know",
            r"\bbtw\b": "by the way",
            r"\bim\b": "I'm",
        }
        result = text
        for pattern, replacement in replacements.items():
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        return result

    def _normalize_text_locally(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", (text or "").strip())
        cleaned = re.sub(r"\s+([,.;!?])", r"\1", cleaned)
        cleaned = re.sub(r"([!?.,]){2,}", lambda match: match.group(1), cleaned)
        cleaned = self._apply_typo_corrections(cleaned)
        cleaned = self._expand_chat_shorthand(cleaned)
        return cleaned

    def _capitalize_sentences(self, text: str) -> str:
        pieces = re.split(r"([.!?]\s*)", text)
        rebuilt: list[str] = []
        for index in range(0, len(pieces), 2):
            sentence = pieces[index].strip()
            separator = pieces[index + 1] if index + 1 < len(pieces) else ""
            if sentence:
                sentence = sentence[:1].upper() + sentence[1:]
            rebuilt.append(f"{sentence}{separator}")
        return "".join(rebuilt).strip()

    def _apply_formal_rewrite(self, text: str) -> str:
        replacements = {
            "can't": "cannot",
            "won't": "will not",
            "gonna": "going to",
            "wanna": "want to",
            "yeah": "yes",
            "thanks": "thank you",
        }
        result = text
        for source, target in replacements.items():
            result = re.sub(rf"\b{re.escape(source)}\b", target, result, flags=re.IGNORECASE)
        return result

    def _apply_simple_rewrite(self, text: str) -> str:
        replacements = {
            "approximately": "about",
            "utilize": "use",
            "purchase": "buy",
            "assistance": "help",
            "additional": "more",
            "regarding": "about",
            "therefore": "so",
            "however": "but",
        }
        result = text
        for source, target in replacements.items():
            result = re.sub(rf"\b{re.escape(source)}\b", target, result, flags=re.IGNORECASE)
        return result

    def _apply_verysimple_rewrite(self, text: str) -> str:
        result = self._apply_simple_rewrite(text)
        replacements = {
            "because": "since",
            "regarding": "about",
            "in order to": "to",
            "assist": "help",
            "purchase": "buy",
            "additional": "extra",
            "everything": "a lot",
            "means everything to me": "matters to me a lot",
        }
        for source, target in replacements.items():
            result = re.sub(rf"\b{re.escape(source)}\b", target, result, flags=re.IGNORECASE)
        result = re.sub(r"\s*,\s*", ". ", result)
        result = re.sub(r"\s{2,}", " ", result)
        return result.strip()

    # This is intentionally a lightweight deterministic utility, not an LLM rewrite.
    def _rewrite_text(self, raw_text: str, mode: str) -> str:
        rewritten = self._normalize_text_locally(raw_text)
        rewritten = self._capitalize_sentences(rewritten)
        if mode == "formal":
            rewritten = self._apply_formal_rewrite(rewritten)
        elif mode == "simple":
            rewritten = self._apply_simple_rewrite(rewritten)
        elif mode == "verysimple":
            rewritten = self._apply_verysimple_rewrite(rewritten)
            rewritten = self._capitalize_sentences(rewritten)
        return rewritten

    # This is a local simplifier that uses deterministic sentence cleanup rules.
    def _explain_text(self, raw_text: str, mode: str) -> str:
        simplified = self._normalize_text_locally(raw_text)
        replacements = {
            "utilize": "use",
            "approximately": "about",
            "demonstrate": "show",
            "obtain": "get",
            "assist": "help",
            "therefore": "so",
            "however": "but",
            "regarding": "about",
            "additional": "extra",
        }
        if mode == "verysimple":
            replacements.update(
                {
                    "complex": "hard",
                    "efficient": "fast",
                    "maintain": "keep",
                    "required": "needed",
                }
            )
        for source, target in replacements.items():
            simplified = re.sub(rf"\b{re.escape(source)}\b", target, simplified, flags=re.IGNORECASE)
        simplified = self._capitalize_sentences(simplified)
        sentences = [part.strip() for part in re.split(r"[.!?]+", simplified) if part.strip()]
        if mode == "verysimple":
            return "\n".join(f"- {sentence}" for sentence in sentences[:6]) or simplified
        if len(sentences) <= 1:
            return simplified
        return "\n".join(f"{index}. {sentence}" for index, sentence in enumerate(sentences[:6], start=1))

    def _choose_job_sync(self, guild_id: int, user_id: int, display_name: str, profession_key: str) -> bool:
        with self._connect_db() as conn:
            self._prepare_profile_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name)
            conn.execute(
                "UPDATE economy_profiles SET profession = ?, last_known_name = ?, updated_at = ? WHERE guild_id = ? AND user_id = ?",
                (profession_key, display_name, _utcnow().isoformat(), guild_id, user_id),
            )
            self._ensure_profession_progress_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                profession_key=profession_key,
            )
        return True

    def _attempt_profession_upgrade_conn(
        self,
        conn: sqlite3.Connection,
        *,
        guild_id: int,
        user_id: int,
        display_name: str,
        profession_key: str,
        stat_key: str = "job_upgrades",
    ) -> dict[str, Any]:
        profession = self._resolve_profession(profession_key)
        progress = self._get_profession_progress_conn(
            conn,
            guild_id=guild_id,
            user_id=user_id,
            profession_key=profession_key,
        )
        level = int(progress["level"])
        xp = int(progress["xp"])
        if level >= PROFESSION_LEVEL_CAP:
            return {"status": "max", "profession": profession["name"], "level": level}
        required_xp = self._profession_xp_required(level)
        upgrade_cost = self._profession_upgrade_cost(level)
        if xp < required_xp:
            return {
                "status": "xp_needed",
                "profession": profession["name"],
                "level": level,
                "xp": xp,
                "required_xp": required_xp,
                "cost": upgrade_cost,
            }
        wallet = self._get_wallet_conn(conn, guild_id=guild_id, user_id=user_id)
        if wallet < upgrade_cost:
            return {
                "status": "insufficient",
                "profession": profession["name"],
                "level": level,
                "wallet": wallet,
                "cost": upgrade_cost,
                "xp": xp,
                "required_xp": required_xp,
            }
        ok, new_wallet = self._adjust_wallet_conn(
            conn,
            guild_id=guild_id,
            user_id=user_id,
            display_name=display_name,
            delta=-upgrade_cost,
        )
        if not ok:
            return {"status": "error"}
        conn.execute(
            """
            UPDATE economy_profession_progress
            SET level = level + 1,
                xp = xp - ?,
                updated_at = ?
            WHERE guild_id = ? AND user_id = ? AND profession_key = ?
            """,
            (required_xp, _utcnow().isoformat(), guild_id, user_id, profession_key),
        )
        new_progress = self._get_profession_progress_conn(
            conn,
            guild_id=guild_id,
            user_id=user_id,
            profession_key=profession_key,
        )
        self._record_progress_event_conn(
            conn,
            guild_id=guild_id,
            user_id=user_id,
            display_name=display_name,
            stat_updates={stat_key: 1},
        )
        return {
            "status": "success",
            "profession": profession["name"],
            "level": int(new_progress["level"]),
            "xp": int(new_progress["xp"]),
            "wallet": new_wallet,
            "cost": upgrade_cost,
            "required_xp": required_xp,
        }

    def _job_upgrade_sync(self, guild_id: int, user_id: int, display_name: str) -> dict[str, Any]:
        with self._connect_db() as conn:
            profile = self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            profession_key = str(profile.get("profession") or DEFAULT_PROFESSION_KEY)
            return self._attempt_profession_upgrade_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                profession_key=profession_key,
                stat_key="job_upgrades",
            )

    def _get_achievements_sync(self, guild_id: int, user_id: int, display_name: str) -> dict[str, Any]:
        with self._connect_db() as conn:
            profile = self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            self._refresh_achievements_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            unlocked_rows = conn.execute(
                """
                SELECT achievement_key, unlocked_at
                FROM economy_achievements
                WHERE guild_id = ? AND user_id = ?
                ORDER BY unlocked_at ASC
                """,
                (guild_id, user_id),
            ).fetchall()
            unlocked_map = {str(row["achievement_key"]): str(row["unlocked_at"]) for row in unlocked_rows}
            entries: list[dict[str, Any]] = []
            for definition in ACHIEVEMENT_DEFS:
                progress = self._evaluate_achievement_metric_conn(
                    conn,
                    guild_id=guild_id,
                    user_id=user_id,
                    display_name=display_name,
                    definition=definition,
                    profile=profile,
                )
                entries.append(
                    {
                        "key": definition["key"],
                        "name": definition["name"],
                        "description": definition["description"],
                        "target": int(definition["target"]),
                        "progress": progress,
                        "unlocked": definition["key"] in unlocked_map,
                        "unlocked_at": unlocked_map.get(definition["key"]),
                    }
                )
            return {"profile": profile, "entries": entries}

    def _get_daily_quests_sync(self, guild_id: int, user_id: int, display_name: str) -> dict[str, Any]:
        with self._connect_db() as conn:
            self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            snapshot = self._auto_claim_completed_missions_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            return snapshot

    def _get_income_snapshot_sync(self, guild_id: int, user_id: int, display_name: str) -> dict[str, Any]:
        with self._connect_db() as conn:
            profile = self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            return profile

    def _get_xp_bonus_sync(self, guild_id: int, user_id: int, display_name: str) -> float:
        with self._connect_db() as conn:
            self._ensure_economy_profile_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name)
            effects = self._get_item_effect_summary_conn(conn, guild_id=guild_id, user_id=user_id)
            return float(effects.get("xp_bonus", 0.0))

    def _perform_work_sync(self, guild_id: int, user_id: int, display_name: str) -> dict[str, Any]:
        with self._connect_db() as conn:
            profile = self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            remaining = self._get_cooldown_remaining_conn(conn, guild_id=guild_id, user_id=user_id, action="work")
            if remaining > 0:
                return {"status": "cooldown", "remaining": remaining}
            profession = self._resolve_profession(profile.get("profession"))
            profession_level = int(profile.get("profession_level", 1))
            wallet_before = self._get_wallet_conn(conn, guild_id=guild_id, user_id=user_id)
            base_reward = random.randint(int(profession["min"]), int(profession["max"]))
            action_bonus = float(profile.get("item_effects", {}).get("action_bonus", {}).get("work", 0.0)) if isinstance(profile.get("item_effects"), dict) else 0.0
            prestige_bonus = self._prestige_work_bonus_multiplier(int(profile.get("prestige", 0)))
            wallet_bonus = self._wallet_work_bonus_multiplier(wallet_before)
            reward = int(
                round(
                    base_reward
                    * self._profession_income_multiplier(profession_level)
                    * (1.0 + wallet_bonus)
                    * (1.0 + min(action_bonus, 0.5))
                    * (1.0 + prestige_bonus)
                )
            )
            ok, wallet = self._adjust_wallet_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name, delta=reward)
            if not ok:
                return {"status": "error", "message": "Wallet update failed."}
            progress = self._add_profession_xp_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                profession_key=str(profession["key"]),
                amount=25,
            )
            auto_upgrade_result: Optional[dict[str, Any]] = None
            progress_level = int(progress["level"])
            progress_xp = int(progress["xp"])
            if progress_level < PROFESSION_LEVEL_CAP and progress_xp >= self._profession_xp_required(progress_level):
                auto_upgrade_result = self._attempt_profession_upgrade_conn(
                    conn,
                    guild_id=guild_id,
                    user_id=user_id,
                    display_name=display_name,
                    profession_key=str(profession["key"]),
                    stat_key="job_upgrades",
                )
                if auto_upgrade_result.get("status") == "success":
                    wallet = int(auto_upgrade_result.get("wallet", wallet))
                    progress_level = int(auto_upgrade_result.get("level", progress_level))
                    progress_xp = int(auto_upgrade_result.get("xp", progress_xp))
                else:
                    refreshed_progress = self._get_profession_progress_conn(
                        conn,
                        guild_id=guild_id,
                        user_id=user_id,
                        profession_key=str(profession["key"]),
                    )
                    progress_level = int(refreshed_progress["level"])
                    progress_xp = int(refreshed_progress["xp"])
            self._set_cooldown_conn(conn, guild_id=guild_id, user_id=user_id, action="work", seconds=WORK_COOLDOWN_SECONDS)
            template = random.choice(WORK_RESULT_TEMPLATES)
            detail = random.choice(tuple(profession["tasks"]))
            self._record_progress_event_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                stat_updates={"work_uses": 1},
                mission_updates={"work": 1, "earn_coins": reward},
            )
            return {
                "status": "success",
                "amount": reward,
                "wallet": wallet,
                "message": (
                    f"{template.format(job=profession['name'].lower(), amount_phrase=_format_coin_reward(reward))} "
                    f"You {detail}."
                ),
                "profession": profession["name"],
                "profession_level": progress_level,
                "profession_xp": progress_xp,
                "profession_xp_needed": self._profession_xp_required(progress_level),
                "wallet_bonus": wallet_bonus,
                "auto_upgrade": auto_upgrade_result,
            }

    def _perform_simple_earning_sync(
        self,
        guild_id: int,
        user_id: int,
        display_name: str,
        action: str,
        minimum: int,
        maximum: int,
        success_messages: tuple[str, ...],
        failure_messages: tuple[str, ...] = (),
        failure_chance: float = 0.0,
    ) -> dict[str, Any]:
        with self._connect_db() as conn:
            profile = self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            remaining = self._get_cooldown_remaining_conn(conn, guild_id=guild_id, user_id=user_id, action=action)
            if remaining > 0:
                return {"status": "cooldown", "remaining": remaining}
            current_wallet = self._get_wallet_conn(conn, guild_id=guild_id, user_id=user_id)
            if failure_messages and random.random() < failure_chance:
                self._set_cooldown_conn(conn, guild_id=guild_id, user_id=user_id, action=action, seconds=ECONOMY_ACTION_COOLDOWNS.get(action, 60.0))
                self._record_progress_event_conn(
                    conn,
                    guild_id=guild_id,
                    user_id=user_id,
                    display_name=display_name,
                    stat_updates={f"{action}_uses": 1},
                    mission_updates={action: 1},
                )
                return {
                    "status": "failure",
                    "message": random.choice(failure_messages),
                    "wallet": current_wallet,
                }
            base_reward = random.randint(minimum, maximum)
            action_bonus = 0.0
            if isinstance(profile.get("item_effects"), dict):
                action_bonus = float(profile["item_effects"].get("action_bonus", {}).get(action, 0.0))
            reward = int(round(base_reward * (1.0 + min(action_bonus, 0.5))))
            ok, wallet = self._adjust_wallet_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name, delta=reward)
            if not ok:
                return {"status": "error", "message": "Wallet update failed."}
            self._set_cooldown_conn(conn, guild_id=guild_id, user_id=user_id, action=action, seconds=ECONOMY_ACTION_COOLDOWNS.get(action, 60.0))
            self._record_progress_event_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                stat_updates={f"{action}_uses": 1},
                mission_updates={action: 1, "earn_coins": reward},
            )
            return {
                "status": "success",
                "amount": reward,
                "wallet": wallet,
                "message": random.choice(success_messages).format(
                    amount=reward,
                    amount_phrase=_format_coin_reward(reward),
                ),
            }

    def _perform_beg_sync(self, guild_id: int, user_id: int, display_name: str) -> dict[str, Any]:
        donor = random.choice(BEG_DONORS)
        success_messages = (
            f"{donor.capitalize()} handed you {{amount_phrase}}.",
            f"{donor.capitalize()} felt generous and gave you {{amount_phrase}}.",
            f"{donor.capitalize()} dropped {{amount_phrase}} into your hands.",
            f"{donor.capitalize()} checked their pocket and shared {{amount_phrase}}.",
            f"{donor.capitalize()} passed you {{amount_phrase}} before moving on.",
        )
        failure_messages = (
            f"{donor.capitalize()} ignored you and kept walking.",
            f"{donor.capitalize()} shook their head and gave you nothing.",
            f"{donor.capitalize()} said they had nothing to spare.",
        )
        return self._perform_simple_earning_sync(
            guild_id,
            user_id,
            display_name,
            "beg",
            8,
            45,
            success_messages,
            failure_messages,
            0.35,
        )

    def _start_quiz_sync(self, guild_id: int, user_id: int, display_name: str) -> dict[str, Any]:
        with self._connect_db() as conn:
            self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            now_ts = time.time()
            existing = conn.execute(
                "SELECT * FROM economy_quiz_sessions WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
            if existing is not None and float(existing["expires_at"]) > now_ts:
                return {
                    "status": "active",
                    "question": existing["question"],
                    "reward": int(existing["reward"]),
                    "remaining": float(existing["expires_at"]) - now_ts,
                }
            conn.execute(
                "DELETE FROM economy_quiz_sessions WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            left = random.randint(6, 40)
            right = random.randint(1, 25)
            operator = random.choice(("+", "-"))
            if operator == "-" and right > left:
                left, right = right, left
            answer = left + right if operator == "+" else left - right
            reward = random.randint(45, 110)
            question = f"{left} {operator} {right}"
            conn.execute(
                """
                INSERT INTO economy_quiz_sessions (
                    guild_id, user_id, question, answer, reward, expires_at, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    question = excluded.question,
                    answer = excluded.answer,
                    reward = excluded.reward,
                    expires_at = excluded.expires_at,
                    created_at = excluded.created_at
                """,
                (
                    guild_id,
                    user_id,
                    question,
                    answer,
                    reward,
                    now_ts + QUIZ_TIMEOUT_SECONDS,
                    _utcnow().isoformat(),
                ),
            )
            return {
                "status": "created",
                "question": question,
                "reward": reward,
                "remaining": QUIZ_TIMEOUT_SECONDS,
            }

    def _answer_quiz_sync(self, guild_id: int, user_id: int, display_name: str, submitted_answer: int) -> dict[str, Any]:
        with self._connect_db() as conn:
            row = conn.execute(
                "SELECT * FROM economy_quiz_sessions WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
            if row is None:
                return {"status": "missing"}
            expires_at = float(row["expires_at"])
            if expires_at <= time.time():
                conn.execute(
                    "DELETE FROM economy_quiz_sessions WHERE guild_id = ? AND user_id = ?",
                    (guild_id, user_id),
                )
                return {"status": "expired"}
            correct_answer = int(row["answer"])
            reward = int(row["reward"])
            question = str(row["question"])
            conn.execute(
                "DELETE FROM economy_quiz_sessions WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            if submitted_answer != correct_answer:
                return {"status": "wrong", "question": question, "correct_answer": correct_answer}
            profile = self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            quiz_bonus = 0.0
            if isinstance(profile.get("item_effects"), dict):
                quiz_bonus = float(profile["item_effects"].get("action_bonus", {}).get("quiz", 0.0))
            final_reward = int(round(reward * (1.0 + min(quiz_bonus, 0.5))))
            ok, wallet = self._adjust_wallet_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name, delta=final_reward)
            if not ok:
                return {"status": "error"}
            self._record_progress_event_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                stat_updates={"quiz_wins": 1},
                mission_updates={"quiz_win": 1, "earn_coins": final_reward},
            )
            return {"status": "correct", "reward": final_reward, "wallet": wallet, "question": question}

    def _claim_daily_sync(self, guild_id: int, user_id: int, display_name: str) -> dict[str, Any]:
        with self._connect_db() as conn:
            self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            row = conn.execute(
                "SELECT daily_claimed_at FROM economy_profiles WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
            claimed_at_raw = row["daily_claimed_at"] if row else None
            if isinstance(claimed_at_raw, str) and claimed_at_raw:
                with contextlib.suppress(ValueError):
                    claimed_at = dt.datetime.fromisoformat(claimed_at_raw)
                    remaining = DAILY_COOLDOWN_SECONDS - ((_utcnow() - claimed_at).total_seconds())
                    if remaining > 0:
                        return {"status": "cooldown", "remaining": remaining}
            reward = random.randint(250, 450)
            ok, wallet = self._adjust_wallet_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name, delta=reward)
            if not ok:
                return {"status": "error"}
            conn.execute(
                "UPDATE economy_profiles SET daily_claimed_at = ?, updated_at = ?, last_known_name = ? WHERE guild_id = ? AND user_id = ?",
                (_utcnow().isoformat(), _utcnow().isoformat(), display_name, guild_id, user_id),
            )
            self._record_progress_event_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                stat_updates={"daily_claims": 1},
                mission_updates={"earn_coins": reward},
            )
            return {"status": "success", "reward": reward, "wallet": wallet}

    def _list_inventory_sync(self, guild_id: int, user_id: int, display_name: str) -> list[dict[str, Any]]:
        with self._connect_db() as conn:
            self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            rows = conn.execute(
                """
                SELECT item_key, quantity
                FROM economy_inventory
                WHERE guild_id = ? AND user_id = ? AND quantity > 0
                ORDER BY item_key ASC
                """,
                (guild_id, user_id),
            ).fetchall()
            return [dict(row) for row in rows]

    def _buy_item_sync(self, guild_id: int, user_id: int, display_name: str, item_key: str) -> dict[str, Any]:
        item = SHOP_ITEM_LOOKUP[item_key]
        with self._connect_db() as conn:
            self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            row = conn.execute(
                "SELECT wallet FROM economy_profiles WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
            if row is None:
                return {"status": "error"}
            wallet = int(row["wallet"])
            price = int(item["price"])
            if wallet < price:
                return {"status": "insufficient", "wallet": wallet, "price": price}
            ok, new_wallet = self._adjust_wallet_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name, delta=-price)
            if not ok:
                return {"status": "error"}
            conn.execute(
                """
                INSERT INTO economy_inventory (guild_id, user_id, item_key, quantity)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(guild_id, user_id, item_key) DO UPDATE SET
                    quantity = quantity + 1
                """,
                (guild_id, user_id, item["key"]),
            )
            mission_updates = {"buy_item": 1}
            self._record_progress_event_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                stat_updates={"items_bought": 1},
                mission_updates=mission_updates,
            )
            return {"status": "success", "wallet": new_wallet, "item": item}

    def _sell_item_sync(self, guild_id: int, user_id: int, display_name: str, item_key: str) -> dict[str, Any]:
        item = SHOP_ITEM_LOOKUP.get(item_key)
        if item is None:
            return {"status": "missing_item"}
        with self._connect_db() as conn:
            self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            quantity = self._get_inventory_quantity_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                item_key=str(item["key"]),
            )
            if quantity <= 0:
                return {"status": "missing_owned", "item": item}
            sell_price = self._item_sell_price(item)
            conn.execute(
                """
                UPDATE economy_inventory
                SET quantity = quantity - 1
                WHERE guild_id = ? AND user_id = ? AND item_key = ? AND quantity > 0
                """,
                (guild_id, user_id, str(item["key"])),
            )
            conn.execute(
                """
                DELETE FROM economy_inventory
                WHERE guild_id = ? AND user_id = ? AND item_key = ? AND quantity <= 0
                """,
                (guild_id, user_id, str(item["key"])),
            )
            ok, wallet = self._adjust_wallet_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                delta=sell_price,
            )
            if not ok:
                return {"status": "error", "item": item}
            self._record_progress_event_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                stat_updates={"items_sold": 1},
            )
            return {
                "status": "success",
                "item": item,
                "sell_price": sell_price,
                "wallet": wallet,
                "remaining_quantity": max(0, quantity - 1),
            }

    def _sell_all_items_sync(self, guild_id: int, user_id: int, display_name: str) -> dict[str, Any]:
        with self._connect_db() as conn:
            self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            rows = conn.execute(
                """
                SELECT item_key, quantity
                FROM economy_inventory
                WHERE guild_id = ? AND user_id = ? AND quantity > 0
                ORDER BY item_key ASC
                """,
                (guild_id, user_id),
            ).fetchall()
            sold_entries: list[dict[str, Any]] = []
            total_payout = 0
            total_items = 0
            for row in rows:
                item = SHOP_ITEM_LOOKUP.get(_normalize_lookup(str(row["item_key"])))
                quantity = max(0, int(row["quantity"]))
                if item is None or quantity <= 0:
                    continue
                sell_price = self._item_sell_price(item)
                entry_total = sell_price * quantity
                sold_entries.append(
                    {
                        "item_name": str(item["name"]),
                        "quantity": quantity,
                        "sell_price": sell_price,
                        "total": entry_total,
                    }
                )
                total_payout += entry_total
                total_items += quantity
            if total_items <= 0 or total_payout <= 0:
                return {"status": "empty"}
            conn.execute(
                "DELETE FROM economy_inventory WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            ok, wallet = self._adjust_wallet_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                delta=total_payout,
            )
            if not ok:
                return {"status": "error"}
            self._record_progress_event_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                stat_updates={"items_sold": total_items},
            )
            return {
                "status": "success",
                "wallet": wallet,
                "total_items": total_items,
                "total_payout": total_payout,
                "sold_entries": sold_entries,
            }

    def _get_inventory_quantity_conn(self, conn: sqlite3.Connection, *, guild_id: int, user_id: int, item_key: str) -> int:
        row = conn.execute(
            "SELECT quantity FROM economy_inventory WHERE guild_id = ? AND user_id = ? AND item_key = ?",
            (guild_id, user_id, item_key),
        ).fetchone()
        if row is None:
            return 0
        return max(0, int(row["quantity"]))

    def _list_owned_pets_sync(self, guild_id: int, user_id: int, display_name: str) -> list[dict[str, Any]]:
        with self._connect_db() as conn:
            self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            rows = conn.execute(
                """
                SELECT pet_key, equipped, last_fed_at, acquired_at
                FROM economy_pets
                WHERE guild_id = ? AND user_id = ?
                ORDER BY acquired_at ASC
                """,
                (guild_id, user_id),
            ).fetchall()
            return [dict(row) for row in rows]

    def _buy_pet_sync(self, guild_id: int, user_id: int, display_name: str, pet_key: str) -> dict[str, Any]:
        pet = PET_LOOKUP[pet_key]
        with self._connect_db() as conn:
            self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            existing = conn.execute(
                "SELECT pet_key FROM economy_pets WHERE guild_id = ? AND user_id = ? AND pet_key = ?",
                (guild_id, user_id, pet_key),
            ).fetchone()
            if existing is not None:
                return {"status": "owned", "pet": pet}
            wallet = self._get_wallet_conn(conn, guild_id=guild_id, user_id=user_id)
            price = int(pet["price"])
            if wallet < price:
                return {"status": "insufficient", "wallet": wallet, "price": price}
            ok, new_wallet = self._adjust_wallet_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                delta=-price,
            )
            if not ok:
                return {"status": "error"}
            conn.execute(
                """
                INSERT INTO economy_pets (guild_id, user_id, pet_key, equipped, last_fed_at, acquired_at)
                VALUES (?, ?, ?, 0, NULL, ?)
                """,
                (guild_id, user_id, pet_key, _utcnow().isoformat()),
            )
            self._record_progress_event_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                stat_updates={"pets_owned": 1},
            )
            return {"status": "success", "pet": pet, "wallet": new_wallet}

    def _equip_pet_sync(self, guild_id: int, user_id: int, display_name: str, pet_key: str) -> dict[str, Any]:
        pet = PET_LOOKUP.get(pet_key)
        if pet is None:
            return {"status": "missing"}
        with self._connect_db() as conn:
            self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            existing = conn.execute(
                "SELECT pet_key FROM economy_pets WHERE guild_id = ? AND user_id = ? AND pet_key = ?",
                (guild_id, user_id, pet_key),
            ).fetchone()
            if existing is None:
                return {"status": "missing"}
            conn.execute(
                "UPDATE economy_pets SET equipped = 0 WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            conn.execute(
                "UPDATE economy_pets SET equipped = 1 WHERE guild_id = ? AND user_id = ? AND pet_key = ?",
                (guild_id, user_id, pet_key),
            )
            return {"status": "success", "pet": pet}

    def _unequip_pet_sync(self, guild_id: int, user_id: int, display_name: str) -> dict[str, Any]:
        with self._connect_db() as conn:
            self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            row = conn.execute(
                "SELECT pet_key FROM economy_pets WHERE guild_id = ? AND user_id = ? AND equipped = 1 LIMIT 1",
                (guild_id, user_id),
            ).fetchone()
            if row is None:
                return {"status": "none"}
            conn.execute(
                "UPDATE economy_pets SET equipped = 0 WHERE guild_id = ? AND user_id = ? AND pet_key = ?",
                (guild_id, user_id, str(row["pet_key"])),
            )
            pet = PET_LOOKUP.get(_normalize_lookup(str(row["pet_key"])))
            return {"status": "success", "pet": pet}

    def _feed_pet_sync(self, guild_id: int, user_id: int, display_name: str) -> dict[str, Any]:
        with self._connect_db() as conn:
            self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            row = conn.execute(
                """
                SELECT pet_key
                FROM economy_pets
                WHERE guild_id = ? AND user_id = ? AND equipped = 1
                LIMIT 1
                """,
                (guild_id, user_id),
            ).fetchone()
            if row is None:
                return {"status": "none"}
            pet_key = _normalize_lookup(str(row["pet_key"]))
            conn.execute(
                "UPDATE economy_pets SET last_fed_at = ? WHERE guild_id = ? AND user_id = ? AND pet_key = ?",
                (_utcnow().isoformat(), guild_id, user_id, pet_key),
            )
            return {"status": "success", "pet": PET_LOOKUP.get(pet_key)}

    def _use_item_sync(self, guild_id: int, user_id: int, display_name: str, item_key: str) -> dict[str, Any]:
        item = SHOP_ITEM_LOOKUP[item_key]
        with self._connect_db() as conn:
            self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            quantity = self._get_inventory_quantity_conn(conn, guild_id=guild_id, user_id=user_id, item_key=item["key"])
            if quantity <= 0:
                return {"status": "missing"}
            if item.get("consumable"):
                conn.execute(
                    "UPDATE economy_inventory SET quantity = quantity - 1 WHERE guild_id = ? AND user_id = ? AND item_key = ?",
                    (guild_id, user_id, item["key"]),
                )
                conn.execute(
                    "DELETE FROM economy_inventory WHERE guild_id = ? AND user_id = ? AND item_key = ? AND quantity <= 0",
                    (guild_id, user_id, item["key"]),
                )
                quantity = max(0, quantity - 1)
            self._record_progress_event_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                stat_updates={"items_used": 1},
                mission_updates={"use_item": 1},
            )
            return {
                "status": "success",
                "item": item,
                "quantity": quantity,
                "consumable": bool(item.get("consumable")),
            }

    def _perform_gamble_sync(self, guild_id: int, user_id: int, display_name: str, amount: int) -> dict[str, Any]:
        with self._connect_db() as conn:
            profile = self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            wallet = self._get_wallet_conn(conn, guild_id=guild_id, user_id=user_id)
            if amount <= 0:
                return {"status": "invalid"}
            if wallet < amount:
                return {"status": "insufficient", "wallet": wallet}
            won = random.random() < 0.48
            gamble_bonus = 0.0
            if isinstance(profile.get("item_effects"), dict):
                gamble_bonus = float(profile["item_effects"].get("action_bonus", {}).get("gamble", 0.0))
            delta = int(round(amount * (1.0 + min(gamble_bonus, 0.4)))) if won else -amount
            ok, new_wallet = self._adjust_wallet_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name, delta=delta)
            if not ok:
                return {"status": "error"}
            stat_updates = {"gamble_plays": 1}
            mission_updates: dict[str, int] = {}
            if won:
                stat_updates["gamble_wins"] = 1
                mission_updates["gamble_win"] = 1
                mission_updates["earn_coins"] = amount
            else:
                stat_updates["gamble_losses"] = 1
            self._record_progress_event_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                stat_updates=stat_updates,
                mission_updates=mission_updates,
            )
            return {
                "status": "win" if won else "loss",
                "amount": amount,
                "wallet": new_wallet,
                "payout_total": amount + delta if won else 0,
            }

    def _reserve_blackjack_bet_sync(self, guild_id: int, user_id: int, display_name: str, amount: int) -> dict[str, Any]:
        with self._connect_db() as conn:
            self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            wallet = self._get_wallet_conn(conn, guild_id=guild_id, user_id=user_id)
            if amount <= 0:
                return {"status": "invalid"}
            if wallet < amount:
                return {"status": "insufficient", "wallet": wallet}
            ok, new_wallet = self._adjust_wallet_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name, delta=-amount)
            if not ok:
                return {"status": "error"}
            return {"status": "success", "wallet": new_wallet}

    def _reserve_blackjack_extra_sync(self, guild_id: int, user_id: int, display_name: str, amount: int) -> dict[str, Any]:
        return self._reserve_blackjack_bet_sync(guild_id, user_id, display_name, amount)

    def _settle_blackjack_payout_sync(self, guild_id: int, user_id: int, display_name: str, amount: int) -> dict[str, Any]:
        with self._connect_db() as conn:
            self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            ok, new_wallet = self._adjust_wallet_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name, delta=amount)
            if not ok:
                return {"status": "error"}
            return {"status": "success", "wallet": new_wallet}

    def _reserve_duel_bets_sync(
        self,
        guild_id: int,
        challenger_id: int,
        challenger_name: str,
        target_id: int,
        target_name: str,
        amount: int,
    ) -> dict[str, Any]:
        with self._connect_db() as conn:
            self._prepare_profile_conn(conn, guild_id=guild_id, user_id=challenger_id, display_name=challenger_name)
            self._prepare_profile_conn(conn, guild_id=guild_id, user_id=target_id, display_name=target_name)
            challenger_wallet = self._get_wallet_conn(conn, guild_id=guild_id, user_id=challenger_id)
            target_wallet = self._get_wallet_conn(conn, guild_id=guild_id, user_id=target_id)
            if amount <= 0:
                return {"status": "invalid"}
            if challenger_wallet < amount:
                return {"status": "challenger_insufficient", "wallet": challenger_wallet}
            if target_wallet < amount:
                return {"status": "target_insufficient", "wallet": target_wallet}
            ok, challenger_after = self._adjust_wallet_conn(
                conn,
                guild_id=guild_id,
                user_id=challenger_id,
                display_name=challenger_name,
                delta=-amount,
            )
            if not ok:
                return {"status": "error"}
            ok, target_after = self._adjust_wallet_conn(
                conn,
                guild_id=guild_id,
                user_id=target_id,
                display_name=target_name,
                delta=-amount,
            )
            if not ok:
                return {"status": "error"}
            return {"status": "success", "challenger_wallet": challenger_after, "target_wallet": target_after}

    def _refund_duel_bets_sync(
        self,
        guild_id: int,
        challenger_id: int,
        challenger_name: str,
        target_id: int,
        target_name: str,
        amount: int,
    ) -> dict[str, Any]:
        with self._connect_db() as conn:
            self._prepare_profile_conn(conn, guild_id=guild_id, user_id=challenger_id, display_name=challenger_name)
            self._prepare_profile_conn(conn, guild_id=guild_id, user_id=target_id, display_name=target_name)
            ok, challenger_after = self._adjust_wallet_conn(
                conn,
                guild_id=guild_id,
                user_id=challenger_id,
                display_name=challenger_name,
                delta=amount,
            )
            if not ok:
                return {"status": "error"}
            ok, target_after = self._adjust_wallet_conn(
                conn,
                guild_id=guild_id,
                user_id=target_id,
                display_name=target_name,
                delta=amount,
            )
            if not ok:
                return {"status": "error"}
            return {"status": "success", "challenger_wallet": challenger_after, "target_wallet": target_after}

    def _settle_duel_winner_sync(
        self,
        guild_id: int,
        winner_id: int,
        winner_name: str,
        payout_amount: int,
    ) -> dict[str, Any]:
        return self._settle_blackjack_payout_sync(guild_id, winner_id, winner_name, payout_amount)

    def _record_blackjack_outcome_sync(
        self,
        guild_id: int,
        user_id: int,
        display_name: str,
        outcome: str,
        payout_amount: int,
    ) -> None:
        with self._connect_db() as conn:
            self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            stat_updates = {"blackjack_plays": 1}
            mission_updates = {"blackjack_play": 1}
            if outcome in {"win", "blackjack"}:
                stat_updates["blackjack_wins"] = 1
                mission_updates["earn_coins"] = max(0, payout_amount)
            elif outcome == "loss":
                stat_updates["blackjack_losses"] = 1
            self._record_progress_event_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                stat_updates=stat_updates,
                mission_updates=mission_updates,
            )

    def _record_slots_result_sync(
        self,
        guild_id: int,
        user_id: int,
        display_name: str,
        outcome: str,
        payout_amount: int,
    ) -> None:
        with self._connect_db() as conn:
            self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            stat_updates = {"slots_plays": 1}
            mission_updates = {"slots_play": 1}
            if outcome == "jackpot":
                stat_updates["slot_jackpots"] = 1
            if payout_amount > 0:
                stat_updates["slots_wins"] = 1
                mission_updates["earn_coins"] = max(0, payout_amount)
            else:
                stat_updates["slots_losses"] = 1
            self._record_progress_event_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                stat_updates=stat_updates,
                mission_updates=mission_updates,
            )

    def _record_crash_result_sync(
        self,
        guild_id: int,
        user_id: int,
        display_name: str,
        won: bool,
        payout_amount: int,
    ) -> None:
        with self._connect_db() as conn:
            self._prepare_profile_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
            stat_updates = {"crash_plays": 1}
            mission_updates: dict[str, int] = {}
            if won:
                stat_updates["crash_wins"] = 1
                mission_updates["earn_coins"] = max(0, payout_amount)
            else:
                stat_updates["crash_losses"] = 1
            self._record_progress_event_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                stat_updates=stat_updates,
                mission_updates=mission_updates,
            )

    def _record_duel_win_sync(
        self,
        guild_id: int,
        user_id: int,
        display_name: str,
        payout_amount: int,
    ) -> None:
        with self._connect_db() as conn:
            self._prepare_profile_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name)
            self._record_progress_event_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                stat_updates={"duel_wins": 1},
                mission_updates={"earn_coins": max(0, payout_amount)},
            )

    def _record_duel_loss_sync(
        self,
        guild_id: int,
        user_id: int,
        display_name: str,
    ) -> None:
        with self._connect_db() as conn:
            self._prepare_profile_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name)
            self._record_progress_event_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                stat_updates={"duel_losses": 1},
            )

    def _record_dungeon_win_sync(
        self,
        guild_id: int,
        user_id: int,
        display_name: str,
        payout_amount: int,
        cleared_level: int,
    ) -> None:
        with self._connect_db() as conn:
            self._prepare_profile_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name)
            self._record_progress_event_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                stat_updates={"dungeon_wins": 1},
                mission_updates={"earn_coins": max(0, payout_amount)},
            )
            if int(cleared_level) >= len(DUNGEON_REWARD_MULTIPLIERS):
                self._award_prestige_conn(
                    conn,
                    guild_id=guild_id,
                    user_id=user_id,
                    display_name=display_name,
                    amount=5,
                )

    def _record_dungeon_failure_sync(
        self,
        guild_id: int,
        user_id: int,
        display_name: str,
    ) -> None:
        with self._connect_db() as conn:
            self._prepare_profile_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name)
            self._record_progress_event_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                stat_updates={"dungeon_failures": 1},
            )

    def _gift_money_sync(
        self,
        guild_id: int,
        sender_id: int,
        sender_name: str,
        target_id: int,
        target_name: str,
        amount: int,
    ) -> dict[str, Any]:
        with self._connect_db() as conn:
            self._prepare_profile_conn(conn, guild_id=guild_id, user_id=sender_id, display_name=sender_name)
            self._prepare_profile_conn(conn, guild_id=guild_id, user_id=target_id, display_name=target_name)
            sender = conn.execute(
                "SELECT wallet FROM economy_profiles WHERE guild_id = ? AND user_id = ?",
                (guild_id, sender_id),
            ).fetchone()
            if sender is None:
                return {"status": "error"}
            if int(sender["wallet"]) < amount:
                return {"status": "insufficient", "wallet": int(sender["wallet"])}
            ok, sender_wallet = self._adjust_wallet_conn(conn, guild_id=guild_id, user_id=sender_id, display_name=sender_name, delta=-amount)
            if not ok:
                return {"status": "error"}
            ok, target_wallet = self._adjust_wallet_conn(conn, guild_id=guild_id, user_id=target_id, display_name=target_name, delta=amount)
            if not ok:
                return {"status": "error"}
            return {"status": "success", "sender_wallet": sender_wallet, "target_wallet": target_wallet}

    def _grant_money_sync(
        self,
        guild_id: int,
        target_id: int,
        target_name: str,
        amount: int,
    ) -> dict[str, Any]:
        with self._connect_db() as conn:
            self._prepare_profile_conn(conn, guild_id=guild_id, user_id=target_id, display_name=target_name)
            if amount <= 0:
                wallet = self._get_wallet_conn(conn, guild_id=guild_id, user_id=target_id)
                return {"status": "invalid", "wallet": wallet}
            ok, wallet = self._adjust_wallet_conn(
                conn,
                guild_id=guild_id,
                user_id=target_id,
                display_name=target_name,
                delta=amount,
            )
            if not ok:
                return {"status": "error"}
            return {"status": "success", "wallet": wallet}

    def _perform_pvp_action_sync(
        self,
        action: str,
        guild_id: int,
        attacker_id: int,
        attacker_name: str,
        target_id: int,
        target_name: str,
    ) -> dict[str, Any]:
        config = PVP_ACTION_CONFIGS[action]
        with self._connect_db() as conn:
            attacker_profile = self._prepare_profile_conn(conn, guild_id=guild_id, user_id=attacker_id, display_name=attacker_name)
            self._prepare_profile_conn(conn, guild_id=guild_id, user_id=target_id, display_name=target_name)
            remaining = self._get_cooldown_remaining_conn(conn, guild_id=guild_id, user_id=attacker_id, action=action)
            if remaining > 0:
                return {"status": "cooldown", "remaining": remaining}
            attacker_wallet = self._get_wallet_conn(conn, guild_id=guild_id, user_id=attacker_id)
            target_wallet = self._get_wallet_conn(conn, guild_id=guild_id, user_id=target_id)
            if target_wallet < int(config["min_target_wallet"]):
                return {"status": "target_poor", "target_wallet": target_wallet}
            action_bonus = 0.0
            if isinstance(attacker_profile.get("item_effects"), dict):
                action_bonus = float(attacker_profile["item_effects"].get("action_bonus", {}).get(action, 0.0))
            self._set_cooldown_conn(
                conn,
                guild_id=guild_id,
                user_id=attacker_id,
                action=action,
                seconds=float(config["cooldown"]),
            )
            if random.random() < min(0.8, float(config["success_chance"]) + min(action_bonus, 0.15)):
                low, high = config["take_range"]
                amount = int(target_wallet * random.uniform(float(low), float(high)))
                amount = int(round(amount * (1.0 + min(action_bonus, 0.25))))
                amount = max(1, min(amount, int(config["take_cap"]), target_wallet))
                ok, attacker_after = self._adjust_wallet_conn(
                    conn,
                    guild_id=guild_id,
                    user_id=attacker_id,
                    display_name=attacker_name,
                    delta=amount,
                )
                if not ok:
                    return {"status": "error"}
                ok, target_after = self._adjust_wallet_conn(
                    conn,
                    guild_id=guild_id,
                    user_id=target_id,
                    display_name=target_name,
                    delta=-amount,
                )
                if not ok:
                    return {"status": "error"}
                stat_updates = {f"{action}_successes": 1}
                if action in {"rob", "steal"}:
                    stat_updates["theft_successes"] = 1
                self._record_progress_event_conn(
                    conn,
                    guild_id=guild_id,
                    user_id=attacker_id,
                    display_name=attacker_name,
                    stat_updates=stat_updates,
                    mission_updates={"earn_coins": amount},
                )
                return {
                    "status": "success",
                    "amount": amount,
                    "attacker_wallet": attacker_after,
                    "target_wallet": target_after,
                    "message": random.choice(tuple(config["success_templates"])).format(
                        target_name=target_name,
                        amount_phrase=_format_coin_reward(amount),
                    ),
                }
            penalty_low, penalty_high = config["failure_penalty"]
            if action == "heist":
                penalty = max(attacker_wallet - 1, 0)
                penalty = attacker_wallet - penalty
            else:
                penalty = min(attacker_wallet, random.randint(int(penalty_low), int(penalty_high)))
            attacker_after = attacker_wallet
            if penalty > 0:
                ok, attacker_after = self._adjust_wallet_conn(
                    conn,
                    guild_id=guild_id,
                    user_id=attacker_id,
                    display_name=attacker_name,
                    delta=-penalty,
                )
                if not ok:
                    return {"status": "error"}
            self._record_progress_event_conn(
                conn,
                guild_id=guild_id,
                user_id=attacker_id,
                display_name=attacker_name,
                stat_updates={f"{action}_failures": 1},
            )
            return {
                "status": "failure",
                "amount": penalty,
                "attacker_wallet": attacker_after,
                "message": random.choice(tuple(config["failure_templates"])).format(
                    target_name=target_name,
                    amount_phrase=_format_coin_reward(penalty),
                ),
            }

    def _get_richest_sync(self, guild_id: int) -> list[dict[str, Any]]:
        with self._connect_db() as conn:
            rows = conn.execute(
                """
                SELECT user_id, last_known_name, wallet, profession
                FROM economy_profiles
                WHERE guild_id = ?
                ORDER BY wallet DESC, total_earned DESC, user_id ASC
                """,
                (guild_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def _build_balance_embed(self, *, target_user: discord.abc.User, profile: dict[str, Any]) -> discord.Embed:
        profession = self._resolve_profession(profile.get("profession"))
        embed = discord.Embed(
            title="Cadis Etrama Di Raizel",
            description=f"Economy profile for **{_display_name(target_user)}**",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Wallet")
        avatar = getattr(target_user, "display_avatar", None)
        if avatar:
            embed.set_thumbnail(url=avatar.url)
        embed.add_field(name="Wallet", value=f"{int(profile.get('wallet', 0))} coins", inline=True)
        embed.add_field(
            name="Profession",
            value=f"{profession['name']} (Lv {int(profile.get('profession_level', 1))})",
            inline=True,
        )
        embed.add_field(name="Prestige", value=str(int(profile.get("prestige", 0))), inline=True)
        embed.add_field(
            name="Work Bonus",
            value=self._format_prestige_bonus_text(int(profile.get("prestige", 0))),
            inline=True,
        )
        embed.add_field(name="Total Earned", value=f"{int(profile.get('total_earned', 0))} coins", inline=True)
        embed.add_field(name="Total Spent", value=f"{int(profile.get('total_spent', 0))} coins", inline=True)
        embed.add_field(name="Passive Rate", value=f"{int(profile.get('passive_per_hour', 0))} coins/hour", inline=True)
        embed.add_field(name="Passive Collected", value=f"{int(profile.get('total_passive_collected', 0))} coins", inline=True)
        if profile.get("item_effect_descriptions"):
            lines = list(profile["item_effect_descriptions"])[:5]
            embed.add_field(name="Active Item Effects", value="\n".join(f"- {line}" for line in lines), inline=False)
        if profile.get("equipped_pet"):
            pet = profile["equipped_pet"]
            embed.add_field(
                name="Equipped Pet",
                value=f"{pet['emoji']} **{pet['name']}** — {profile.get('pet_bonus_text') or pet.get('bonus_text', '')}",
                inline=False,
            )
        if int(profile.get("auto_collected_passive", 0)) > 0:
            embed.add_field(
                name="Silent Income",
                value=f"Added **{int(profile['auto_collected_passive'])} coins** from passive sources during this refresh.",
                inline=False,
            )
        embed.set_footer(text="Use jobs / job upgrade / income to shape your economy.")
        return embed

    def _build_jobs_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="Cadis Etrama Di Raizel",
            description="Available professions. Use `choosejob <name>` to switch or `job upgrade` to push your current career higher.",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Jobs")
        chunks = [PROFESSIONS[index:index + 10] for index in range(0, len(PROFESSIONS), 10)]
        for index, chunk in enumerate(chunks, start=1):
            embed.add_field(name=f"Jobs {index}", value="\n".join(f"- {entry['name']}" for entry in chunk), inline=True)
        embed.set_footer(text="Economy commands are English-only by design.")
        return embed

    def _build_current_job_embed(self, *, profile: dict[str, Any]) -> discord.Embed:
        profession = self._resolve_profession(profile.get("profession"))
        level = int(profile.get("profession_level", 1))
        current_xp = int(profile.get("profession_xp", 0))
        needed_xp = int(profile.get("profession_xp_needed", self._profession_xp_required(level)))
        wallet_bonus = self._wallet_work_bonus_multiplier(int(profile.get("wallet", 0) or 0))
        embed = discord.Embed(
            title="Cadis Etrama Di Raizel",
            description=f"Current profession: **{profession['name']}**",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Job Progress")
        embed.add_field(name="Level", value=str(level), inline=True)
        embed.add_field(name="Progress", value=f"{current_xp}/{needed_xp} XP", inline=True)
        embed.add_field(name="Next Upgrade Cost", value=f"{int(profile.get('profession_upgrade_cost', 0))} coins", inline=True)
        embed.add_field(
            name="Income Scaling",
            value=(
                f"Job Level: x{self._profession_income_multiplier(level):.2f}\n"
                f"Economy Bonus: +{int(round(wallet_bonus * 100))}% from wallet size"
            ),
            inline=False,
        )
        embed.set_footer(text="Work can auto-upgrade your job when XP is full and you can afford the upgrade cost.")
        return embed

    def _build_achievements_embed(self, *, display_name: str, entries: list[dict[str, Any]]) -> discord.Embed:
        unlocked = [entry for entry in entries if entry["unlocked"]]
        embed = discord.Embed(
            title="Cadis Etrama Di Raizel",
            description=f"Achievements for **{display_name}**",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Achievements")
        if unlocked:
            unlocked_lines = [f"• **{entry['name']}** — {entry['description']}" for entry in unlocked[:8]]
            embed.add_field(name="Unlocked", value="\n".join(unlocked_lines), inline=False)
        else:
            embed.add_field(name="Unlocked", value="No achievements unlocked yet.", inline=False)
        progress_lines = []
        for entry in entries:
            if entry["unlocked"]:
                continue
            progress_lines.append(
                f"• **{entry['name']}** — {entry['progress']}/{entry['target']}"
            )
        embed.add_field(
            name="In Progress",
            value="\n".join(progress_lines[:8]) if progress_lines else "Everything listed here is already unlocked.",
            inline=False,
        )
        embed.set_footer(text=f"{len(unlocked)}/{len(entries)} achievements unlocked")
        return embed

    def _build_quests_embed(self, *, missions: list[dict[str, Any]], claimed_reward: int, claimed_count: int) -> discord.Embed:
        embed = discord.Embed(
            title="Cadis Etrama Di Raizel",
            description="Daily missions reset every day and completed rewards are claimed automatically when you check this page.",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Daily Missions")
        lines = []
        for mission in missions:
            template = next((definition for definition in DAILY_MISSION_DEFS if definition["key"] == mission["mission_key"]), None)
            title = template["name"] if template else str(mission["mission_key"]).replace("_", " ").title()
            description = template["description"] if template else str(mission["progress_key"])
            progress = int(mission["progress"])
            target = int(mission["target"])
            status = "Claimed" if int(mission["claimed"]) else ("Ready" if progress >= target else "Active")
            lines.append(
                f"• **{title}** — {description}\n  Progress: `{progress}/{target}` • Reward: `{int(mission['reward'])} coins` • {status}"
            )
        embed.add_field(name="Today", value="\n".join(lines) if lines else "No missions available.", inline=False)
        if claimed_reward > 0:
            embed.add_field(
                name="Claimed This Check",
                value=f"Completed **{claimed_count}** mission(s) for **{claimed_reward} coins**.",
                inline=False,
            )
        embed.set_footer(text=f"Daily missions: {self._today_key()}")
        return embed

    def _build_income_embed(self, *, profile: dict[str, Any]) -> discord.Embed:
        embed = discord.Embed(
            title="Cadis Etrama Di Raizel",
            description="Property and passive income overview.",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Passive Income")
        sources = profile.get("passive_sources") or []
        if sources:
            lines = [
                f"• **{source['item_name']}** x{source['quantity']} — {source['amount_per_tick']} coins / 5m"
                for source in sources
            ]
            embed.add_field(name="Sources", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Sources", value="No passive income properties owned yet.", inline=False)
        embed.add_field(name="Rate", value=f"{int(profile.get('passive_per_hour', 0))} coins/hour", inline=True)
        embed.add_field(name="Collected Total", value=f"{int(profile.get('total_passive_collected', 0))} coins", inline=True)
        if int(profile.get("auto_collected_passive", 0)) > 0:
            embed.add_field(
                name="Collected Now",
                value=f"**{int(profile['auto_collected_passive'])} coins** were added silently during this refresh.",
                inline=False,
            )
        embed.set_footer(text="Passive income accumulates quietly in the background.")
        return embed

    def _build_crash_embed(self, session: CrashSession) -> discord.Embed:
        embed = discord.Embed(
            title="Crash Flight",
            description="A live multiplier run with lift, dips, and a sudden break. Cash out before the flight collapses.",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Cadis Etrama Di Raizel")
        embed.add_field(name="Bet", value=_format_coin_reward(session.bet), inline=True)
        embed.add_field(name="Live Multiplier", value=f"**x{session.current_multiplier:.2f}**", inline=True)
        embed.add_field(name="Peak", value=f"x{session.peak_multiplier:.2f}", inline=True)
        embed.add_field(
            name="Potential Cash Out",
            value=_format_coin_reward(self._calculate_crash_payout(session)),
            inline=True,
        )
        embed.add_field(name="Flight Status", value=session.trend_label, inline=False)
        trail = " → ".join(f"x{value:.2f}" for value in session.history[-6:])
        embed.add_field(name="Flight Path", value=trail, inline=False)
        if session.resolved:
            if session.cashed_out:
                embed.add_field(name="Result", value=session.result_note or "You cashed out in time.", inline=False)
                embed.add_field(name="Payout", value=f"**{session.payout_amount} coins**", inline=False)
            else:
                embed.add_field(name="Result", value=session.result_note or "The line crashed before you escaped.", inline=False)
        else:
            embed.add_field(name="Controls", value="Watch the live multiplier and hit **Cash Out** before the flight breaks.", inline=False)
        embed.set_footer(text="Only the starting player can cash out this flight.")
        return embed

    def build_shop_embed(self, category: Optional[str] = None) -> discord.Embed:
        title = "Shop"
        if category is None:
            embed = discord.Embed(
                title=title,
                description=(
                    "A polished local storefront for upgrades, comfort, companions, and fun finds.\n"
                    "Pick a category below or use `buy <item>` when something catches your eye."
                ),
                color=EMBED_COLOR,
            )
            embed.set_author(name="Cadis Etrama Di Raizel")
            overview_lines = [
                f"{_category_emoji(category_name)} **{category_name}** — {self._shop_category_entry_count(category_name)} items"
                for category_name in self._shop_categories()
            ]
            embed.add_field(name="Category Overview", value="\n".join(overview_lines), inline=False)
            for category_name in self._shop_categories():
                embed.add_field(
                    name=f"{_category_emoji(category_name)} {category_name}",
                    value=self._format_shop_preview_block(category_name),
                    inline=False,
                )
            embed.add_field(
                name="How To Buy",
                value="`buy <item>`\nExamples: `buy gaming chair` • `buy seal pup`",
                inline=False,
            )
            embed.set_footer(text="Use the buttons below to browse categories.")
            return embed

        category_emoji = _category_emoji(category)
        embed = discord.Embed(
            title=f"{category_emoji} {category}",
            description=SHOP_CATEGORY_NOTES.get(category, "Browse the items in this category."),
            color=EMBED_COLOR,
        )
        embed.set_author(name="Cadis Etrama Di Raizel")
        if category == "Pets":
            item_lines = [self._format_pet_shop_line(pet, show_details=True) for pet in PETS]
            chunk_size = 3
        else:
            items = self._shop_items_for_category(category)
            item_lines = [self._format_shop_item_line(item) for item in items]
            chunk_size = 6
        for chunk_index, chunk in enumerate(_chunk_lines(item_lines, max_lines=chunk_size), start=1):
            name = "Items" if chunk_index == 1 else f"Items {chunk_index}"
            embed.add_field(name=name, value="\n".join(chunk), inline=False)
        embed.add_field(
            name="How To Buy",
            value="Use `buy <item>` with the item name as shown above.",
            inline=False,
        )
        if category == "Pets":
            embed.add_field(
                name="Pet Commands",
                value="`buy <pet>` or `buypet <pet>`\n`mypet` `equippet <name>` `feedpet`",
                inline=False,
            )
        embed.set_footer(text=f"Category: {category} • {self._shop_category_entry_count(category)} item(s)")
        return embed

    def build_shopview_embed(self, category: Optional[str] = None, *, page: int = 0) -> discord.Embed:
        if category is None:
            embed = discord.Embed(
                title="ShopView",
                description=(
                    "A premium interactive storefront with cleaner browsing, visible item effects, and page controls.\n"
                    "Choose a category below to inspect the market in detail."
                ),
                color=EMBED_COLOR,
            )
            embed.set_author(name="Cadis Etrama Di Raizel")
            overview_lines = [
                f"{_category_emoji(category_name)} **{category_name}** - {self._shop_category_entry_count(category_name)} item(s)"
                for category_name in self._shop_categories()
            ]
            embed.add_field(name="Category Overview", value="\n".join(overview_lines), inline=False)
            embed.add_field(
                name="Instructions",
                value="Use category buttons to browse. Use `buy <item>` to purchase, `sell <item>` to sell one copy, or `sellall` to liquidate inventory.",
                inline=False,
            )
            embed.add_field(
                name="Display",
                value="Each page shows the item emoji, name, price, and visible effect or bonus.",
                inline=False,
            )
            embed.set_footer(text="Advanced interactive shop - buttons disable after timeout.")
            return embed

        entries = self._shopview_entries_for_category(category)
        page_count = self._shopview_page_count(category)
        safe_page = max(0, min(page, page_count - 1))
        start = safe_page * SHOPVIEW_PAGE_SIZE
        page_entries = entries[start:start + SHOPVIEW_PAGE_SIZE]
        embed = discord.Embed(
            title=f"{_category_emoji(category)} {category}",
            description=SHOP_CATEGORY_NOTES.get(category, "Browse the items in this category."),
            color=EMBED_COLOR,
        )
        embed.set_author(name="Cadis Etrama Di Raizel")
        for entry in page_entries:
            field_name, field_value = self._build_shopview_entry_field(entry)
            embed.add_field(name=field_name, value=field_value, inline=False)
        embed.add_field(
            name="Purchase",
            value="Use `buy <item>` to purchase. Use `sell <item>` for one copy or `sellall` to sell your inventory at 70% value.",
            inline=False,
        )
        embed.set_footer(text=f"Page {safe_page + 1}/{page_count} - Home returns to the overview")
        return embed

    # Final override for the legacy shop output so the visible market text
    # stays ASCII-safe even if the host environment previously mangled dashes.
    def build_shop_embed(self, category: Optional[str] = None) -> discord.Embed:
        title = "Shop"
        if category is None:
            embed = discord.Embed(
                title=title,
                description=(
                    "A polished local storefront for upgrades, comfort, companions, and fun finds.\n"
                    "Pick a category below or use `buy <item>` when something catches your eye."
                ),
                color=EMBED_COLOR,
            )
            embed.set_author(name="Cadis Etrama Di Raizel")
            overview_lines = [
                f"{_category_emoji(category_name)} **{category_name}** - {self._shop_category_entry_count(category_name)} items"
                for category_name in self._shop_categories()
            ]
            embed.add_field(name="Category Overview", value="\n".join(overview_lines), inline=False)
            for category_name in self._shop_categories():
                embed.add_field(
                    name=f"{_category_emoji(category_name)} {category_name}",
                    value=self._format_shop_preview_block(category_name),
                    inline=False,
                )
            embed.add_field(
                name="Market Commands",
                value="`buy <item>` | `sell <item>` | `sellall`\nExamples: `buy gaming chair` | `sell golden throne`",
                inline=False,
            )
            embed.set_footer(text="Use the buttons below to browse categories.")
            return embed

        category_emoji = _category_emoji(category)
        embed = discord.Embed(
            title=f"{category_emoji} {category}",
            description=SHOP_CATEGORY_NOTES.get(category, "Browse the items in this category."),
            color=EMBED_COLOR,
        )
        embed.set_author(name="Cadis Etrama Di Raizel")
        if category == "Pets":
            item_lines = [self._format_pet_shop_line(pet, show_details=True) for pet in PETS]
            chunk_size = 3
        else:
            items = self._shop_items_for_category(category)
            item_lines = [self._format_shop_item_line(item) for item in items]
            chunk_size = 6
        for chunk_index, chunk in enumerate(_chunk_lines(item_lines, max_lines=chunk_size), start=1):
            name = "Items" if chunk_index == 1 else f"Items {chunk_index}"
            embed.add_field(name=name, value="\n".join(chunk), inline=False)
        embed.add_field(
            name="Market Commands",
            value="Use `buy <item>` to purchase, `sell <item>` to sell one copy, or `sellall` to liquidate your inventory.",
            inline=False,
        )
        if category == "Pets":
            embed.add_field(
                name="Pet Commands",
                value="`buy <pet>` or `buypet <pet>`\n`mypet` `equippet <name>` `feedpet`",
                inline=False,
            )
        embed.set_footer(text=f"Category: {category} - {self._shop_category_entry_count(category)} item(s)")
        return embed

    def _build_shop_embed(self) -> discord.Embed:
        return self.build_shop_embed()

    def _build_blackjack_embed(
        self,
        session: BlackjackSession,
        *,
        note: Optional[str] = None,
        reveal_dealer: bool = False,
    ) -> discord.Embed:
        player_total = self._blackjack_hand_value(session.player_hand)
        dealer_total = self._blackjack_hand_value(session.dealer_hand)
        dealer_value_text = str(dealer_total) if reveal_dealer else str(self._blackjack_hand_value([session.dealer_hand[0]]))
        embed = discord.Embed(
            title="Blackjack",
            description="Interactive table play with a single live hand.",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Cadis Etrama Di Raizel")
        embed.add_field(
            name=f"Dealer • {dealer_value_text}",
            value=self._format_blackjack_hand(session.dealer_hand, hide_hole_card=not reveal_dealer),
            inline=False,
        )
        embed.add_field(
            name=f"{session.display_name} • {player_total}",
            value=self._format_blackjack_hand(session.player_hand),
            inline=False,
        )
        embed.add_field(name="Current Bet", value=_format_coin_reward(session.bet), inline=True)
        embed.add_field(name="Status", value="Resolved" if session.resolved else "In progress", inline=True)
        if note:
            embed.add_field(name="Table Note", value=note, inline=False)
        if session.resolved:
            if session.outcome in {"win", "blackjack"} and session.payout_amount > 0:
                embed.add_field(name="Final Result", value=f"**Payout: {session.payout_amount} coins**", inline=False)
            elif session.outcome == "push" and session.payout_amount > 0:
                embed.add_field(name="Final Result", value=f"**Push: {session.payout_amount} coins returned**", inline=False)
            elif session.outcome == "loss":
                embed.add_field(name="Final Result", value=f"**Lost: {session.bet} coins**", inline=False)
        embed.set_footer(text="Hit, stand, or double down while the hand is active.")
        return embed

    def _build_multiplayer_blackjack_embed(
        self,
        session: MultiplayerBlackjackSession,
        *,
        note: Optional[str] = None,
    ) -> discord.Embed:
        challenger_total = self._blackjack_hand_value(session.challenger_hand) if session.challenger_hand else 0
        target_total = self._blackjack_hand_value(session.target_hand) if session.target_hand else 0
        if session.resolved:
            status_text = "Resolved"
        elif session.pending_acceptance:
            status_text = "Waiting for acceptance"
        else:
            current_name = self._multiplayer_blackjack_player_name(session, session.current_player_id)
            status_text = f"{current_name}'s turn" if current_name != "Unknown Player" else "In progress"
        embed = discord.Embed(
            title="Blackjack - Multiplayer Table",
            description="A head-to-head blackjack hand. Highest non-bust total takes the full pot.",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Cadis Etrama Di Raizel")
        embed.add_field(name="Player 1", value=session.challenger_name, inline=True)
        embed.add_field(name="Player 2", value=session.target_name, inline=True)
        embed.add_field(name="Pot", value=_format_coin_reward(session.bet * 2), inline=True)
        challenger_flags: list[str] = []
        if session.challenger_stood:
            challenger_flags.append("stood")
        if session.challenger_busted:
            challenger_flags.append("busted")
        target_flags: list[str] = []
        if session.target_stood:
            target_flags.append("stood")
        if session.target_busted:
            target_flags.append("busted")
        embed.add_field(
            name=f"{session.challenger_name} - {challenger_total}",
            value=f"{self._format_blackjack_hand(session.challenger_hand) or 'No cards'}\nStatus: {', '.join(challenger_flags) if challenger_flags else 'active'}",
            inline=False,
        )
        embed.add_field(
            name=f"{session.target_name} - {target_total}",
            value=f"{self._format_blackjack_hand(session.target_hand) or 'No cards'}\nStatus: {', '.join(target_flags) if target_flags else 'active'}",
            inline=False,
        )
        embed.add_field(name="Table State", value=status_text, inline=False)
        final_note = note or session.result_note
        if final_note:
            embed.add_field(name="Result", value=final_note, inline=False)
        if session.resolved and session.winner_id is not None:
            winner_name = self._multiplayer_blackjack_player_name(session, session.winner_id)
            embed.add_field(
                name="Final Payout",
                value=f"**{winner_name} wins {session.payout_amount} coins**",
                inline=False,
            )
        elif session.resolved and session.refunded:
            embed.add_field(name="Final Payout", value="**The table ended in a tie. Both bets were returned.**", inline=False)
        embed.set_footer(text="Only the two seated players can interact with this table.")
        return embed

    def _build_coinflip_embed(self, session: CoinflipSession) -> discord.Embed:
        state_text = "Waiting on both players."
        if session.accepted and session.side_choice is not None and not session.resolved:
            state_text = "Flip locked in. Resolving the toss..."
        elif session.accepted and not session.resolved:
            state_text = "Accepted. Waiting for the challenger to call heads or tails."
        elif session.side_choice is not None and not session.accepted:
            state_text = "Call locked in. Waiting for the challenged player to respond."
        embed = discord.Embed(
            title="Coinflip Challenge",
            description="A live player-vs-player coinflip with one shared pot.",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Cadis Etrama Di Raizel")
        embed.add_field(name="Challenger", value=session.challenger_name, inline=True)
        embed.add_field(name="Opponent", value=session.target_name, inline=True)
        embed.add_field(name="Pot", value=_format_coin_reward(session.bet * 2), inline=True)
        embed.add_field(name="Call", value=(session.side_choice or "Unchosen").title(), inline=True)
        embed.add_field(name="Acceptance", value="Accepted" if session.accepted else "Pending", inline=True)
        reveal_value = (session.revealed_side or "Hidden").title()
        embed.add_field(name="Coin", value=reveal_value, inline=True)
        embed.add_field(name="State", value=state_text, inline=False)
        if session.result_note:
            embed.add_field(name="Result", value=session.result_note, inline=False)
        if session.resolved and session.winner_id is not None:
            winner_name = session.challenger_name if session.winner_id == session.challenger_id else session.target_name
            embed.add_field(name="Final", value=f"**{winner_name} wins {session.payout_amount} coins**", inline=False)
        elif session.resolved and session.refunded:
            embed.add_field(name="Final", value="**The coinflip was cancelled and both bets were returned.**", inline=False)
        embed.set_footer(text="The challenger calls heads or tails. The opponent decides whether to accept.")
        return embed

    def _build_guess_embed(self, session: GuessSession) -> discord.Embed:
        embed = discord.Embed(
            title="Number Guess",
            description="Guess the hidden number from 1 to 100 before you run out of tries.",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Cadis Etrama Di Raizel")
        embed.add_field(name="Player", value=session.display_name, inline=True)
        embed.add_field(name="Bet", value=_format_coin_reward(session.bet), inline=True)
        embed.add_field(name="Tries Left", value=f"{session.tries_left}/{session.max_tries}", inline=True)
        embed.add_field(name="Current Range", value=f"{session.low_bound} - {session.high_bound}", inline=True)
        embed.add_field(
            name="Guesses",
            value=", ".join(str(value) for value in session.guesses[-5:]) if session.guesses else "No guesses yet.",
            inline=True,
        )
        embed.add_field(
            name="How To Play",
            value="Reply in the same channel with a whole number between 1 and 100.",
            inline=False,
        )
        if session.result_note:
            embed.add_field(name="Result", value=session.result_note, inline=False)
        if session.resolved and session.payout_amount > 0:
            embed.add_field(name="Final", value=f"**Payout: {session.payout_amount} coins**", inline=False)
        elif session.resolved:
            embed.add_field(name="Final", value=f"**Lost: {session.bet} coins**", inline=False)
        embed.set_footer(text="The guess game listens only to the player who started it.")
        return embed

    async def _get_http_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def _grant_profile_xp(self, *, guild_id: int, user: discord.abc.User, amount: int) -> None:
        safe_amount = max(0, int(amount))
        if safe_amount <= 0:
            return
        async with self._profile_lock:
            entry = self._ensure_profile_entry(guild_id, user)
            entry["xp"] = max(0, int(entry.get("xp", 0))) + safe_amount
            entry["last_display_name"] = _display_name(user)
            await self._save_profile_data()

    def _trivia_rewards_for_difficulty(self, difficulty: str) -> tuple[int, int]:
        normalized = _normalize_lookup(difficulty)
        if normalized == "hard":
            return 220, 24
        if normalized == "medium":
            return 140, 16
        return 80, 10

    def _decode_trivia_text(self, value: str) -> str:
        decoded = html.unescape(str(value or ""))
        return re.sub(r"\s+", " ", decoded).strip()

    def _prepare_trivia_question(self, payload: dict[str, Any]) -> TriviaQuestion:
        question_text = self._decode_trivia_text(str(payload.get("question") or ""))
        category_text = self._decode_trivia_text(str(payload.get("category") or "General"))
        difficulty_text = self._decode_trivia_text(str(payload.get("difficulty") or "easy")).lower()
        correct_answer = self._decode_trivia_text(str(payload.get("correct_answer") or ""))
        incorrect_answers = [
            self._decode_trivia_text(str(answer))
            for answer in (payload.get("incorrect_answers") or [])
            if str(answer or "").strip()
        ]
        options = [correct_answer, *incorrect_answers]
        random.shuffle(options)
        correct_index = options.index(correct_answer)
        return TriviaQuestion(
            question=question_text,
            category=category_text,
            difficulty=difficulty_text,
            options=options,
            correct_index=correct_index,
            correct_answer=correct_answer,
        )

    async def _fetch_trivia_json(self, url: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                session = await self._get_http_session()
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as response:
                    response.raise_for_status()
                    payload = await response.json()
                    if isinstance(payload, dict):
                        return payload
                    raise RuntimeError("Trivia API returned an unexpected payload.")
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(2 + attempt)
        raise RuntimeError("Failed to contact the trivia service.") from last_error

    async def _ensure_trivia_token(self) -> str:
        if self._trivia_token:
            return self._trivia_token
        payload = await self._fetch_trivia_json(TRIVIA_TOKEN_REQUEST_URL)
        token = str(payload.get("token") or "").strip()
        if not token:
            raise RuntimeError("Trivia token request returned no token.")
        self._trivia_token = token
        return token

    async def _reset_trivia_token(self) -> str:
        token = await self._ensure_trivia_token()
        payload = await self._fetch_trivia_json(TRIVIA_TOKEN_RESET_URL.format(token=quote(token, safe="")))
        new_token = str(payload.get("token") or token).strip()
        if not new_token:
            raise RuntimeError("Trivia token reset returned no token.")
        self._trivia_token = new_token
        self._trivia_questions = []
        self._trivia_index = 0
        return new_token

    async def _refresh_trivia_batch_locked(self) -> None:
        token = await self._ensure_trivia_token()
        for attempt in range(2):
            payload = await self._fetch_trivia_json(TRIVIA_BATCH_URL.format(amount=TRIVIA_BATCH_SIZE, token=quote(token, safe="")))
            response_code = int(payload.get("response_code", -1))
            if response_code == 0:
                results = payload.get("results") or []
                questions = [self._prepare_trivia_question(item) for item in results if isinstance(item, dict)]
                questions = [question for question in questions if question.question and question.correct_answer and len(question.options) == 4]
                if not questions:
                    raise RuntimeError("Trivia service returned no usable questions.")
                self._trivia_questions = questions
                self._trivia_index = 0
                return
            if response_code == 4 and attempt == 0:
                token = await self._reset_trivia_token()
                continue
            raise RuntimeError(f"Trivia service failed with response code {response_code}.")

    async def _get_next_trivia_question(self) -> TriviaQuestion:
        async with self._trivia_fetch_lock:
            if self._trivia_index >= len(self._trivia_questions):
                await self._refresh_trivia_batch_locked()
            question = self._trivia_questions[self._trivia_index]
            self._trivia_index += 1
            return question

    def _build_trivia_embed(self, session: TriviaSession, *, state: str = "active") -> discord.Embed:
        question = session.current_question
        description = "Answer directly in chat. The first correct answer wins."
        if question is None:
            description = "Loading the next trivia question..."
        embed = discord.Embed(
            title="Trivia",
            description=description,
            color=EMBED_COLOR,
        )
        embed.set_author(name="Cadis Etrama Di Raizel")
        embed.add_field(name="Round", value=str(max(1, session.round_number)), inline=True)
        if question is not None:
            embed.add_field(name="Category", value=question.category, inline=True)
            embed.add_field(name="Difficulty", value=question.difficulty.title(), inline=True)
            embed.add_field(name="Question", value=question.question, inline=False)
            option_lines = [
                f"`{chr(65 + index)}` {option}"
                for index, option in enumerate(question.options)
            ]
            embed.add_field(name="Options", value="\n".join(option_lines), inline=False)
            reward_coins, reward_xp = self._trivia_rewards_for_difficulty(question.difficulty)
            embed.add_field(name="Reward", value=f"{reward_coins} coins + {reward_xp} XP", inline=True)
            time_left = 0
            if not session.question_resolved and session.last_activity_at > 0:
                elapsed = time.monotonic() - session.last_activity_at
                time_left = max(0, int(TRIVIA_QUESTION_TIMEOUT_SECONDS - elapsed))
            embed.add_field(name="Time Left", value=_format_relative_seconds(time_left), inline=True)
            embed.add_field(name="How To Answer", value="Type the answer text or the option letter (`A`, `B`, `C`, `D`) in chat.", inline=False)
        if session.result_note:
            embed.add_field(name="Result", value=session.result_note, inline=False)
        if state == "ended":
            embed.set_footer(text="Trivia session ended.")
        else:
            embed.set_footer(text="Only one trivia session can run in a channel.")
        return embed

    async def _refresh_trivia_message(self, session: TriviaSession, *, state: str = "active") -> None:
        if session.message is None:
            return
        with contextlib.suppress(discord.HTTPException):
            await session.message.edit(embed=self._build_trivia_embed(session, state=state), view=None)

    async def _start_next_trivia_question(self, session: TriviaSession, *, intro_note: Optional[str] = None) -> None:
        question = await self._get_next_trivia_question()
        async with session.lock:
            if session.resolved:
                return
            self._cancel_session_task(session.question_task)
            self._cancel_session_task(session.advance_task)
            session.advance_task = None
            session.question_task = None
            session.current_question = question
            session.round_number += 1
            session.question_resolved = False
            session.answered_user_ids.clear()
            session.last_activity_at = time.monotonic()
            session.winner_id = None
            session.payout_amount = 0
            session.xp_reward = 0
            session.result_note = intro_note
            await self._refresh_trivia_message(session)
            session.question_task = self._track_session_task(
                asyncio.create_task(self._trivia_question_timeout(session, session.round_number))
            )

    async def _advance_trivia_after_delay(self, session: TriviaSession) -> None:
        try:
            await asyncio.sleep(TRIVIA_NEXT_QUESTION_DELAY_SECONDS)
            if session.resolved:
                return
            await self._start_next_trivia_question(session)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.warning("Failed to advance trivia session in channel %s", session.channel_id, exc_info=True)
            async with session.lock:
                if session.resolved:
                    return
                session.resolved = True
                session.result_note = "Trivia ended because the next question could not be loaded."
                await self._refresh_trivia_message(session, state="ended")
                self._close_trivia_session(session)

    async def _trivia_question_timeout(self, session: TriviaSession, round_number: int) -> None:
        try:
            await asyncio.sleep(TRIVIA_QUESTION_TIMEOUT_SECONDS)
            async with session.lock:
                if session.resolved or session.current_question is None or session.round_number != round_number or session.question_resolved:
                    return
                session.question_resolved = True
                session.result_note = f"Time ran out. Correct answer: **{session.current_question.correct_answer}**"
                await self._refresh_trivia_message(session, state="timeout")
                session.question_task = None
                idle_elapsed = time.monotonic() - session.last_activity_at
                if idle_elapsed >= TRIVIA_SESSION_IDLE_TIMEOUT_SECONDS:
                    session.resolved = True
                    session.result_note = (
                        f"Trivia ended due to inactivity.\nLast answer: **{session.current_question.correct_answer}**"
                    )
                    await self._refresh_trivia_message(session, state="ended")
                    self._close_trivia_session(session)
                    return
                session.advance_task = self._track_session_task(asyncio.create_task(self._advance_trivia_after_delay(session)))
        except asyncio.CancelledError:
            return

    async def _handle_trivia_guess(self, message: discord.Message, session: TriviaSession) -> Optional[bool]:
        submitted = _normalize_guess_text(message.content)
        if not submitted:
            return None
        async with session.lock:
            question = session.current_question
            if session.resolved or session.question_resolved or question is None:
                return None
            first_token = _normalize_lookup(message.content.split(maxsplit=1)[0]) if message.content.strip() else ""
            if first_token in RESERVED_TEXT_GAME_WORDS or first_token in {"trivia"}:
                return None
            option_letters = {chr(97 + index): option for index, option in enumerate(question.options)}
            correct_aliases = {
                _normalize_guess_text(question.correct_answer),
                _normalize_guess_text(question.correct_answer.replace(" ", "")),
                chr(97 + question.correct_index),
            }
            if submitted in option_letters and option_letters[submitted] != question.correct_answer:
                session.last_activity_at = time.monotonic()
                session.result_note = f"**{message.content.strip()}** is not correct."
                return False
            if submitted not in correct_aliases:
                session.last_activity_at = time.monotonic()
                return False
            reward_coins, reward_xp = self._trivia_rewards_for_difficulty(question.difficulty)
            payout_result = await self._run_db(
                self._settle_blackjack_payout_sync,
                session.guild_id,
                message.author.id,
                _display_name(message.author),
                reward_coins,
            )
            await self._grant_profile_xp(guild_id=session.guild_id, user=message.author, amount=reward_xp)
            session.question_resolved = True
            session.last_activity_at = time.monotonic()
            session.winner_id = message.author.id
            session.payout_amount = reward_coins if payout_result.get("status") == "success" else 0
            session.xp_reward = reward_xp
            session.result_note = (
                f"**{_display_name(message.author)}** answered correctly.\n"
                f"Correct answer: **{question.correct_answer}**\n"
                f"Reward: **{session.payout_amount} coins** + **{session.xp_reward} XP**"
            )
            self._cancel_session_task(session.question_task)
            session.question_task = None
            await self._refresh_trivia_message(session, state="correct")
            session.advance_task = self._track_session_task(asyncio.create_task(self._advance_trivia_after_delay(session)))
            return True

    async def _process_active_trivia_message(self, message: discord.Message) -> bool:
        if message.guild is None or message.author.bot:
            return False
        session = self._trivia_sessions.get(self._channel_game_key(message.guild.id, message.channel.id))
        if session is None or session.resolved:
            return False
        result = await self._handle_trivia_guess(message, session)
        if result is None:
            return False
        await self._react_to_game_guess(message, correct=result)
        return True

    def _drawgame_phase_fraction(self, phase: int) -> float:
        mapping = {0: 0.15, 1: 0.35, 2: 0.60, 3: 1.0}
        return mapping.get(max(0, min(3, phase)), 1.0)

    def _drawgame_reward_amount(self, session: DrawGameSession) -> int:
        phase_penalty = session.reveal_phase * 25
        hint_penalty = session.hint_level * 35
        return max(60, int(session.reward_base - phase_penalty - hint_penalty))

    def _drawgame_hint_text(self, session: DrawGameSession) -> str:
        answer = session.answer
        if session.hint_level <= 0:
            return "No hints used yet."
        if session.hint_level == 1:
            return f"Starts with **{answer[:1].upper()}**."
        if session.hint_level == 2:
            compact = answer.replace(" ", "")
            return f"It has **{len(compact)}** letters."
        return session.clue

    def _build_drawgame_embed(self, session: DrawGameSession, *, reveal_answer: bool = False) -> discord.Embed:
        time_left = max(0, int(DRAWGAME_TIMEOUT_SECONDS - (time.monotonic() - session.started_at)))
        embed = discord.Embed(
            title="Quick Draw Guessing Game",
            description="Guess the drawing!",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Cadis Etrama Di Raizel")
        embed.add_field(name="Reveal Phase", value=f"{session.reveal_phase + 1}/4", inline=True)
        embed.add_field(name="Time Left", value=_format_relative_seconds(time_left), inline=True)
        embed.add_field(name="Current Reward", value=_format_coin_reward(self._drawgame_reward_amount(session)), inline=True)
        embed.add_field(name="Hint Status", value=self._drawgame_hint_text(session), inline=False)
        if reveal_answer:
            embed.add_field(name="Answer", value=f"**{session.answer.title()}**", inline=False)
        if session.result_note:
            embed.add_field(name="Result", value=session.result_note, inline=False)
        else:
            embed.add_field(name="How To Play", value="Guess with normal chat messages. Use `hint` for a clue.", inline=False)
        embed.set_image(url="attachment://drawgame.png")
        embed.set_footer(text="Only one message-based guessing game can be active in a channel.")
        return embed

    def _build_drawgame_loading_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="Quick Draw Guessing Game",
            description="Loading drawing...",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Cadis Etrama Di Raizel")
        embed.add_field(
            name="Status",
            value="Preparing a valid Quick Draw sample and rendering the first reveal phase.",
            inline=False,
        )
        embed.set_footer(text="The game message will update as soon as the drawing is ready.")
        return embed

    async def _render_quickdraw_png_async(self, drawing: list[list[list[int]]], *, fraction: float) -> io.BytesIO:
        return await asyncio.to_thread(self._render_quickdraw_png, drawing, fraction=fraction)

    async def _refresh_drawgame_message(self, session: DrawGameSession, *, reveal_answer: bool = False) -> None:
        if session.message is None:
            return
        image_bytes = await self._render_quickdraw_png_async(
            session.drawing,
            fraction=self._drawgame_phase_fraction(session.reveal_phase),
        )
        file = discord.File(image_bytes, filename="drawgame.png")
        with contextlib.suppress(discord.HTTPException):
            await session.message.edit(
                embed=self._build_drawgame_embed(session, reveal_answer=reveal_answer),
                attachments=[file],
            )

    async def _timeout_drawgame_session(self, session: DrawGameSession) -> None:
        try:
            await asyncio.sleep(DRAWGAME_TIMEOUT_SECONDS)
            async with session.lock:
                if session.resolved:
                    return
                session.resolved = True
                session.result_note = "Time ran out. No one solved the drawing this round."
                await self._refresh_drawgame_message(session, reveal_answer=True)
                self._close_drawgame_session(session)
        except asyncio.CancelledError:
            return

    async def _run_drawgame_reveal_loop(self, session: DrawGameSession) -> None:
        try:
            for phase_index, delay in enumerate(DRAWGAME_PHASE_DELAYS[1:], start=1):
                await asyncio.sleep(delay)
                async with session.lock:
                    if session.resolved:
                        return
                    session.reveal_phase = phase_index
                    session.result_note = "More of the drawing has been revealed."
                    await self._refresh_drawgame_message(session)
        except asyncio.CancelledError:
            return

    async def _resolve_drawgame_win(self, session: DrawGameSession, winner: discord.abc.User) -> None:
        if session.resolved:
            return
        payout = self._drawgame_reward_amount(session)
        payout_result = await self._run_db(
            self._settle_blackjack_payout_sync,
            session.guild_id,
            winner.id,
            _display_name(winner),
            payout,
        )
        session.resolved = True
        session.winner_id = winner.id
        session.payout_amount = payout if payout_result.get("status") == "success" else 0
        session.result_note = f"**{_display_name(winner)}** guessed the drawing correctly and won {_format_coin_reward(session.payout_amount)}."
        await self._refresh_drawgame_message(session, reveal_answer=True)
        self._close_drawgame_session(session)

    def _hangman_mask(self, session: HangmanSession) -> str:
        parts: list[str] = []
        for char in session.answer:
            if not char.isalpha():
                parts.append(char)
            elif char.lower() in session.guessed_letters:
                parts.append(char.upper())
            else:
                parts.append("_")
        return " ".join(parts)

    def _build_hangman_embed(self, session: HangmanSession, *, reveal_answer: bool = False) -> discord.Embed:
        time_left = 0
        if session.timeout_task is not None and not session.timeout_task.done():
            time_left = max(0, int(HANGMAN_TIMEOUT_SECONDS - (time.monotonic() - session.started_at)))
        embed = discord.Embed(
            title="Hangman",
            description="Guess letters or the full word through normal chat messages.",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Cadis Etrama Di Raizel")
        embed.add_field(name="Word", value=self._hangman_mask(session) if not reveal_answer else session.answer.upper(), inline=False)
        guessed = ", ".join(sorted(letter.upper() for letter in session.guessed_letters)) if session.guessed_letters else "None"
        embed.add_field(name="Guessed Letters", value=guessed, inline=True)
        embed.add_field(name="Attempts Left", value=f"{session.remaining_attempts}/{session.max_attempts}", inline=True)
        reward_value = session.payout_amount if session.resolved and session.payout_amount > 0 else max(40, session.reward_base + session.remaining_attempts * 15)
        embed.add_field(name="Reward", value=_format_coin_reward(reward_value), inline=True)
        embed.add_field(name="Time Left", value=_format_relative_seconds(time_left), inline=False)
        if session.result_note:
            embed.add_field(name="Result", value=session.result_note, inline=False)
        embed.set_footer(text="Only one channel-wide text guessing game can run at a time.")
        return embed

    async def _timeout_hangman_session(self, session: HangmanSession) -> None:
        try:
            await asyncio.sleep(HANGMAN_TIMEOUT_SECONDS)
            async with session.lock:
                if session.resolved:
                    return
                session.resolved = True
                session.result_note = f"Time ran out. The word was **{session.answer.upper()}**."
                if session.message is not None:
                    with contextlib.suppress(discord.HTTPException):
                        await session.message.edit(embed=self._build_hangman_embed(session, reveal_answer=True))
                self._close_hangman_session(session)
        except asyncio.CancelledError:
            return

    def _build_wordchain_embed(self, session: WordChainSession, *, ended: bool = False) -> discord.Embed:
        embed = discord.Embed(
            title="Word Chain",
            description="Keep the chain alive by starting with the required letter.",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Cadis Etrama Di Raizel")
        embed.add_field(name="Last Word", value=session.current_word.title(), inline=True)
        embed.add_field(name="Required Letter", value=session.required_letter.upper(), inline=True)
        reward_preview = session.payout_amount if session.resolved and session.payout_amount > 0 else max(25, 35 + len(session.history) * 12)
        embed.add_field(name="Current Reward", value=_format_coin_reward(reward_preview), inline=True)
        recent_lines = [
            f"{player_name}: **{word}**"
            for player_name, word in session.history[-6:]
        ]
        embed.add_field(name="Recent Chain", value="\n".join(recent_lines) if recent_lines else "Chain not started yet.", inline=False)
        if session.result_note:
            embed.add_field(name="Result", value=session.result_note, inline=False)
        elif not ended:
            embed.add_field(name="How To Play", value="Send one valid word that starts with the required letter.", inline=False)
        embed.set_footer(text="The turn timer resets after each valid word.")
        return embed

    async def _timeout_wordchain_session(self, session: WordChainSession) -> None:
        try:
            await asyncio.sleep(WORDCHAIN_TURN_TIMEOUT_SECONDS)
            async with session.lock:
                if session.resolved:
                    return
                session.resolved = True
                reward = max(25, 35 + len(session.history) * 12)
                if session.last_contributor_id is not None and session.last_contributor_name is not None:
                    payout_result = await self._run_db(
                        self._settle_blackjack_payout_sync,
                        session.guild_id,
                        session.last_contributor_id,
                        session.last_contributor_name,
                        reward,
                    )
                    session.payout_amount = reward if payout_result.get("status") == "success" else 0
                    session.result_note = (
                        f"No valid word arrived in time.\n"
                        f"**{session.last_contributor_name}** was the last valid contributor and earned {_format_coin_reward(session.payout_amount)}."
                    )
                else:
                    session.result_note = "No valid word arrived in time, so the chain ended with no payout."
                if session.message is not None:
                    with contextlib.suppress(discord.HTTPException):
                        await session.message.edit(embed=self._build_wordchain_embed(session, ended=True))
                self._close_wordchain_session(session)
        except asyncio.CancelledError:
            return

    def _restart_wordchain_timeout(self, session: WordChainSession) -> None:
        self._cancel_session_task(session.timeout_task)
        session.timeout_task = self._track_session_task(asyncio.create_task(self._timeout_wordchain_session(session)))

    async def _finish_blackjack_session(self, session: BlackjackSession, *, outcome: str, note: str) -> dict[str, Any]:
        if session.resolved:
            return {"status": "already_resolved", "wallet": None}
        session.resolved = True
        session.outcome = outcome
        payout_amount = 0
        if outcome == "push":
            payout_amount = session.bet
        elif outcome == "blackjack":
            payout_amount = int(session.bet * 2.5)
        elif outcome == "win":
            payout_amount = session.bet * 2
        wallet = None
        if payout_amount > 0:
            profile = await self._run_db(
                self._get_income_snapshot_sync,
                session.guild_id,
                session.user_id,
                session.display_name,
            )
            blackjack_bonus = 0.0
            if isinstance(profile.get("item_effects"), dict):
                blackjack_bonus = float(profile["item_effects"].get("action_bonus", {}).get("blackjack", 0.0))
            payout_amount = int(round(payout_amount * (1.0 + min(blackjack_bonus, 0.25))))
            payout_result = await self._run_db(
                self._settle_blackjack_payout_sync,
                session.guild_id,
                session.user_id,
                session.display_name,
                payout_amount,
            )
            wallet = payout_result.get("wallet") if payout_result.get("status") == "success" else None
        session.result_note = note
        session.payout_amount = payout_amount
        session.wallet_after = wallet
        await self._run_db(
            self._record_blackjack_outcome_sync,
            session.guild_id,
            session.user_id,
            session.display_name,
            outcome,
            payout_amount,
        )
        self._blackjack_sessions.pop(self._blackjack_session_key(session.guild_id, session.user_id), None)
        return {"status": outcome, "wallet": wallet, "payout_amount": payout_amount}

    async def _resolve_blackjack_dealer(self, session: BlackjackSession, *, timeout_note: Optional[str] = None) -> dict[str, Any]:
        if session.resolved:
            return {"status": "already_resolved"}
        player_total = self._blackjack_hand_value(session.player_hand)
        dealer_total = self._blackjack_hand_value(session.dealer_hand)
        while dealer_total < 17:
            self._blackjack_draw(session.dealer_hand, session.deck)
            dealer_total = self._blackjack_hand_value(session.dealer_hand)
        if dealer_total > 21:
            note = f"{timeout_note + ' ' if timeout_note else ''}Dealer busted at **{dealer_total}**. You win."
            return await self._finish_blackjack_session(session, outcome="win", note=note.strip())
        if player_total > dealer_total:
            note = f"{timeout_note + ' ' if timeout_note else ''}Your **{player_total}** beat the dealer's **{dealer_total}**."
            return await self._finish_blackjack_session(session, outcome="win", note=note.strip())
        if player_total < dealer_total:
            note = f"{timeout_note + ' ' if timeout_note else ''}Dealer held **{dealer_total}** against your **{player_total}**."
            return await self._finish_blackjack_session(session, outcome="loss", note=note.strip())
        note = f"{timeout_note + ' ' if timeout_note else ''}Push. You and the dealer both landed on **{player_total}**."
        return await self._finish_blackjack_session(session, outcome="push", note=note.strip())

    async def _start_multiplayer_blackjack(self, session: MultiplayerBlackjackSession) -> dict[str, Any]:
        reserve_result = await self._run_db(
            self._reserve_duel_bets_sync,
            session.guild_id,
            session.challenger_id,
            session.challenger_name,
            session.target_id,
            session.target_name,
            session.bet,
        )
        if reserve_result["status"] != "success":
            session.resolved = True
            if reserve_result["status"] == "challenger_insufficient":
                session.result_note = f"{session.challenger_name} no longer has enough coins for the hand."
            elif reserve_result["status"] == "target_insufficient":
                session.result_note = f"{session.target_name} does not have enough coins to match the table."
            else:
                session.result_note = "The multiplayer blackjack table could not reserve both bets."
            self._close_multiplayer_blackjack_session(session)
            return reserve_result
        session.accepted = True
        session.pending_acceptance = False
        session.deck = self._create_blackjack_deck()
        session.challenger_hand = []
        session.target_hand = []
        self._blackjack_draw(session.challenger_hand, session.deck)
        self._blackjack_draw(session.target_hand, session.deck)
        self._blackjack_draw(session.challenger_hand, session.deck)
        self._blackjack_draw(session.target_hand, session.deck)
        session.current_player_id = session.challenger_id
        session.result_note = f"{session.target_name} accepted. {session.challenger_name} opens the table."
        return {"status": "success"}

    async def _refund_multiplayer_blackjack_session(self, session: MultiplayerBlackjackSession, *, note: str) -> None:
        if session.resolved:
            return
        if session.accepted:
            await self._run_db(
                self._refund_duel_bets_sync,
                session.guild_id,
                session.challenger_id,
                session.challenger_name,
                session.target_id,
                session.target_name,
                session.bet,
            )
            session.refunded = True
        session.resolved = True
        session.result_note = note
        self._close_multiplayer_blackjack_session(session)

    async def _settle_multiplayer_blackjack(self, session: MultiplayerBlackjackSession) -> None:
        if session.resolved:
            return
        challenger_total = self._blackjack_hand_value(session.challenger_hand)
        target_total = self._blackjack_hand_value(session.target_hand)
        challenger_bust = challenger_total > 21
        target_bust = target_total > 21
        if challenger_bust and target_bust:
            await self._run_db(
                self._refund_duel_bets_sync,
                session.guild_id,
                session.challenger_id,
                session.challenger_name,
                session.target_id,
                session.target_name,
                session.bet,
            )
            session.resolved = True
            session.refunded = True
            session.result_note = "Both players busted. The table ends as a tie and both bets are returned."
            self._close_multiplayer_blackjack_session(session)
            return
        if challenger_bust:
            winner_id = session.target_id
            winner_name = session.target_name
            note = f"{session.challenger_name} busted at **{challenger_total}**. {session.target_name} takes the table."
        elif target_bust:
            winner_id = session.challenger_id
            winner_name = session.challenger_name
            note = f"{session.target_name} busted at **{target_total}**. {session.challenger_name} takes the table."
        elif challenger_total > target_total:
            winner_id = session.challenger_id
            winner_name = session.challenger_name
            note = f"{session.challenger_name}'s **{challenger_total}** beats {session.target_name}'s **{target_total}**."
        elif target_total > challenger_total:
            winner_id = session.target_id
            winner_name = session.target_name
            note = f"{session.target_name}'s **{target_total}** beats {session.challenger_name}'s **{challenger_total}**."
        else:
            await self._run_db(
                self._refund_duel_bets_sync,
                session.guild_id,
                session.challenger_id,
                session.challenger_name,
                session.target_id,
                session.target_name,
                session.bet,
            )
            session.resolved = True
            session.refunded = True
            session.result_note = f"Both players landed on **{challenger_total}**. The table pushes and both bets are returned."
            self._close_multiplayer_blackjack_session(session)
            return
        payout_amount = session.bet * 2
        payout_result = await self._run_db(
            self._settle_duel_winner_sync,
            session.guild_id,
            winner_id,
            winner_name,
            payout_amount,
        )
        session.resolved = True
        session.winner_id = winner_id
        session.payout_amount = payout_amount if payout_result.get("status") == "success" else 0
        session.result_note = note
        await self._run_db(
            self._record_blackjack_outcome_sync,
            session.guild_id,
            session.challenger_id,
            session.challenger_name,
            "win" if winner_id == session.challenger_id else "loss",
            payout_amount if winner_id == session.challenger_id else 0,
        )
        await self._run_db(
            self._record_blackjack_outcome_sync,
            session.guild_id,
            session.target_id,
            session.target_name,
            "win" if winner_id == session.target_id else "loss",
            payout_amount if winner_id == session.target_id else 0,
        )
        self._close_multiplayer_blackjack_session(session)

    async def _apply_multiplayer_blackjack_action(self, session: MultiplayerBlackjackSession, user_id: int, action: str) -> str:
        hand = self._multiplayer_blackjack_player_hand(session, user_id)
        player_name = self._multiplayer_blackjack_player_name(session, user_id)
        if action == "hit":
            self._blackjack_draw(hand, session.deck)
            total = self._blackjack_hand_value(hand)
            if total > 21:
                self._set_multiplayer_blackjack_flags(session, user_id, busted=True, stood=True)
                note = f"{player_name} hit **{total}** and busted."
            else:
                note = f"{player_name} drew a card and moved to **{total}**."
                return note
        else:
            total = self._blackjack_hand_value(hand)
            self._set_multiplayer_blackjack_flags(session, user_id, stood=True)
            note = f"{player_name} stands on **{total}**."
        next_player = self._advance_multiplayer_blackjack_turn(session)
        if next_player is None:
            await self._settle_multiplayer_blackjack(session)
            return session.result_note or note
        next_name = self._multiplayer_blackjack_player_name(session, next_player)
        return f"{note}\n{next_name} is up next."

    async def _resolve_coinflip_session(self, session: CoinflipSession) -> None:
        if session.resolved:
            return
        for state_text in (
            "The coin lifts into the air...",
            "It turns once under the light...",
            "The landing is about to lock in...",
        ):
            session.result_note = state_text
            if session.message is not None:
                with contextlib.suppress(discord.HTTPException):
                    await session.message.edit(embed=self._build_coinflip_embed(session))
            await asyncio.sleep(0.6)
        landed = random.choice(("heads", "tails"))
        session.revealed_side = landed
        challenger_wins = session.side_choice == landed
        winner_id = session.challenger_id if challenger_wins else session.target_id
        winner_name = session.challenger_name if challenger_wins else session.target_name
        payout_amount = session.bet * 2
        payout_result = await self._run_db(
            self._settle_duel_winner_sync,
            session.guild_id,
            winner_id,
            winner_name,
            payout_amount,
        )
        session.resolved = True
        session.winner_id = winner_id
        session.payout_amount = payout_amount if payout_result.get("status") == "success" else 0
        session.result_note = (
            f"The coin landed on **{landed.title()}**.\n"
            f"**{winner_name}** takes the full pot."
        )
        self._close_coinflip_session(session)

    async def _refund_coinflip_session(self, session: CoinflipSession, *, note: str) -> None:
        if session.resolved:
            return
        if session.accepted:
            await self._run_db(
                self._refund_duel_bets_sync,
                session.guild_id,
                session.challenger_id,
                session.challenger_name,
                session.target_id,
                session.target_name,
                session.bet,
            )
            session.refunded = True
        session.resolved = True
        session.result_note = note
        self._close_coinflip_session(session)

    async def help_func(self, message: discord.Message) -> str:
        categories = self._available_help_categories()
        view = HelpMenuView(cog=self, author_id=message.author.id, categories=categories)
        embed = self.build_help_embed()
        sent = await message.reply(embed=embed, view=view)
        view.bind_message(sent)
        return "Interactive help shown"

    async def profile_func(self, message: discord.Message, *, target_user: Optional[discord.abc.User] = None) -> str:
        if message.guild is None:
            await message.reply("Profiles are only available inside a server.")
            return "Profile unavailable in DMs"
        target = target_user or message.author
        async with self._profile_lock:
            snapshot = self._profile_snapshot(guild=message.guild, target_user=target)
        economy_profile = await self._run_db(
            self._get_economy_profile_sync,
            message.guild.id,
            target.id,
            _display_name(target),
        )
        embed = self._build_profile_embed(
            guild=message.guild,
            target_user=target,
            snapshot=snapshot,
            economy_profile=economy_profile,
        )
        await message.reply(embed=embed)
        return f"Profile shown for {_display_name(target)}"

    async def xp_leaderboard_func(self, message: discord.Message, *, page: int = 1) -> str:
        if message.guild is None:
            await message.reply("XP leaderboard is only available inside a server.")
            return "XP leaderboard unavailable in DMs"
        async with self._profile_lock:
            embed = self._build_xp_leaderboard_embed(guild=message.guild, page=page)
        await message.reply(embed=embed)
        return f"XP leaderboard page {page}"

    async def avatar_func(self, message: discord.Message, *, target_user: Optional[discord.abc.User] = None) -> str:
        target = target_user or message.author
        embed = discord.Embed(
            title="Cadis Etrama Di Raizel",
            description=f"Avatar for **{_display_name(target)}**",
            color=EMBED_COLOR,
        )
        embed.set_image(url=target.display_avatar.url)
        embed.set_footer(text=f"User ID: {target.id}")
        await message.reply(embed=embed)
        return f"Avatar shown for {_display_name(target)}"

    async def banner_func(self, message: discord.Message, *, target_user: Optional[discord.abc.User] = None) -> str:
        target = target_user or message.author
        try:
            fetched = await self.bot.fetch_user(target.id)
        except Exception:
            logger.exception("Failed to fetch user banner for %s", target.id)
            await message.reply("I couldn't fetch that user's banner right now.")
            return "Banner fetch failed"
        if fetched.banner is None:
            await message.reply(f"{_display_name(target)} does not have a banner set.")
            return "No banner"
        embed = discord.Embed(
            title="Cadis Etrama Di Raizel",
            description=f"Banner for **{_display_name(target)}**",
            color=EMBED_COLOR,
        )
        embed.set_image(url=fetched.banner.url)
        await message.reply(embed=embed)
        return f"Banner shown for {_display_name(target)}"

    async def userinfo_func(self, message: discord.Message, *, target_user: Optional[discord.abc.User] = None) -> str:
        target = target_user or message.author
        member = target if isinstance(target, discord.Member) else (message.guild.get_member(target.id) if message.guild else None)
        try:
            fetched = await self.bot.fetch_user(target.id)
        except Exception:
            fetched = target
        embed = discord.Embed(
            title="Cadis Etrama Di Raizel",
            description=f"User information for **{_display_name(target)}**",
            color=EMBED_COLOR,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Username", value=str(target), inline=True)
        embed.add_field(name="Display Name", value=_display_name(target), inline=True)
        embed.add_field(name="User ID", value=str(target.id), inline=True)
        embed.add_field(name="Created", value=discord.utils.format_dt(target.created_at, "F"), inline=False)
        if member and member.joined_at:
            embed.add_field(name="Joined Server", value=discord.utils.format_dt(member.joined_at, "F"), inline=False)
        embed.add_field(name="Avatar", value=f"[Open Avatar]({target.display_avatar.url})", inline=False)
        if getattr(fetched, "banner", None):
            embed.add_field(name="Banner", value=f"[Open Banner]({fetched.banner.url})", inline=False)
        else:
            embed.add_field(name="Banner", value="No banner set.", inline=False)
        await message.reply(embed=embed)
        return f"User info shown for {_display_name(target)}"

    async def translate_func(self, message: discord.Message, *, raw_text: str) -> str:
        try:
            source, target, content = self._parse_translate_request(raw_text)
        except ValueError as exc:
            await message.reply(str(exc))
            return "Translate usage error"
        if _argos_translate is None:
            await message.reply("Local translation backend is not available right now.")
            return "Translate backend unavailable"
        try:
            translated = await asyncio.to_thread(_argos_translate.translate, content, source, target)
        except Exception:
            logger.exception("Local translation failed for %s -> %s", source, target)
            await message.reply("Translation backend is installed, but that language pair is not ready yet.")
            return "Translate failed"
        embed = discord.Embed(
            title="Cadis Etrama Di Raizel",
            description="Local translation result.",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Translate")
        embed.add_field(name=f"{source.upper()} Input", value=content[:1024], inline=False)
        embed.add_field(name=f"{target.upper()} Output", value=(translated or "(empty)")[:1024], inline=False)
        await message.reply(embed=embed)
        return f"Translated {source}->{target}"

    async def rewrite_func(self, message: discord.Message, *, raw_text: str) -> str:
        try:
            mode, content = self._parse_rewrite_request(raw_text)
        except ValueError as exc:
            await message.reply(str(exc))
            return "Rewrite usage error"
        if not content:
            await message.reply("Give me some text to rewrite.")
            return "Rewrite empty"
        rewritten = self._rewrite_text(content, mode)
        embed = discord.Embed(
            title="Cadis Etrama Di Raizel",
            description="Local rule-based rewrite result.",
            color=EMBED_COLOR,
        )
        embed.set_author(name=f"Rewrite ({mode})")
        embed.add_field(name="Output", value=rewritten[:1024], inline=False)
        await message.reply(embed=embed)
        return f"Rewrite complete ({mode})"

    async def explain_func(self, message: discord.Message, *, raw_text: str) -> str:
        content = (raw_text or "").strip()
        if not content:
            await message.reply("Usage: explain <text> or explain verysimple <text>")
            return "Explain usage error"
        mode = "simple"
        lowered = content.lower()
        for candidate in ("verysimple", "simple"):
            if lowered.startswith(f"{candidate} "):
                mode = candidate
                content = content[len(candidate):].strip()
                break
        if not content:
            await message.reply("Give me some text to explain.")
            return "Explain empty"
        explained = self._explain_text(content, mode)
        embed = discord.Embed(
            title="Cadis Etrama Di Raizel",
            description="Local simplified explanation.",
            color=EMBED_COLOR,
        )
        embed.set_author(name=f"Explain ({mode})")
        embed.add_field(name="Output", value=explained[:1024], inline=False)
        await message.reply(embed=embed)
        return f"Explain complete ({mode})"

    async def balance_func(self, message: discord.Message, *, target_user: Optional[discord.abc.User] = None) -> str:
        if message.guild is None:
            await message.reply("Economy commands are only available inside a server.")
            return "Balance unavailable in DMs"
        target = target_user or message.author
        profile = await self._run_db(self._get_economy_profile_sync, message.guild.id, target.id, _display_name(target))
        await message.reply(embed=self._build_balance_embed(target_user=target, profile=profile))
        return f"Balance shown for {_display_name(target)}"

    async def jobs_func(self, message: discord.Message) -> str:
        await message.reply(embed=self._build_jobs_embed())
        return "Jobs shown"

    async def choose_job_func(self, message: discord.Message, *, raw_job_name: str) -> str:
        if message.guild is None:
            await message.reply("Jobs are only available inside a server.")
            return "Choose job unavailable in DMs"
        normalized = _normalize_lookup(raw_job_name)
        if normalized.startswith("choose "):
            normalized = _normalize_lookup(normalized[len("choose "):])
        if normalized.startswith("job "):
            normalized = _normalize_lookup(normalized[len("job "):])
        profession = PROFESSION_LOOKUP.get(normalized)
        if profession is None:
            suggestions = ", ".join(entry["name"] for entry in PROFESSIONS[:5])
            await message.reply(
                "That job was not found. Use `jobs` to see the full list.\n"
                f"Examples: {suggestions}"
            )
            return "Unknown job"
        await self._run_db(self._choose_job_sync, message.guild.id, message.author.id, _display_name(message.author), profession["key"])
        await message.reply(f"Your profession is now **{profession['name']}**.")
        return f"Job changed to {profession['name']}"

    async def current_job_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Jobs are only available inside a server.")
            return "Current job unavailable in DMs"
        profile = await self._run_db(self._get_economy_profile_sync, message.guild.id, message.author.id, _display_name(message.author))
        await message.reply(embed=self._build_current_job_embed(profile=profile))
        return "Current job shown"

    async def job_upgrade_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Job upgrades are only available inside a server.")
            return "Job upgrade unavailable in DMs"
        result = await self._run_db(
            self._job_upgrade_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
        )
        if result["status"] == "max":
            await message.reply(f"Your **{result['profession']}** career is already at the level cap.")
            return "Job upgrade max"
        if result["status"] == "xp_needed":
            await message.reply(
                f"You need more profession XP before upgrading **{result['profession']}**.\n"
                f"Progress: **{result['xp']} / {result['required_xp']} XP**\n"
                f"Upgrade Cost: **{result['cost']} coins**"
            )
            return "Job upgrade xp needed"
        if result["status"] == "insufficient":
            await message.reply(
                f"You need **{result['cost']} coins** to upgrade **{result['profession']}**, "
                f"but your wallet is only **{result['wallet']} coins**."
            )
            return "Job upgrade insufficient"
        if result["status"] == "success":
            await message.reply(
                f"Your **{result['profession']}** profession reached **Level {result['level']}**.\n"
                f"Upgrade Cost Paid: **{result['cost']} coins**\n"
                f"Wallet: **{result['wallet']} coins**"
            )
            return "Job upgraded"
        await message.reply("That job upgrade could not be completed right now.")
        return "Job upgrade failed"

    async def achievements_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Achievements are only available inside a server.")
            return "Achievements unavailable in DMs"
        snapshot = await self._run_db(
            self._get_achievements_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
        )
        await message.reply(
            embed=self._build_achievements_embed(
                display_name=_display_name(message.author),
                entries=list(snapshot["entries"]),
            )
        )
        return "Achievements shown"

    async def quests_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Daily missions are only available inside a server.")
            return "Quests unavailable in DMs"
        snapshot = await self._run_db(
            self._get_daily_quests_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
        )
        await message.reply(
            embed=self._build_quests_embed(
                missions=list(snapshot["missions"]),
                claimed_reward=int(snapshot["claimed_reward"]),
                claimed_count=int(snapshot["claimed_count"]),
            )
        )
        return "Quests shown"

    async def income_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Passive income is only available inside a server.")
            return "Income unavailable in DMs"
        profile = await self._run_db(
            self._get_income_snapshot_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
        )
        await message.reply(embed=self._build_income_embed(profile=profile))
        return "Income shown"

    async def collect_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Passive income collection is only available inside a server.")
            return "Collect unavailable in DMs"
        profile = await self._run_db(
            self._get_income_snapshot_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
        )
        collected = int(profile.get("auto_collected_passive", 0))
        if collected <= 0:
            await message.reply("No passive income was ready to collect right now.")
            return "Collect empty"
        await message.reply(
            f"Collected **{collected} coins** from your passive income sources.\n"
            f"Wallet: **{int(profile.get('wallet', 0))} coins**"
        )
        return "Collect complete"

    async def quick_earn_panel_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("The earn panel is only available inside a server.")
            return "Quick earn unavailable in DMs"
        view = QuickEarnView(
            cog=self,
            author_id=message.author.id,
            source_message=message,
        )
        sent = await message.reply(embed=self._build_quick_earn_embed(), view=view)
        view.bind_message(sent)
        return "Quick earn shown"

    async def _pvp_action_func(self, message: discord.Message, *, action: str, target_user: Optional[discord.abc.User]) -> str:
        if message.guild is None:
            await message.reply(f"{action.title()} is only available inside a server.")
            return f"{action} unavailable in DMs"
        if target_user is None:
            await message.reply(f"Use `{action} @user`.")
            return f"{action} target missing"
        if target_user.id == message.author.id:
            await message.reply(f"You cannot {action} yourself.")
            return f"{action} self blocked"
        result = await self._run_db(
            self._perform_pvp_action_sync,
            action,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
            target_user.id,
            _display_name(target_user),
        )
        if result["status"] == "cooldown":
            await message.reply(f"Try `{action}` again in {_format_relative_seconds(result['remaining'])}.")
            return f"{action} cooldown"
        if result["status"] == "target_poor":
            await message.reply(f"{_display_name(target_user)} does not have enough coins to make `{action}` worth attempting.")
            return f"{action} target poor"
        if result["status"] == "success":
            await message.reply(
                f"{result['message']}\n"
                f"Wallet: **{int(result['attacker_wallet'])} coins**"
            )
            return f"{action} success"
        if result["status"] == "failure":
            await message.reply(
                f"{result['message']}\n"
                f"Wallet: **{int(result['attacker_wallet'])} coins**"
            )
            return f"{action} failure"
        await message.reply(f"`{action}` could not be resolved right now.")
        return f"{action} failed"

    async def steal_func(self, message: discord.Message, *, target_user: Optional[discord.abc.User]) -> str:
        return await self._pvp_action_func(message, action="steal", target_user=target_user)

    async def rob_func(self, message: discord.Message, *, target_user: Optional[discord.abc.User]) -> str:
        return await self._pvp_action_func(message, action="rob", target_user=target_user)

    async def heist_func(self, message: discord.Message, *, target_user: Optional[discord.abc.User]) -> str:
        return await self._pvp_action_func(message, action="heist", target_user=target_user)

    async def work_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Work is only available inside a server.")
            return "Work unavailable in DMs"
        result = await self._run_db(self._perform_work_sync, message.guild.id, message.author.id, _display_name(message.author))
        if result["status"] == "cooldown":
            await message.reply(f"You can work again in {_format_relative_seconds(result['remaining'])}.")
            return "Work cooldown"
        if result["status"] == "error":
            await message.reply("Work reward could not be processed right now.")
            return "Work error"
        lines = [
            f"{result['message']}",
            f"Wallet: {_format_coin_reward(int(result['wallet']))}",
            f"Profession Progress: **{int(result['profession_xp'])}/{int(result['profession_xp_needed'])} XP**",
        ]
        wallet_bonus = float(result.get("wallet_bonus", 0.0))
        if wallet_bonus > 0:
            lines.append(f"Economy Bonus Applied: **+{int(round(wallet_bonus * 100))}%**")
        auto_upgrade = result.get("auto_upgrade")
        if isinstance(auto_upgrade, dict):
            if auto_upgrade.get("status") == "success":
                lines.append(
                    f"Auto Upgrade: **{auto_upgrade['profession']}** reached **Level {auto_upgrade['level']}** "
                    f"for **{auto_upgrade['cost']} coins**."
                )
            elif auto_upgrade.get("status") == "insufficient":
                lines.append(
                    f"Auto Upgrade Ready: enough XP for **{auto_upgrade['profession']}**, "
                    f"but you still need **{auto_upgrade['cost']} coins**."
                )
        await message.reply("\n".join(lines))
        return "Work complete"

    async def beg_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Beg is only available inside a server.")
            return "Beg unavailable in DMs"
        result = await self._run_db(self._perform_beg_sync, message.guild.id, message.author.id, _display_name(message.author))
        if result["status"] == "cooldown":
            await message.reply(f"Slow down a little. Try again in {_format_relative_seconds(result['remaining'])}.")
            return "Beg cooldown"
        if result["status"] == "failure":
            await message.reply(result["message"])
            return "Beg failed"
        if result["status"] == "error":
            await message.reply("Beg reward could not be processed right now.")
            return "Beg error"
        await message.reply(result["message"])
        return "Beg complete"

    async def _generic_earning_func(self, message: discord.Message, *, action: str, minimum: int, maximum: int, messages: tuple[str, ...]) -> str:
        if message.guild is None:
            await message.reply(f"{action.title()} is only available inside a server.")
            return f"{action} unavailable in DMs"
        result = await self._run_db(
            self._perform_simple_earning_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
            action,
            minimum,
            maximum,
            messages,
            (),
            0.0,
        )
        if result["status"] == "cooldown":
            await message.reply(f"Try `{action}` again in {_format_relative_seconds(result['remaining'])}.")
            return f"{action} cooldown"
        if result["status"] == "error":
            await message.reply(f"{action.title()} reward could not be processed right now.")
            return f"{action} error"
        await message.reply(result["message"])
        return f"{action} complete"

    async def fish_func(self, message: discord.Message) -> str:
        return await self._generic_earning_func(message, action="fish", minimum=25, maximum=90, messages=FISH_MESSAGES)

    async def hunt_func(self, message: discord.Message) -> str:
        return await self._generic_earning_func(message, action="hunt", minimum=30, maximum=95, messages=HUNT_MESSAGES)

    async def search_func(self, message: discord.Message) -> str:
        return await self._generic_earning_func(message, action="search", minimum=18, maximum=70, messages=SEARCH_MESSAGES)

    async def mine_func(self, message: discord.Message) -> str:
        return await self._generic_earning_func(message, action="mine", minimum=35, maximum=100, messages=MINE_MESSAGES)

    async def deliver_func(self, message: discord.Message) -> str:
        return await self._generic_earning_func(message, action="deliver", minimum=28, maximum=92, messages=DELIVER_MESSAGES)

    async def scavenge_func(self, message: discord.Message) -> str:
        return await self._generic_earning_func(message, action="scavenge", minimum=15, maximum=65, messages=SCAVENGE_MESSAGES)

    async def freelance_func(self, message: discord.Message) -> str:
        return await self._generic_earning_func(message, action="freelance", minimum=38, maximum=115, messages=FREELANCE_MESSAGES)

    async def craft_func(self, message: discord.Message) -> str:
        return await self._generic_earning_func(message, action="craft", minimum=32, maximum=102, messages=CRAFT_MESSAGES)

    async def repair_func(self, message: discord.Message) -> str:
        return await self._generic_earning_func(message, action="repair", minimum=34, maximum=108, messages=REPAIR_MESSAGES)

    async def patrol_func(self, message: discord.Message) -> str:
        return await self._generic_earning_func(message, action="patrol", minimum=36, maximum=112, messages=PATROL_MESSAGES)

    async def quiz_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Quiz is only available inside a server.")
            return "Quiz unavailable in DMs"
        result = await self._run_db(self._start_quiz_sync, message.guild.id, message.author.id, _display_name(message.author))
        if result["status"] == "active":
            await message.reply(
                f"Your current quiz is still active: **{result['question']}**\n"
                f"Only you can answer with `answer <number>` within {_format_relative_seconds(result['remaining'])}."
            )
            return "Quiz already active"
        await message.reply(
            f"Math quiz: **{result['question']}**\n"
            f"Only you can answer with `answer <number>` within {_format_relative_seconds(result['remaining'])}.\n"
            f"Reward: {_format_coin_reward(result['reward'])}"
        )
        return "Quiz started"

    async def answer_quiz_func(self, message: discord.Message, *, raw_answer: str) -> str:
        if message.guild is None:
            await message.reply("Quiz answers are only available inside a server.")
            return "Quiz answer unavailable in DMs"
        try:
            submitted = int(str(raw_answer).strip())
        except (TypeError, ValueError):
            await message.reply("Use `answer <number>` with a valid number.")
            return "Quiz answer invalid"
        result = await self._run_db(
            self._answer_quiz_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
            submitted,
        )
        if result["status"] == "missing":
            await message.reply("You do not have an active quiz. Use `quiz` first.")
            return "No active quiz"
        if result["status"] == "expired":
            await message.reply("That quiz expired. Start a new one with `quiz`.")
            return "Quiz expired"
        if result["status"] == "wrong":
            await message.reply(f"Wrong answer. **{result['question']} = {result['correct_answer']}**.\nNo reward this time.")
            return "Quiz wrong"
        if result["status"] == "correct":
            await message.reply(f"Correct. **{result['question']}** paid out {_format_coin_reward(result['reward'])}.")
            return "Quiz correct"
        await message.reply("Something went wrong while checking your answer.")
        return "Quiz answer failed"

    async def daily_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Daily rewards are only available inside a server.")
            return "Daily unavailable in DMs"
        result = await self._run_db(self._claim_daily_sync, message.guild.id, message.author.id, _display_name(message.author))
        if result["status"] == "cooldown":
            await message.reply(f"You already claimed daily. Come back in {_format_relative_seconds(result['remaining'])}.")
            return "Daily cooldown"
        if result["status"] == "success":
            await message.reply(f"Daily reward claimed: {_format_coin_reward(result['reward'])}.")
            return "Daily claimed"
        await message.reply("Daily reward could not be claimed right now.")
        return "Daily failed"

    async def purge_func(self, message: discord.Message, *, amount: int) -> str:
        if message.guild is None:
            await message.reply("Purge can only be used inside a server.")
            return "Purge unavailable in DMs"
        if not isinstance(message.author, discord.Member) or not message.author.guild_permissions.manage_messages:
            await message.reply("You need the **Manage Messages** permission to use purge.")
            return "Purge permission denied"
        if amount < 1 or amount > 100:
            await message.reply("Use `purge <amount>` with a value between **1** and **100**.")
            return "Purge amount invalid"
        me = message.guild.me or message.guild.get_member(self.bot.user.id)
        if me is None or not message.channel.permissions_for(me).manage_messages:
            await message.reply("I need the **Manage Messages** permission in this channel to purge messages.")
            return "Purge bot permission missing"
        try:
            deleted = await message.channel.purge(limit=amount + 1)
        except discord.Forbidden:
            await message.reply("I do not have permission to delete messages here.")
            return "Purge forbidden"
        except discord.HTTPException:
            logger.exception("Purge failed in channel %s", message.channel.id)
            await message.reply("Purge failed right now. Please try again in a moment.")
            return "Purge failed"
        removed_count = max(0, len(deleted) - 1)
        with contextlib.suppress(discord.HTTPException):
            await message.channel.send(
                f"Cleared **{removed_count} messages**.",
                delete_after=5,
            )
        return f"Purged {removed_count} messages"

    async def shop_func(self, message: discord.Message, *, initial_category: Optional[str] = None) -> str:
        view = ShopMenuView(
            cog=self,
            author_id=message.author.id,
            categories=self._shop_categories(),
        )
        if initial_category in view.categories:
            view.current_category = initial_category
            view._rebuild_buttons()
        sent = await message.reply(embed=self.build_shop_embed(view.current_category), view=view)
        view.bind_message(sent)
        return "Shop shown"

    async def shopview_func(self, message: discord.Message, *, initial_category: Optional[str] = None) -> str:
        view = ShopViewMenu(
            cog=self,
            author_id=message.author.id,
            categories=self._shop_categories(),
        )
        if initial_category in view.categories:
            view.current_category = initial_category
            view.current_page = 0
            view._rebuild_buttons()
        sent = await message.reply(embed=self.build_shopview_embed(category=view.current_category, page=view.current_page), view=view)
        view.bind_message(sent)
        return "Shopview shown"

    async def petshop_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Pets are only available inside a server.")
            return "Pet shop unavailable in DMs"
        return await self.shop_func(message, initial_category="Pets")

    async def mypet_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Pets are only available inside a server.")
            return "My pet unavailable in DMs"
        owned = await self._run_db(
            self._list_owned_pets_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
        )
        await message.reply(embed=self._build_my_pet_embed(owned_rows=owned))
        return "My pet shown"

    async def _handle_pet_purchase(self, message: discord.Message, *, pet: dict[str, Any]) -> str:
        result = await self._run_db(
            self._buy_pet_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
            str(pet["key"]),
        )
        if result["status"] == "owned":
            await message.reply(f"You already own **{pet['name']}**.")
            return "Pet already owned"
        if result["status"] == "insufficient":
            await message.reply(
                f"You need **{result['price']} coins** for that pet, but your wallet is only **{result['wallet']} coins**."
            )
            return "Pet insufficient"
        if result["status"] == "success":
            await message.reply(
                f"You adopted **{pet['emoji']} {pet['name']}** for **{pet['price']} coins**.\n"
                f"Wallet: **{result['wallet']} coins**"
            )
            return "Pet bought"
        await message.reply("That pet purchase could not be completed.")
        return "Pet buy failed"

    async def buypet_func(self, message: discord.Message, *, raw_pet_name: str) -> str:
        if message.guild is None:
            await message.reply("Pets are only available inside a server.")
            return "Buy pet unavailable in DMs"
        pet = PET_LOOKUP.get(_normalize_lookup(raw_pet_name))
        if pet is None:
            await message.reply("That pet is not in the market. Open `shop` and browse the Pets category.")
            return "Unknown pet"
        return await self._handle_pet_purchase(message, pet=pet)

    async def equippet_func(self, message: discord.Message, *, raw_pet_name: str) -> str:
        if message.guild is None:
            await message.reply("Pets are only available inside a server.")
            return "Equip pet unavailable in DMs"
        pet = PET_LOOKUP.get(_normalize_lookup(raw_pet_name))
        if pet is None:
            await message.reply("That pet was not found. Open `shop` and browse the Pets category.")
            return "Unknown pet"
        result = await self._run_db(
            self._equip_pet_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
            str(pet["key"]),
        )
        if result["status"] == "missing":
            await message.reply("You do not own that pet yet.")
            return "Pet missing"
        await message.reply(f"Your equipped pet is now **{pet['emoji']} {pet['name']}**.")
        return "Pet equipped"

    async def unequippet_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Pets are only available inside a server.")
            return "Unequip pet unavailable in DMs"
        result = await self._run_db(
            self._unequip_pet_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
        )
        if result["status"] == "none":
            await message.reply("You do not have an equipped pet right now.")
            return "No pet equipped"
        pet = result.get("pet")
        await message.reply(f"You unequipped **{pet['name']}**." if pet else "Your equipped pet was cleared.")
        return "Pet unequipped"

    async def feedpet_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Pets are only available inside a server.")
            return "Feed pet unavailable in DMs"
        result = await self._run_db(
            self._feed_pet_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
        )
        if result["status"] == "none":
            await message.reply("Equip a pet first, then try `feedpet` again.")
            return "No pet to feed"
        pet = result.get("pet")
        await message.reply(f"You fed **{pet['emoji']} {pet['name']}**. It seems very pleased.")
        return "Pet fed"

    async def petinfo_func(self, message: discord.Message) -> str:
        return await self.mypet_func(message)

    async def inventory_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Inventory is only available inside a server.")
            return "Inventory unavailable in DMs"
        items = await self._run_db(self._list_inventory_sync, message.guild.id, message.author.id, _display_name(message.author))
        if not items:
            await message.reply("Your inventory is empty.")
            return "Inventory empty"
        lines = []
        bonus_lines = []
        for index, entry in enumerate(items, start=1):
            item = SHOP_ITEM_LOOKUP.get(_normalize_lookup(str(entry["item_key"])))
            item_name = item["name"] if item else str(entry["item_key"])
            lines.append(f"{index}. {_item_emoji(item_name)} {item_name} x{int(entry['quantity'])}")
            effect = ITEM_EFFECTS.get(_normalize_lookup(str(entry["item_key"])))
            if effect and effect.get("description"):
                bonus_lines.append(f"- {item_name}: {effect['description']}")
        embed = discord.Embed(title="Cadis Etrama Di Raizel", description="\n".join(lines), color=EMBED_COLOR)
        embed.set_author(name="Inventory")
        if bonus_lines:
            embed.add_field(name="Active Bonuses", value="\n".join(bonus_lines[:8]), inline=False)
        embed.set_footer(text="Use `sell <item>` to sell one copy or `sellall` to sell your whole inventory.")
        await message.reply(embed=embed)
        return "Inventory shown"

    async def buy_func(self, message: discord.Message, *, raw_item_name: str) -> str:
        if message.guild is None:
            await message.reply("Shop purchases are only available inside a server.")
            return "Buy unavailable in DMs"
        normalized = _normalize_lookup(raw_item_name)
        item = SHOP_ITEM_LOOKUP.get(normalized)
        pet = PET_LOOKUP.get(normalized)
        if pet is not None:
            return await self._handle_pet_purchase(message, pet=pet)
        if item is None:
            await message.reply("That item is not in the shop. Use `shop` to see what's available.")
            return "Unknown shop item"
        result = await self._run_db(self._buy_item_sync, message.guild.id, message.author.id, _display_name(message.author), normalized)
        if result["status"] == "insufficient":
            await message.reply(f"You need **{result['price']} coins** for that purchase, but you only have **{result['wallet']}**.")
            return "Buy insufficient funds"
        if result["status"] == "success":
            await message.reply(f"You bought **{item['name']}** for **{item['price']} coins**.\nWallet: **{result['wallet']} coins**")
            return "Item purchased"
        await message.reply("That purchase could not be completed.")
        return "Buy failed"

    async def sell_func(self, message: discord.Message, *, raw_item_name: str) -> str:
        if message.guild is None:
            await message.reply("Selling is only available inside a server.")
            return "Sell unavailable in DMs"
        normalized = _normalize_lookup(raw_item_name)
        item = SHOP_ITEM_LOOKUP.get(normalized)
        if item is None:
            if PET_LOOKUP.get(normalized) is not None:
                await message.reply("Pets cannot be sold through the item market right now.")
                return "Sell pet blocked"
            await message.reply("That item is not in the shop list. Use `inventory` to review what you own.")
            return "Unknown sell item"
        result = await self._run_db(
            self._sell_item_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
            normalized,
        )
        if result["status"] == "missing_owned":
            await message.reply("You do not own that item.")
            return "Sell missing item"
        if result["status"] == "success":
            remaining = int(result.get("remaining_quantity", 0))
            remaining_line = f"\nRemaining: **{remaining}**" if remaining > 0 else ""
            await message.reply(
                f"You sold **{item['name']}** for **{int(result['sell_price'])} coins** (70% of original value)."
                f"{remaining_line}\nWallet: **{int(result['wallet'])} coins**"
            )
            return "Item sold"
        await message.reply("That item could not be sold right now.")
        return "Sell failed"

    async def sellall_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Selling is only available inside a server.")
            return "Sellall unavailable in DMs"
        result = await self._run_db(
            self._sell_all_items_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
        )
        if result["status"] == "empty":
            await message.reply("You have no sellable inventory items right now.")
            return "Sellall empty"
        if result["status"] == "success":
            preview = ", ".join(
                f"{entry['item_name']} x{entry['quantity']}"
                for entry in list(result.get("sold_entries", []))[:4]
            )
            preview_line = f"\nSold: {preview}" if preview else ""
            await message.reply(
                f"You sold **{int(result['total_items'])} items** for a total of **{int(result['total_payout'])} coins**."
                f"{preview_line}\nWallet: **{int(result['wallet'])} coins**"
            )
            return "Sellall success"
        await message.reply("Your inventory could not be sold right now.")
        return "Sellall failed"

    async def use_item_func(self, message: discord.Message, *, raw_item_name: str) -> str:
        if message.guild is None:
            await message.reply("Items can only be used inside a server.")
            return "Use item unavailable in DMs"
        target_user = message.mentions[0] if message.mentions else None
        cleaned_item_name = self._strip_mention_markup(raw_item_name)
        normalized = _normalize_lookup(cleaned_item_name)
        item = SHOP_ITEM_LOOKUP.get(normalized)
        if item is None:
            await message.reply("That item is not in the shop list.")
            return "Unknown item"
        result = await self._run_db(self._use_item_sync, message.guild.id, message.author.id, _display_name(message.author), normalized)
        if result["status"] == "missing":
            await message.reply("You do not own that item.")
            return "Item missing"
        if result["status"] == "success":
            item_name = str(result["item"]["name"])
            usage_text = self._choose_item_use_message(item_name, target_user=target_user if item_name == "Phone" else None)
            if result.get("consumable"):
                usage_text = f"{usage_text}\nRemaining: **{int(result.get('quantity', 0))}**"
            await message.reply(usage_text)
            return "Item used"
        await message.reply("That item could not be used.")
        return "Use item failed"

    async def duel_func(self, message: discord.Message, *, target_user: Optional[discord.abc.User], amount: int) -> str:
        if message.guild is None:
            await message.reply("Duel is only available inside a server.")
            return "Duel unavailable in DMs"
        if target_user is None:
            await message.reply("Use `duel @user <amount>`.")
            return "Duel target missing"
        if target_user.id == message.author.id:
            await message.reply("You cannot duel yourself.")
            return "Duel self blocked"
        if amount <= 0:
            await message.reply("Use `duel @user <amount>` with a value greater than zero.")
            return "Duel amount invalid"
        challenger_busy = self._active_game_label_for_user(message.guild.id, message.author.id)
        if challenger_busy:
            await message.reply(f"You already have an active **{challenger_busy}** session. Finish that first.")
            return "Duel challenger busy"
        target_busy = self._active_game_label_for_user(message.guild.id, target_user.id)
        if target_busy:
            await message.reply(f"{_display_name(target_user)} already has an active **{target_busy}** session.")
            return "Duel target busy"
        challenger_key = (message.guild.id, message.author.id)
        target_key = (message.guild.id, target_user.id)
        if challenger_key in self._duel_sessions or target_key in self._duel_sessions:
            await message.reply("One of the selected players is already in an active duel.")
            return "Duel already active"
        reserve_result = await self._run_db(
            self._reserve_duel_bets_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
            target_user.id,
            _display_name(target_user),
            amount,
        )
        if reserve_result["status"] == "challenger_insufficient":
            await message.reply(f"You do not have enough coins. Wallet: **{reserve_result['wallet']} coins**")
            return "Duel challenger insufficient"
        if reserve_result["status"] == "target_insufficient":
            await message.reply(f"{_display_name(target_user)} does not have enough coins for this duel.")
            return "Duel target insufficient"
        if reserve_result["status"] != "success":
            await message.reply("That duel could not be started right now.")
            return "Duel failed"
        session = DuelSession(
            guild_id=message.guild.id,
            challenger_id=message.author.id,
            challenger_name=_display_name(message.author),
            target_id=target_user.id,
            target_name=_display_name(target_user),
            bet=amount,
        )
        self._duel_sessions[challenger_key] = session
        self._duel_sessions[target_key] = session
        view = DuelView(cog=self, session=session)
        sent = await message.reply(embed=self._build_duel_embed(session), view=view)
        view.bind_message(sent)
        return "Duel started"

    async def gamble_func(self, message: discord.Message, *, amount: int) -> str:
        if message.guild is None:
            await message.reply("Gamble is only available inside a server.")
            return "Gamble unavailable in DMs"
        if amount <= 0:
            await message.reply("Use `gamble <amount>` with a value greater than zero.")
            return "Gamble amount invalid"
        result = await self._run_db(
            self._perform_gamble_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
            amount,
        )
        if result["status"] == "insufficient":
            await message.reply(
                f"You do not have enough coins for that bet.\n"
                f"Wallet: {_format_coin_reward(int(result['wallet']))}"
            )
            return "Gamble insufficient"
        if result["status"] == "invalid":
            await message.reply("Bet amount must be greater than zero.")
            return "Gamble invalid"
        if result["status"] == "win":
            message_text = random.choice(GAMBLE_WIN_MESSAGES).format(
                risk_phrase=_format_coin_reward(amount),
                payout_phrase=_format_coin_reward(int(result["payout_total"])),
            )
            await message.reply(f"{message_text}\nWallet: {_format_coin_reward(int(result['wallet']))}")
            return "Gamble win"
        if result["status"] == "loss":
            message_text = random.choice(GAMBLE_LOSS_MESSAGES).format(
                risk_phrase=_format_coin_reward(amount),
            )
            await message.reply(f"{message_text}\nWallet: {_format_coin_reward(int(result['wallet']))}")
            return "Gamble loss"
        await message.reply("That gamble could not be resolved right now.")
        return "Gamble failed"

    async def slots_func(self, message: discord.Message, *, amount: int) -> str:
        if message.guild is None:
            await message.reply("Slots are only available inside a server.")
            return "Slots unavailable in DMs"
        if amount <= 0:
            await message.reply("Use `slots <amount>` with a value greater than zero.")
            return "Slots amount invalid"
        active_game = self._active_game_label_for_user(message.guild.id, message.author.id)
        if active_game:
            await message.reply(f"You already have an active **{active_game}** session. Finish that first.")
            return "Slots user busy"
        session_key = self._blackjack_session_key(message.guild.id, message.author.id)
        if session_key in self._slot_spins:
            await message.reply("You already have a slot spin in progress. Let that one finish first.")
            return "Slots already active"
        reserve_result = await self._run_db(
            self._reserve_blackjack_bet_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
            amount,
        )
        if reserve_result["status"] == "insufficient":
            await message.reply(
                f"You do not have enough coins for that spin.\n"
                f"Wallet: {_format_coin_reward(int(reserve_result['wallet']))}"
            )
            return "Slots insufficient"
        if reserve_result["status"] != "success":
            await message.reply("That slot spin could not start right now.")
            return "Slots failed"

        self._slot_spins.add(session_key)
        spin_message: Optional[discord.Message] = None
        try:
            reels = self._random_slot_reels()
            spin_message = await message.reply(
                embed=self._build_slots_embed(
                    bet=amount,
                    reels=reels,
                    state_text="Spinning up the reels...",
                )
            )
            for state_text in (
                "The reels blur into motion...",
                "Lights flash across the machine...",
                "Almost there...",
            ):
                await asyncio.sleep(0.7)
                reels = self._random_slot_reels()
                await spin_message.edit(
                    embed=self._build_slots_embed(
                        bet=amount,
                        reels=reels,
                        state_text=state_text,
                    )
                )

            outcome = self._roll_slot_outcome(amount)
            wallet_after = reserve_result.get("wallet")
            if outcome.payout_amount > 0:
                payout_result = await self._run_db(
                    self._settle_blackjack_payout_sync,
                    message.guild.id,
                    message.author.id,
                    _display_name(message.author),
                    outcome.payout_amount,
                )
                if payout_result.get("status") == "success":
                    wallet_after = payout_result.get("wallet")
            final_status = {
                "jackpot": "Jackpot line connected.",
                "big_win": "A rare high-value line locked in.",
                "medium_win": "A strong symbol line paid out.",
                "small_win": "A lucky partial match paid out.",
                "loss": "The reels stopped cold this round.",
            }.get(outcome.outcome, "Spin complete.")
            payout_text = outcome.result_text
            if wallet_after is not None:
                payout_text = f"{payout_text}\nWallet: {_format_coin_reward(int(wallet_after))}"
            await spin_message.edit(
                embed=self._build_slots_embed(
                    bet=amount,
                    reels=outcome.reels,
                    state_text=final_status,
                    payout_text=payout_text,
                )
            )
            await self._run_db(
                self._record_slots_result_sync,
                message.guild.id,
                message.author.id,
                _display_name(message.author),
                outcome.outcome,
                outcome.payout_amount,
            )
            return "Slots complete"
        except Exception:
            logger.exception("Slot spin failed for guild=%s user=%s", message.guild.id, message.author.id)
            await self._run_db(
                self._settle_blackjack_payout_sync,
                message.guild.id,
                message.author.id,
                _display_name(message.author),
                amount,
            )
            if spin_message is not None:
                with contextlib.suppress(discord.HTTPException):
                    await spin_message.edit(
                        embed=self._build_slots_embed(
                            bet=amount,
                            reels=self._random_slot_reels(),
                            state_text="Spin cancelled safely.",
                            payout_text=f"Your {_format_coin_reward(amount)} bet was returned.",
                        )
                    )
            else:
                await message.reply("The slot machine stalled, but your bet was returned safely.")
            return "Slots error"
        finally:
            self._slot_spins.discard(session_key)

    async def crash_func(self, message: discord.Message, *, amount: int) -> str:
        if message.guild is None:
            await message.reply("Crash is only available inside a server.")
            return "Crash unavailable in DMs"
        if amount <= 0:
            await message.reply("Use `crash <amount>` with a value greater than zero.")
            return "Crash amount invalid"
        active_game = self._active_game_label_for_user(message.guild.id, message.author.id)
        if active_game:
            await message.reply(f"You already have an active **{active_game}** session. Finish that first.")
            return "Crash user busy"
        session_key = self._blackjack_session_key(message.guild.id, message.author.id)
        existing = self._crash_sessions.get(session_key)
        if existing and not existing.resolved:
            await message.reply("You already have an active crash round. Finish that one first.")
            return "Crash already active"
        reserve_result = await self._run_db(
            self._reserve_blackjack_bet_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
            amount,
        )
        if reserve_result["status"] == "insufficient":
            await message.reply(
                f"You do not have enough coins for that crash bet.\n"
                f"Wallet: {_format_coin_reward(int(reserve_result['wallet']))}"
            )
            return "Crash insufficient"
        if reserve_result["status"] != "success":
            await message.reply("That crash round could not be started right now.")
            return "Crash failed"

        profile = await self._run_db(
            self._get_income_snapshot_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
        )
        crash_bonus = float(profile.get("crash_bonus", 0.0))
        if isinstance(profile.get("item_effects"), dict):
            crash_bonus += float(profile["item_effects"].get("action_bonus", {}).get("crash", 0.0))
        session = CrashSession(
            guild_id=message.guild.id,
            user_id=message.author.id,
            display_name=_display_name(message.author),
            bet=amount,
            crash_point=self._roll_crash_point(),
            bonus_multiplier=min(crash_bonus, 0.25),
        )
        self._crash_sessions[session_key] = session
        view = CrashView(cog=self, session=session, author_id=message.author.id)
        sent = await message.reply(embed=self._build_crash_embed(session), view=view)
        view.bind_message(sent)
        asyncio.create_task(self._run_crash_loop(session, view))
        return "Crash started"

    async def dungeon_func(self, message: discord.Message, *, amount: int) -> str:
        if message.guild is None:
            await message.reply("Dungeon is only available inside a server.")
            return "Dungeon unavailable in DMs"
        if amount <= 0:
            await message.reply("Use `dungeon <amount>` with a value greater than zero.")
            return "Dungeon amount invalid"
        active_game = self._active_game_label_for_user(message.guild.id, message.author.id)
        if active_game:
            await message.reply(f"You already have an active **{active_game}** session. Finish that first.")
            return "Dungeon user busy"
        session_key = (message.guild.id, message.author.id)
        existing = self._dungeon_sessions.get(session_key)
        if existing and not existing.resolved:
            await message.reply("You already have an active dungeon run.")
            return "Dungeon already active"
        reserve_result = await self._run_db(
            self._reserve_blackjack_bet_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
            amount,
        )
        if reserve_result["status"] == "insufficient":
            await message.reply(
                f"You do not have enough coins for that dungeon run.\n"
                f"Wallet: {_format_coin_reward(int(reserve_result['wallet']))}"
            )
            return "Dungeon insufficient"
        if reserve_result["status"] != "success":
            await message.reply("That dungeon run could not be started right now.")
            return "Dungeon failed"
        profile = await self._run_db(
            self._get_economy_profile_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
        )
        session = DungeonSession(
            guild_id=message.guild.id,
            user_id=message.author.id,
            display_name=_display_name(message.author),
            bet=amount,
            life_charges=int(profile.get("dungeon_lives", 0)),
        )
        self._dungeon_sessions[session_key] = session
        view = DungeonFighterView(cog=self, session=session, author_id=message.author.id)
        sent = await message.reply(embed=self._build_dungeon_embed(session), view=view)
        view.bind_message(sent)
        return "Dungeon started"

    async def blackjack_func(self, message: discord.Message, *, amount: int, target_user: Optional[discord.abc.User] = None) -> str:
        if message.guild is None:
            await message.reply("Blackjack is only available inside a server.")
            return "Blackjack unavailable in DMs"
        if amount <= 0:
            await message.reply("Use `blackjack <amount>` with a value greater than zero.")
            return "Blackjack amount invalid"
        if target_user is not None:
            if target_user.id == message.author.id:
                await message.reply("You cannot challenge yourself to multiplayer blackjack.")
                return "Blackjack self blocked"
            challenger_busy = self._active_game_label_for_user(message.guild.id, message.author.id)
            if challenger_busy:
                await message.reply(f"You already have an active **{challenger_busy}** session. Finish that first.")
                return "Blackjack challenger busy"
            target_busy = self._active_game_label_for_user(message.guild.id, target_user.id)
            if target_busy:
                await message.reply(f"{_display_name(target_user)} already has an active **{target_busy}** session.")
                return "Blackjack target busy"
            session = MultiplayerBlackjackSession(
                guild_id=message.guild.id,
                challenger_id=message.author.id,
                challenger_name=_display_name(message.author),
                target_id=target_user.id,
                target_name=_display_name(target_user),
                bet=amount,
            )
            self._multiplayer_blackjack_sessions[(message.guild.id, message.author.id)] = session
            self._multiplayer_blackjack_sessions[(message.guild.id, target_user.id)] = session
            view = MultiplayerBlackjackChallengeView(cog=self, session=session, author_id=message.author.id)
            sent = await message.reply(embed=self._build_multiplayer_blackjack_embed(session), view=view)
            view.bind_message(sent)
            return "Multiplayer blackjack challenge started"
        active_game = self._active_game_label_for_user(message.guild.id, message.author.id)
        if active_game:
            await message.reply(f"You already have an active **{active_game}** session. Finish that first.")
            return "Blackjack user busy"
        session_key = self._blackjack_session_key(message.guild.id, message.author.id)
        existing = self._blackjack_sessions.get(session_key)
        if existing and not existing.resolved:
            await message.reply("You already have an active blackjack hand. Finish that one first.")
            return "Blackjack already active"
        reserve_result = await self._run_db(
            self._reserve_blackjack_bet_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
            amount,
        )
        if reserve_result["status"] == "insufficient":
            await message.reply(
                f"You do not have enough coins for that blackjack bet.\n"
                f"Wallet: {_format_coin_reward(int(reserve_result['wallet']))}"
            )
            return "Blackjack insufficient"
        if reserve_result["status"] != "success":
            await message.reply("That blackjack hand could not be started right now.")
            return "Blackjack failed"

        deck = self._create_blackjack_deck()
        player_hand: list[tuple[str, str]] = []
        dealer_hand: list[tuple[str, str]] = []
        self._blackjack_draw(player_hand, deck)
        self._blackjack_draw(dealer_hand, deck)
        self._blackjack_draw(player_hand, deck)
        self._blackjack_draw(dealer_hand, deck)
        session = BlackjackSession(
            guild_id=message.guild.id,
            user_id=message.author.id,
            display_name=_display_name(message.author),
            bet=amount,
            original_bet=amount,
            player_hand=player_hand,
            dealer_hand=dealer_hand,
            deck=deck,
        )
        self._blackjack_sessions[session_key] = session

        player_total = self._blackjack_hand_value(player_hand)
        dealer_total = self._blackjack_hand_value(dealer_hand)
        if player_total == 21 or dealer_total == 21:
            if player_total == 21 and dealer_total == 21:
                await self._finish_blackjack_session(session, outcome="push", note="Both hands opened with blackjack. The bet is returned.")
            elif player_total == 21:
                await self._finish_blackjack_session(session, outcome="blackjack", note="Natural blackjack. Premium payout secured.")
            else:
                await self._finish_blackjack_session(session, outcome="loss", note="Dealer opened with blackjack before the hand could begin.")
            await message.reply(embed=self._build_blackjack_embed(session, note=session.result_note, reveal_dealer=True))
            return "Blackjack instant result"

        view = BlackjackView(cog=self, session=session, author_id=message.author.id)
        embed = self._build_blackjack_embed(session)
        sent = await message.reply(embed=embed, view=view)
        view.bind_message(sent)
        return "Blackjack started"

    async def coinflip_func(self, message: discord.Message, *, target_user: Optional[discord.abc.User], amount: int) -> str:
        if message.guild is None:
            await message.reply("Coinflip is only available inside a server.")
            return "Coinflip unavailable in DMs"
        if target_user is None:
            await message.reply("Use `coinflip @user <amount>`.")
            return "Coinflip target missing"
        if target_user.id == message.author.id:
            await message.reply("You cannot coinflip against yourself.")
            return "Coinflip self blocked"
        if amount <= 0:
            await message.reply("Use `coinflip @user <amount>` with a value greater than zero.")
            return "Coinflip amount invalid"
        challenger_busy = self._active_game_label_for_user(message.guild.id, message.author.id)
        if challenger_busy:
            await message.reply(f"You already have an active **{challenger_busy}** session. Finish that first.")
            return "Coinflip challenger busy"
        target_busy = self._active_game_label_for_user(message.guild.id, target_user.id)
        if target_busy:
            await message.reply(f"{_display_name(target_user)} already has an active **{target_busy}** session.")
            return "Coinflip target busy"
        session = CoinflipSession(
            guild_id=message.guild.id,
            challenger_id=message.author.id,
            challenger_name=_display_name(message.author),
            target_id=target_user.id,
            target_name=_display_name(target_user),
            bet=amount,
        )
        self._coinflip_sessions[(message.guild.id, message.author.id)] = session
        self._coinflip_sessions[(message.guild.id, target_user.id)] = session
        view = CoinflipView(cog=self, session=session)
        sent = await message.reply(embed=self._build_coinflip_embed(session), view=view)
        view.bind_message(sent)
        return "Coinflip challenge started"

    async def guess_func(self, message: discord.Message, *, amount: int) -> str:
        if message.guild is None:
            await message.reply("Guess is only available inside a server.")
            return "Guess unavailable in DMs"
        if amount <= 0:
            await message.reply("Use `guess <amount>` with a value greater than zero.")
            return "Guess amount invalid"
        active_game = self._active_game_label_for_user(message.guild.id, message.author.id)
        if active_game:
            await message.reply(f"You already have an active **{active_game}** session. Finish that first.")
            return "Guess user busy"
        reserve_result = await self._run_db(
            self._reserve_blackjack_bet_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
            amount,
        )
        if reserve_result["status"] == "insufficient":
            await message.reply(
                f"You do not have enough coins for that guess game.\n"
                f"Wallet: {_format_coin_reward(int(reserve_result['wallet']))}"
            )
            return "Guess insufficient"
        if reserve_result["status"] != "success":
            await message.reply("That guess game could not be started right now.")
            return "Guess failed"
        session = GuessSession(
            guild_id=message.guild.id,
            user_id=message.author.id,
            display_name=_display_name(message.author),
            bet=amount,
            target_number=random.randint(1, 100),
            tries_left=5,
            max_tries=5,
        )
        self._guess_sessions[(message.guild.id, message.author.id)] = session
        sent = await message.reply(embed=self._build_guess_embed(session))
        session.message = sent
        def check(response: discord.Message) -> bool:
            return (
                response.guild is not None
                and response.guild.id == message.guild.id
                and response.channel.id == message.channel.id
                and response.author.id == message.author.id
            )
        try:
            while session.tries_left > 0 and not session.resolved:
                try:
                    response = await self.bot.wait_for("message", timeout=120.0, check=check)
                except asyncio.TimeoutError:
                    session.resolved = True
                    session.result_note = "Time ran out before you finished the guess game."
                    break
                raw_guess = response.content.strip()
                if not re.fullmatch(r"\d{1,3}", raw_guess):
                    session.result_note = "Only whole numbers between 1 and 100 count for this game."
                    if session.message is not None:
                        with contextlib.suppress(discord.HTTPException):
                            await session.message.edit(embed=self._build_guess_embed(session))
                    continue
                guess_value = int(raw_guess)
                if guess_value < 1 or guess_value > 100:
                    session.result_note = "Stay inside the 1 to 100 range."
                    if session.message is not None:
                        with contextlib.suppress(discord.HTTPException):
                            await session.message.edit(embed=self._build_guess_embed(session))
                    continue
                session.guesses.append(guess_value)
                session.tries_left -= 1
                if guess_value == session.target_number:
                    payout = amount * 2
                    payout_result = await self._run_db(
                        self._settle_blackjack_payout_sync,
                        message.guild.id,
                        message.author.id,
                        _display_name(message.author),
                        payout,
                    )
                    session.resolved = True
                    session.payout_amount = payout if payout_result.get("status") == "success" else 0
                    session.wallet_after = payout_result.get("wallet") if payout_result.get("status") == "success" else None
                    session.result_note = f"You guessed **{guess_value}** correctly and cracked the number."
                    if session.wallet_after is not None:
                        session.result_note += f"\nWallet: {_format_coin_reward(int(session.wallet_after))}"
                    break
                if guess_value < session.target_number:
                    session.low_bound = max(session.low_bound, guess_value + 1)
                    hint = "Too low."
                else:
                    session.high_bound = min(session.high_bound, guess_value - 1)
                    hint = "Too high."
                if session.tries_left <= 0:
                    session.resolved = True
                    session.result_note = (
                        f"{hint} You ran out of tries. The number was **{session.target_number}**."
                    )
                else:
                    session.result_note = f"{hint} Narrow it down and try again."
                if session.message is not None:
                    with contextlib.suppress(discord.HTTPException):
                        await session.message.edit(embed=self._build_guess_embed(session))
            if session.message is not None:
                with contextlib.suppress(discord.HTTPException):
                    await session.message.edit(embed=self._build_guess_embed(session))
            return "Guess complete" if session.resolved else "Guess running"
        finally:
            self._guess_sessions.pop((message.guild.id, message.author.id), None)

    async def drawgame_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Drawgame is only available inside a server.")
            return "Drawgame unavailable in DMs"
        channel_key = self._channel_game_key(message.guild.id, message.channel.id)
        active = self._get_active_chat_guessing_session(message.guild.id, message.channel.id)
        if active is not None:
            await message.reply(f"There is already an active **{active[0]}** session in this channel.")
            return "Drawgame already active"
        if channel_key in self._drawgame_loading_channels:
            await message.reply("A drawgame is already loading in this channel.")
            return "Drawgame loading already active"
        self._drawgame_loading_channels.add(channel_key)
        loading_message = await message.reply(embed=self._build_drawgame_loading_embed())
        try:
            entry, initial_image = await asyncio.wait_for(
                asyncio.to_thread(self._prepare_drawgame_startup_sync),
                timeout=QUICKDRAW_STARTUP_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("Quick Draw startup timed out in channel %s.", message.channel.id)
            error_embed = discord.Embed(
                title="Quick Draw Guessing Game",
                description="Could not prepare a valid Quick Draw drawing. Please try again.",
                color=EMBED_COLOR,
            )
            error_embed.add_field(
                name="Status",
                value="The drawing startup took too long, so this round was cancelled cleanly.",
                inline=False,
            )
            with contextlib.suppress(discord.HTTPException):
                await loading_message.edit(embed=error_embed, attachments=[])
            return "Drawgame startup timed out"
        except Exception:
            logger.warning("Failed to start drawgame because no drawable Quick Draw sample was available.", exc_info=True)
            error_embed = discord.Embed(
                title="Quick Draw Guessing Game",
                description="Could not prepare a valid Quick Draw drawing. Please try again.",
                color=EMBED_COLOR,
            )
            error_embed.add_field(
                name="Status",
                value="A drawable sample could not be prepared, so the game did not start.",
                inline=False,
            )
            with contextlib.suppress(discord.HTTPException):
                await loading_message.edit(embed=error_embed, attachments=[])
            return "Drawgame sample unavailable"
        finally:
            self._drawgame_loading_channels.discard(channel_key)
        session = DrawGameSession(
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            host_user_id=message.author.id,
            answer=str(entry["answer"]),
            normalized_answers=set(entry.get("normalized_answers") or {_normalize_guess_text(str(entry["answer"]))}),
            clue=str(entry.get("clue") or "It is a common object, animal, or idea from Quick Draw."),
            drawing=list(entry["drawing"]),
            reward_base=240,
            started_at=time.monotonic(),
        )
        self._drawgame_sessions[channel_key] = session
        file = discord.File(initial_image, filename="drawgame.png")
        try:
            await loading_message.edit(embed=self._build_drawgame_embed(session), attachments=[file])
            logger.info(
                "Quick Draw startup: message updated successfully in channel %s for answer='%s'.",
                message.channel.id,
                entry.get("answer"),
            )
        except discord.HTTPException:
            logger.warning("Quick Draw startup: failed to update loading message in channel %s.", message.channel.id, exc_info=True)
            self._drawgame_sessions.pop(channel_key, None)
            fail_embed = discord.Embed(
                title="Quick Draw Guessing Game",
                description="Could not prepare a valid Quick Draw drawing. Please try again.",
                color=EMBED_COLOR,
            )
            fail_embed.add_field(
                name="Status",
                value="The drawing was prepared, but the game message could not be updated.",
                inline=False,
            )
            with contextlib.suppress(discord.HTTPException):
                await loading_message.edit(embed=fail_embed, attachments=[])
            return "Drawgame message update failed"
        session.message = loading_message
        session.reveal_task = self._track_session_task(asyncio.create_task(self._run_drawgame_reveal_loop(session)))
        session.timeout_task = self._track_session_task(asyncio.create_task(self._timeout_drawgame_session(session)))
        return "Drawgame started"

    async def drawgame_hint_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Hint is only available inside a server.")
            return "Hint unavailable in DMs"
        active = self._get_active_text_game(message.guild.id, message.channel.id)
        if active is None or active[0] != "drawgame":
            await message.reply("There is no active drawgame session in this channel.")
            return "No active drawgame"
        session: DrawGameSession = active[1]
        async with session.lock:
            if session.resolved:
                await message.reply("That drawgame session has already ended.")
                return "Drawgame resolved"
            if session.hint_level >= 3:
                await message.reply("All hints for this drawing have already been used.")
                return "Drawgame hints exhausted"
            session.hint_level += 1
            session.result_note = f"Hint {session.hint_level}: {self._drawgame_hint_text(session)}"
            await self._refresh_drawgame_message(session)
        return "Drawgame hint shown"

    async def enddrawgame_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Drawgame controls are only available inside a server.")
            return "End drawgame unavailable in DMs"
        active = self._get_active_text_game(message.guild.id, message.channel.id)
        if active is None or active[0] != "drawgame":
            await message.reply("There is no active drawgame session in this channel.")
            return "No active drawgame"
        session: DrawGameSession = active[1]
        async with session.lock:
            if session.resolved:
                await message.reply("That drawgame session has already ended.")
                return "Drawgame already ended"
            has_manage_messages = False
            if isinstance(message.author, discord.Member):
                has_manage_messages = message.author.guild_permissions.manage_messages
            if message.author.id != session.host_user_id and not has_manage_messages:
                await message.reply("Only the game starter or a moderator can end this drawgame.")
                return "Drawgame end denied"
            session.resolved = True
            session.result_note = "The drawgame was ended early. The answer has been revealed."
            await self._refresh_drawgame_message(session, reveal_answer=True)
            self._close_drawgame_session(session)
        return "Drawgame ended"

    async def hangman_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Hangman is only available inside a server.")
            return "Hangman unavailable in DMs"
        active = self._get_active_chat_guessing_session(message.guild.id, message.channel.id)
        if active is not None:
            await message.reply(f"There is already an active **{active[0]}** session in this channel.")
            return "Hangman already active"
        answer = random.choice(HANGMAN_WORDS)
        session = HangmanSession(
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            host_user_id=message.author.id,
            answer=answer,
            guessed_letters=set(),
            remaining_attempts=7,
            max_attempts=7,
            reward_base=140,
            started_at=time.monotonic(),
        )
        self._hangman_sessions[self._channel_game_key(message.guild.id, message.channel.id)] = session
        sent = await message.reply(embed=self._build_hangman_embed(session))
        session.message = sent
        session.timeout_task = self._track_session_task(asyncio.create_task(self._timeout_hangman_session(session)))
        return "Hangman started"

    async def wordchain_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Wordchain is only available inside a server.")
            return "Wordchain unavailable in DMs"
        active = self._get_active_chat_guessing_session(message.guild.id, message.channel.id)
        if active is not None:
            await message.reply(f"There is already an active **{active[0]}** session in this channel.")
            return "Wordchain already active"
        start_word = random.choice(WORDCHAIN_WORDS)
        last_letter = next((char.lower() for char in reversed(start_word) if char.isalpha()), start_word[-1].lower())
        session = WordChainSession(
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            host_user_id=message.author.id,
            current_word=start_word,
            required_letter=last_letter,
            used_words={_normalize_guess_text(start_word)},
            history=[("Bot", start_word)],
            started_at=time.monotonic(),
        )
        self._wordchain_sessions[self._channel_game_key(message.guild.id, message.channel.id)] = session
        sent = await message.reply(embed=self._build_wordchain_embed(session))
        session.message = sent
        self._restart_wordchain_timeout(session)
        return "Wordchain started"

    async def trivia_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Trivia is only available inside a server.")
            return "Trivia unavailable in DMs"
        active = self._get_active_chat_guessing_session(message.guild.id, message.channel.id)
        if active is not None:
            await message.reply(f"There is already an active **{active[0]}** session in this channel.")
            return "Trivia already active"
        session = TriviaSession(
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            host_user_id=message.author.id,
            last_activity_at=time.monotonic(),
        )
        self._trivia_sessions[self._channel_game_key(message.guild.id, message.channel.id)] = session
        loading_embed = discord.Embed(
            title="Trivia",
            description="Loading a question...",
            color=EMBED_COLOR,
        )
        loading_embed.set_author(name="Cadis Etrama Di Raizel")
        loading_embed.add_field(
            name="How It Works",
            value="Answer directly in chat. The first correct answer wins coins and XP.",
            inline=False,
        )
        sent = await message.reply(embed=loading_embed)
        session.message = sent
        try:
            await self._start_next_trivia_question(session, intro_note="Trivia started. Answer in chat to win the round.")
        except Exception:
            logger.warning("Failed to start trivia in channel %s", message.channel.id, exc_info=True)
            session.resolved = True
            session.result_note = "Trivia could not start because the question service was unavailable."
            await self._refresh_trivia_message(session, state="ended")
            self._close_trivia_session(session)
            return "Trivia start failed"
        return "Trivia started"

    async def _react_to_game_guess(self, message: discord.Message, *, correct: bool) -> None:
        if message.author.bot:
            return
        emojis = ["🟢"] if correct else ["🔴"]
        if correct:
            emojis.append("🎉")
        me = getattr(message.guild, "me", None) if message.guild is not None else None
        for emoji in emojis:
            already_added = False
            for reaction in message.reactions:
                if str(reaction.emoji) != emoji:
                    continue
                if me is None:
                    already_added = True
                    break
                with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                    users = [user async for user in reaction.users(limit=20)]
                    if any(getattr(user, "id", None) == me.id for user in users):
                        already_added = True
                        break
            if already_added:
                continue
            with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                await message.add_reaction(emoji)

    async def _handle_drawgame_guess(self, message: discord.Message, session: DrawGameSession) -> Optional[bool]:
        guess = _normalize_guess_text(message.content)
        if not guess:
            return None
        if guess in session.normalized_answers:
            async with session.lock:
                if session.resolved:
                    return None
                await self._resolve_drawgame_win(session, message.author)
            return True
        return False

    async def _handle_hangman_guess(self, message: discord.Message, session: HangmanSession) -> Optional[bool]:
        guess = _normalize_guess_text(message.content)
        if not guess:
            return None
        guess_correct = False
        async with session.lock:
            if session.resolved:
                return None
            self._cancel_session_task(session.timeout_task)
            session.timeout_task = self._track_session_task(asyncio.create_task(self._timeout_hangman_session(session)))
            if len(guess) == 1 and guess.isalpha():
                if guess in session.guessed_letters:
                    return None
                session.guessed_letters.add(guess)
                if guess in session.answer.lower():
                    session.result_note = f"Letter **{guess.upper()}** is in the word."
                    guess_correct = True
                else:
                    session.remaining_attempts = max(0, session.remaining_attempts - 1)
                    session.result_note = f"Letter **{guess.upper()}** is not in the word."
            else:
                if guess == _normalize_guess_text(session.answer):
                    session.guessed_letters.update(char.lower() for char in session.answer if char.isalpha())
                    guess_correct = True
                else:
                    session.remaining_attempts = max(0, session.remaining_attempts - 1)
                    session.result_note = f"**{message.content.strip()}** is not the word."
            solved = all((not char.isalpha()) or (char.lower() in session.guessed_letters) for char in session.answer)
            if solved:
                reward = max(60, session.reward_base + session.remaining_attempts * 18)
                payout_result = await self._run_db(
                    self._settle_blackjack_payout_sync,
                    session.guild_id,
                    message.author.id,
                    _display_name(message.author),
                    reward,
                )
                session.resolved = True
                session.winner_id = message.author.id
                session.payout_amount = reward if payout_result.get("status") == "success" else 0
                session.result_note = f"**{_display_name(message.author)}** solved the word and won {_format_coin_reward(session.payout_amount)}."
                if session.message is not None:
                    with contextlib.suppress(discord.HTTPException):
                        await session.message.edit(embed=self._build_hangman_embed(session, reveal_answer=True))
                self._close_hangman_session(session)
                return True
            if session.remaining_attempts <= 0:
                session.resolved = True
                session.result_note = f"No attempts left. The word was **{session.answer.upper()}**."
                if session.message is not None:
                    with contextlib.suppress(discord.HTTPException):
                        await session.message.edit(embed=self._build_hangman_embed(session, reveal_answer=True))
                self._close_hangman_session(session)
                return False
            if session.message is not None:
                with contextlib.suppress(discord.HTTPException):
                    await session.message.edit(embed=self._build_hangman_embed(session))
        return guess_correct

    async def _handle_wordchain_guess(self, message: discord.Message, session: WordChainSession) -> Optional[bool]:
        submitted = _normalize_guess_text(message.content)
        if not submitted or " " in submitted or not submitted.isalpha():
            return None
        async with session.lock:
            if session.resolved:
                return None
            if submitted in RESERVED_TEXT_GAME_WORDS:
                return None
            if submitted in session.used_words:
                session.result_note = f"**{submitted}** was already used in this chain."
                if session.message is not None:
                    with contextlib.suppress(discord.HTTPException):
                        await session.message.edit(embed=self._build_wordchain_embed(session))
                return False
            if not submitted.startswith(session.required_letter):
                session.result_note = f"**{submitted}** does not start with **{session.required_letter.upper()}**."
                if session.message is not None:
                    with contextlib.suppress(discord.HTTPException):
                        await session.message.edit(embed=self._build_wordchain_embed(session))
                return False
            if submitted not in WORDCHAIN_WORD_LOOKUP:
                session.result_note = f"**{submitted}** is not in the current word pool for this chain."
                if session.message is not None:
                    with contextlib.suppress(discord.HTTPException):
                        await session.message.edit(embed=self._build_wordchain_embed(session))
                return False
            session.used_words.add(submitted)
            session.current_word = submitted
            session.required_letter = submitted[-1]
            session.last_contributor_id = message.author.id
            session.last_contributor_name = _display_name(message.author)
            session.history.append((_display_name(message.author), submitted))
            session.result_note = f"**{_display_name(message.author)}** kept the chain alive with **{submitted}**."
            if session.message is not None:
                with contextlib.suppress(discord.HTTPException):
                    await session.message.edit(embed=self._build_wordchain_embed(session))
            self._restart_wordchain_timeout(session)
        return True

    async def _process_active_text_game_message(self, message: discord.Message) -> bool:
        if message.guild is None or message.author.bot:
            return False
        active = self._get_active_text_game(message.guild.id, message.channel.id)
        if active is None:
            return False
        first_token = _normalize_lookup(message.content.split(maxsplit=1)[0]) if message.content.strip() else ""
        if first_token in RESERVED_TEXT_GAME_WORDS:
            return False
        label, session = active
        result: Optional[bool]
        if label == "drawgame":
            result = await self._handle_drawgame_guess(message, session)
        elif label == "hangman":
            result = await self._handle_hangman_guess(message, session)
        elif label == "wordchain":
            result = await self._handle_wordchain_guess(message, session)
        else:
            result = None
        if result is None:
            return False
        await self._react_to_game_guess(message, correct=result)
        return True

    async def _is_developer_user(self, user: discord.abc.User) -> bool:
        with contextlib.suppress(Exception):
            return await self.bot.is_owner(user)
        return False

    async def givemoney_func(self, message: discord.Message, *, target_user: Optional[discord.abc.User], amount: int) -> str:
        if message.guild is None:
            await message.reply("Developer economy commands are only available inside a server.")
            return "Give money unavailable in DMs"
        if not await self._is_developer_user(message.author):
            await message.reply("This command is restricted to the bot owner.")
            return "Give money permission denied"
        if target_user is None:
            await message.reply("Use `givemoney @user <amount>`.")
            return "Give money target missing"
        if amount <= 0:
            await message.reply("Use `givemoney @user <amount>` with a value greater than zero.")
            return "Give money amount invalid"
        result = await self._run_db(
            self._grant_money_sync,
            message.guild.id,
            target_user.id,
            _display_name(target_user),
            amount,
        )
        if result["status"] == "success":
            await message.reply(
                f"You gave **{amount} coins** to **{_display_name(target_user)}**.\n"
                f"Target wallet: **{int(result['wallet'])} coins**"
            )
            return "Give money complete"
        await message.reply("That coin grant could not be completed.")
        return "Give money failed"

    async def gift_func(self, message: discord.Message, *, target_user: Optional[discord.abc.User], amount: int) -> str:
        if message.guild is None:
            await message.reply("Gifting is only available inside a server.")
            return "Gift unavailable in DMs"
        if target_user is None:
            await message.reply("Use `gift @user <amount>`.")
            return "Gift target missing"
        if target_user.id == message.author.id:
            await message.reply("You cannot gift money to yourself.")
            return "Gift self blocked"
        if amount <= 0:
            await message.reply("Gift amount must be greater than zero.")
            return "Gift amount invalid"
        result = await self._run_db(
            self._gift_money_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
            target_user.id,
            _display_name(target_user),
            amount,
        )
        if result["status"] == "insufficient":
            await message.reply(f"You do not have enough coins. Current wallet: **{result['wallet']}**.")
            return "Gift insufficient funds"
        if result["status"] == "success":
            await message.reply(f"You gifted **{amount} coins** to **{_display_name(target_user)}**.\nYour wallet: **{result['sender_wallet']} coins**")
            return "Gift complete"
        await message.reply("That gift could not be completed.")
        return "Gift failed"

    def cog_unload(self) -> None:
        for task in list(self._reminder_tasks):
            task.cancel()
        self._reminder_tasks.clear()
        for task in list(self._session_tasks):
            task.cancel()
        self._session_tasks.clear()
        if self._http_session is not None and not self._http_session.closed:
            with contextlib.suppress(RuntimeError):
                asyncio.create_task(self._http_session.close())

    def _split_help_chunks(self, value: str, *, limit: int = 1000) -> list[str]:
        lines = [line for line in (value or "").splitlines() if line.strip()]
        if not lines:
            return ["No commands recorded yet."]
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for line in lines:
            addition = len(line) + (1 if current else 0)
            if current and current_len + addition > limit:
                chunks.append("\n".join(current))
                current = [line]
                current_len = len(line)
            else:
                current.append(line)
                current_len += addition
        if current:
            chunks.append("\n".join(current))
        return chunks

    def _available_help_categories(self) -> list[tuple[str, str]]:
        return [
            ("playback", "🎵 Playback"),
            ("filters", "🎚 Filters"),
            ("history", "📜 History"),
            ("minigame", "🎮 Minigame"),
            ("utility", "⚙ Utility"),
            ("stats", "📊 Stats"),
            ("marriage", "💍 Marriage"),
            ("profile_xp", "👤 Profile / XP"),
            ("avatar_tools", "🖼 Avatar Tools"),
            ("text_tools", "🧠 Text Tools"),
            ("moderation", "🛠 Moderation"),
        ]

    def _help_page_sections(self, category: str) -> list[tuple[str, str]]:
        pages: dict[str, list[tuple[str, str]]] = {
            "playback": [
                ("Core Commands", "`play <song>` `pause` `resume` `skip` `stop`\n`queue` `shuffle` `clearqueue`"),
                ("Advanced Commands", "`seek 1:20` `forward 10` `back 10`\n`nowplaying` `np`\n`play <playlist url>` `playlist <url>`"),
                ("Examples", "`play Breaking Benjamin`\n`forward 15`\n`playlist <url>`"),
            ],
            "filters": [
                ("Core Commands", "`nightcore` `bassboost` `slow` `reverb` `echo`\n`speed 1.15` `pitch 0.9`\n`lowpass 300` `highpass 200`"),
                ("Advanced Commands", "`equalizer 100 3` `show filters`\n`nightcore off` `reverb off`\n`filter off` `reset filters`"),
                ("Examples", "`nightcore`\n`speed 1.25`\n`lowpass 300`\n`bassboost off`"),
            ],
            "history": [
                ("Core Commands", "`history @user` `history me`\n`mostplayed @user` `mostplayed me`\n`songs @user` `favorites @user`"),
                ("Notes", "History is per guild and per user.\nPage numbers work in both history and mostplayed views."),
                ("Examples", "`history @Raizel`\n`mostplayed me`\n`history me page 2`"),
            ],
            "minigame": [
                ("Economy", "`balance` `bal` `wallet`\n`daily` `quests` `missions`\n`achievements` `badges`\n`income` `collect` `property`\n`gift @user <amount>` `richest` `topmoney`"),
                ("Jobs", "`jobs` `choosejob <name>` `job choose <name>`\n`myjob` `job upgrade` `level job`\n`work` `beg` `quiz` `answer <number>`\n`fish` `hunt` `search` `mine`\n`deliver` `scavenge` `freelance`\n`craft` `repair` `patrol`\n`earn` `quickearn` `workpanel`"),
                ("Casino", "`gamble <amount>` `bet <amount>`\n`blackjack <amount>` `bj <amount>`\n`bj @user <amount>`\n`coinflip @user <amount>` `cf @user <amount>`\n`slots <amount>` `slot <amount>` `spin <amount>`\n`crash <amount>`\n`guess <amount>`"),
                ("PvP / Dungeon", "`duel @user <amount>`\n`dungeon <amount>` `dungeon run <amount>` `pve <amount>`\n`steal @user` `rob @user` `heist @user`"),
                ("Extras", "`shop` `market` `shopview`\n`inventory` `buy <item>` `use <item>`\nPets now live inside the main market.\n`mypet` `equippet <name>` `feedpet` `petinfo`"),
                ("Notes", "Only one live game session is allowed per user.\nBlackjack, coinflip, crash, duel, guess, and dungeon all lock cleanly and settle through SQLite-safe wallet updates."),
            ],
            "utility": [
                ("Core Commands", "`ping` `uptime`\n`calc <expression>`\n`timer <time>`\n`remind <time> <text>`"),
                ("Advanced Commands", "`notes add <text>`\n`notes list`\n`notes delete <id>`"),
                ("Examples", "`calc (5 + 3) * 2`\n`timer 10m`\n`remind 45m stretch and drink water`\n`notes add buy coffee beans`"),
            ],
            "stats": [
                ("Core Commands", "`mystats` `dungeonstats` `casinostats`\n`jobstats` `winrate` `lossrate`\n`mostused` `playtime`"),
                ("Leaderboards", "`topmoney` `topxp`\n`topdungeon` `topgamblers`\n`topwins` `toplosses`"),
                ("Examples", "`mystats`\n`casinostats`\n`topdungeon`"),
            ],
            "marriage": [
                ("Core Commands", "`marry @user` `propose @user`\n`accept` `decline` `divorce`"),
                ("Advanced Commands", "`spouse` `marriage` `marriageprofile`\n`love`"),
                ("Notes", "Marriage is persistent per server.\nOnly one spouse at a time.\nProposals require the target user to confirm with `accept`."),
                ("Examples", "`propose @user`\n`accept`\n`marriageprofile`"),
            ],
            "profile_xp": [
                ("Core Commands", "`profile` `profile @user`\n`rank` `xp` `level`\n`leaderboard` `topxp`"),
                ("Examples", "`profile`\n`rank @user`\n`leaderboard`"),
            ],
            "avatar_tools": [
                ("Core Commands", "`avatar` `avatar @user`\n`pfp` `pp`\n`banner`\n`userinfo`"),
                ("Examples", "`avatar @user`\n`banner`\n`userinfo @user`"),
            ],
            "text_tools": [
                ("Core Commands", "`translate <text>` `tr <text>`\n`rewrite <text>` `rewrite formal <text>`\n`rewrite simple <text>` `rewrite verysimple <text>`\n`explain <text>` `explain verysimple <text>`"),
                ("Advanced Commands", "`summarize <text>` `keywords <text>`\n`fix <text>` `shorten <text>` `expand <text>`\n`tone casual <text>` `tone formal <text>`"),
                ("Examples", "`summarize long text here`\n`keywords this message about dungeon rewards`\n`tone formal can you send the file today`"),
            ],
            "moderation": [
                ("Core Commands", "`purge <amount>`"),
                ("Examples", "`purge 5`\n`purge 20`"),
            ],
        }
        return pages.get(category, [])

    def build_help_embed(self, category: Optional[str] = None) -> discord.Embed:
        title = "Cadis Etrama Di Raizel"
        category_titles = {
            "playback": "Playback",
            "filters": "Filters",
            "history": "History",
            "minigame": "Minigame",
            "utility": "Utility / QoL",
            "stats": "Stats / Analytics",
            "marriage": "Marriage",
            "profile_xp": "Profile / XP",
            "avatar_tools": "Avatar Tools",
            "text_tools": "Text Tools",
            "moderation": "Moderation",
        }
        descriptions = {
            "playback": "Core music playback, queue, seek, and playlist commands.",
            "filters": "Real FFmpeg-based audio effects with per-filter off support.",
            "history": "See per-user song history and most-played tracks.",
            "minigame": "English-only economy, gambling, dungeon, shop, and pet systems.",
            "utility": "Practical reminder, notes, timer, calculator, and status tools.",
            "stats": "Personal analytics, win/loss tracking, and expanded leaderboards.",
            "marriage": "Persistent proposal, spouse, and relationship profile commands.",
            "profile_xp": "Local server XP, rank, and profile tracking.",
            "avatar_tools": "Avatar, banner, and user information tools.",
            "text_tools": "Local deterministic text utilities without external AI.",
            "moderation": "Quick moderation utility commands.",
        }
        if category is None:
            embed = discord.Embed(
                title=title,
                description=(
                    "An advanced interactive command system.\n"
                    "Use the buttons below to move between polished category pages."
                ),
                color=EMBED_COLOR,
            )
            embed.set_author(name="Interactive Help Menu")
            first_column = ["🎵 Playback", "🎚 Filters", "📜 History", "🎮 Minigame", "⚙ Utility", "📊 Stats"]
            second_column = ["💍 Marriage", "👤 Profile / XP", "🖼 Avatar Tools", "🧠 Text Tools", "🛠 Moderation", "🧩 Smart Help"]
            embed.add_field(name="Categories", value="\n".join(first_column), inline=True)
            embed.add_field(name="Categories 2", value="\n".join(second_column), inline=True)
            embed.add_field(
                name="Quick Access",
                value="`help dungeon`\n`help slots`\n`help crash`\n`help marriage`",
                inline=False,
            )
            embed.add_field(
                name="Tips",
                value="Use the buttons below for categories.\nUse `help <topic>` for focused pages like `help duel` or `help stats`.",
                inline=False,
            )
            embed.set_footer(text="Interactive help menu")
            return embed

        embed = discord.Embed(
            title=title,
            description=descriptions.get(category, "Command reference."),
            color=EMBED_COLOR,
        )
        embed.set_author(name=category_titles.get(category, "Help"))
        for field_name, field_value in self._help_page_sections(category):
            chunks = self._split_help_chunks(field_value)
            for index, chunk in enumerate(chunks, start=1):
                label = field_name if index == 1 else f"{field_name} {index}"
                embed.add_field(name=label, value=chunk[:1024], inline=False)
        embed.add_field(
            name="Notes",
            value="Use `help <topic>` for a focused page when you want syntax, examples, and mechanics for one system.",
            inline=False,
        )
        embed.set_footer(text=f"Category: {category_titles.get(category, 'Help')}")
        return embed

    def _resolve_help_topic(self, topic: Optional[str]) -> Optional[str]:
        normalized = _normalize_lookup(topic or "")
        if not normalized:
            return None
        aliases = {
            "dungeon": "dungeon",
            "ancient dungeon": "dungeon",
            "slots": "slots",
            "slot": "slots",
            "job": "job",
            "jobs": "job",
            "crash": "crash",
            "marriage": "marriage",
            "shop": "shop",
            "shopview": "shop",
            "market": "shop",
            "duel": "duel",
            "profile": "profile",
            "stats": "stats",
        }
        return aliases.get(normalized)

    def _build_topic_help_embed(self, topic_key: str) -> discord.Embed:
        topics: dict[str, dict[str, str]] = {
            "dungeon": {
                "title": "Dungeon Help",
                "summary": "A risk-based dungeon climb with lives, companions, Ancient Dungeon continuation, and leave cashout.",
                "syntax": "`dungeon <amount>`\n`dungeon run <amount>`\n`pve <amount>`",
                "examples": "`dungeon 500`\n`pve 1200`",
                "notes": "Attack pushes the run forward. Leave returns your original bet plus cleared-floor rewards. Level 10 pays first, then can unlock the Ancient Dungeon choice.",
            },
            "slots": {
                "title": "Slots Help",
                "summary": "Animated emoji reels with multiple win tiers, including jackpot results.",
                "syntax": "`slots <amount>`\n`slot <amount>`\n`spin <amount>`",
                "examples": "`slots 500`\n`spin 250`",
                "notes": "One live message spins the reels and resolves the wallet safely in SQLite.",
            },
            "job": {
                "title": "Job Help",
                "summary": "Choose a profession, level it up, and use earning actions tied to your economy profile.",
                "syntax": "`jobs`\n`choosejob <name>`\n`job choose <name>`\n`myjob`\n`job upgrade`",
                "examples": "`choosejob blacksmith`\n`myjob`\n`job upgrade`",
                "notes": "Profession level improves work-style rewards and is stored persistently.",
            },
            "crash": {
                "title": "Crash Help",
                "summary": "A live multiplier game with a Cash Out button and one continuously updated message.",
                "syntax": "`crash <amount>`",
                "examples": "`crash 800`",
                "notes": "Cash out before the run breaks. The same message updates live to keep the UI clean.",
            },
            "marriage": {
                "title": "Marriage Help",
                "summary": "A persistent social system with proposals, spouse status, and relationship profiles.",
                "syntax": "`propose @user`\n`marry @user`\n`accept`\n`decline`\n`divorce`",
                "examples": "`propose @Raizel`\n`accept`\n`marriageprofile`",
                "notes": "Only one spouse per server. Proposals do not auto-complete; the target user must confirm.",
            },
            "shop": {
                "title": "Shop Help",
                "summary": "Economy market browsing with visible item effects, shopview UI, and pets inside the main market.",
                "syntax": "`shop`\n`market`\n`shopview`\n`buy <item>`\n`inventory`\n`use <item>`",
                "examples": "`shopview`\n`buy coffee machine`\n`use phone @user`",
                "notes": "Item effects are visible in shop pages and inventory. Pets are bought from the market's Pets category.",
            },
            "duel": {
                "title": "Duel Help",
                "summary": "A live best-of-three Rock / Paper / Scissors match with a locked wager for both players.",
                "syntax": "`duel @user <amount>`",
                "examples": "`duel @user 500`",
                "notes": "Only the two duel participants can interact. The winner takes the full pot.",
            },
            "profile": {
                "title": "Profile Help",
                "summary": "XP, level, server rank, profession snapshot, prestige, and relationship details in one profile card.",
                "syntax": "`profile`\n`profile @user`\n`rank`\n`xp`\n`level`",
                "examples": "`profile`\n`rank @user`",
                "notes": "Profile uses local XP data plus economy data to build a combined overview.",
            },
            "stats": {
                "title": "Stats Help",
                "summary": "Analytics for economy progress, casino results, dungeon performance, and action usage.",
                "syntax": "`mystats`\n`dungeonstats`\n`casinostats`\n`jobstats`\n`winrate`\n`lossrate`\n`mostused`\n`playtime`",
                "examples": "`mystats`\n`topdungeon`\n`topwins`",
                "notes": "Stats use local SQLite tracking and avoid external services.",
            },
        }
        topic = topics[topic_key]
        embed = discord.Embed(
            title="Cadis Etrama Di Raizel",
            description=topic["summary"],
            color=EMBED_COLOR,
        )
        embed.set_author(name=topic["title"])
        embed.add_field(name="Syntax", value=topic["syntax"], inline=False)
        embed.add_field(name="Examples", value=topic["examples"], inline=False)
        embed.add_field(name="Tips", value=topic["notes"], inline=False)
        embed.set_footer(text=f"Help Topic: {topic['title']}")
        return embed

    async def help_func(self, message: discord.Message, *, topic: Optional[str] = None) -> str:
        resolved_topic = self._resolve_help_topic(topic)
        if topic and resolved_topic is None:
            embed = discord.Embed(
                title="Cadis Etrama Di Raizel",
                description="I do not have a focused help page for that topic yet.",
                color=EMBED_COLOR,
            )
            embed.add_field(
                name="Available Topics",
                value="`dungeon` `slots` `job` `crash` `marriage` `shop` `duel` `profile` `stats`",
                inline=False,
            )
            await message.reply(embed=embed)
            return "Unknown help topic"
        if resolved_topic is not None:
            await message.reply(embed=self._build_topic_help_embed(resolved_topic))
            return f"Help topic shown for {resolved_topic}"
        categories = self._available_help_categories()
        view = HelpMenuView(cog=self, author_id=message.author.id, categories=categories)
        embed = self.build_help_embed()
        sent = await message.reply(embed=embed, view=view)
        view.bind_message(sent)
        return "Interactive help shown"

    def _available_help_categories(self) -> list[tuple[str, str]]:
        return [
            ("playback", "🎵 Playback"),
            ("filters", "🎚 Filters"),
            ("history", "📜 History"),
            ("minigame", "🎮 Minigame"),
            ("utility", "⚙ Utility"),
            ("stats", "📊 Stats"),
            ("marriage", "💍 Marriage"),
            ("profile_xp", "👤 Profile / XP"),
            ("avatar_tools", "🖼 Avatar Tools"),
            ("text_tools", "🧠 Text Tools"),
            ("moderation", "🛠 Moderation"),
        ]

    def _help_page_sections(self, category: str) -> list[tuple[str, str]]:
        pages: dict[str, list[tuple[str, str]]] = {
            "playback": [
                ("Core Commands", "`play <song>` `pause` `resume` `skip` `stop`\n`queue` `shuffle` `clearqueue`"),
                ("Advanced Commands", "`seek 1:20` `forward 10` `back 10`\n`nowplaying` `np`\n`play <playlist url>` `playlist <url>`"),
                ("Examples", "`play Breaking Benjamin`\n`forward 15`\n`playlist <url>`"),
            ],
            "filters": [
                ("Core Commands", "`nightcore` `bassboost` `slow` `reverb` `echo`\n`speed 1.15` `pitch 0.9`\n`lowpass 300` `highpass 200`"),
                ("Advanced Commands", "`equalizer 100 3` `show filters`\n`nightcore off` `reverb off`\n`filter off` `reset filters`"),
                ("Examples", "`nightcore`\n`speed 1.25`\n`lowpass 300`\n`bassboost off`"),
            ],
            "history": [
                ("Core Commands", "`history @user` `history me`\n`mostplayed @user` `mostplayed me`\n`songs @user` `favorites @user`"),
                ("Notes", "History is per guild and per user.\nPage numbers work in both history and mostplayed views."),
                ("Examples", "`history @Raizel`\n`mostplayed me`\n`history me page 2`"),
            ],
            "minigame": [
                ("Economy", "`balance` `bal` `wallet`\n`daily` `quests` `missions`\n`achievements` `badges`\n`income` `collect` `property`\n`gift @user <amount>` `richest` `topmoney`"),
                ("Jobs", "`jobs` `choosejob <name>` `job choose <name>`\n`myjob` `job upgrade` `level job`\n`work` `beg` `quiz` `answer <number>`\n`fish` `hunt` `search` `mine`\n`deliver` `scavenge` `freelance`\n`craft` `repair` `patrol`\n`earn` `quickearn` `workpanel`"),
                ("Casino", "`gamble <amount>` `bet <amount>`\n`blackjack <amount>` `bj <amount>`\n`bj @user <amount>`\n`coinflip @user <amount>` `cf @user <amount>`\n`slots <amount>` `slot <amount>` `spin <amount>`\n`crash <amount>`\n`guess <amount>`"),
                ("PvP / Dungeon", "`duel @user <amount>`\n`dungeon <amount>` `dungeon run <amount>` `pve <amount>`\n`steal @user` `rob @user` `heist @user`"),
                ("Guessing Games", "`drawgame` `hint`\n`hangman`\n`wordchain` `chainword`\n`trivia`\n`reveal` `enddrawgame`"),
                ("Extras", "`shop` `market` `shopview`\n`inventory` `buy <item>` `sell <item>` `sellall` `use <item>`\nPets now live inside the main market.\n`mypet` `equippet <name>` `feedpet` `petinfo`"),
                ("Notes", "Drawgame, hangman, wordchain, and trivia are channel-scoped guessing games.\nOnly one of them can run in a channel at a time, so normal guesses never collide."),
            ],
            "utility": [
                ("Core Commands", "`ping` `uptime`\n`calc <expression>`\n`timer <time>`\n`remind <time> <text>`"),
                ("Advanced Commands", "`notes add <text>`\n`notes list`\n`notes delete <id>`"),
                ("Examples", "`calc (5 + 3) * 2`\n`timer 10m`\n`remind 45m stretch and drink water`\n`notes add buy coffee beans`"),
            ],
            "stats": [
                ("Core Commands", "`mystats` `dungeonstats` `casinostats`\n`jobstats` `winrate` `lossrate`\n`mostused` `playtime`"),
                ("Leaderboards", "`topmoney` `topxp`\n`topdungeon` `topgamblers`\n`topwins` `toplosses`"),
                ("Examples", "`mystats`\n`casinostats`\n`topdungeon`"),
            ],
            "marriage": [
                ("Core Commands", "`marry @user` `propose @user`\n`accept` `decline` `divorce`"),
                ("Advanced Commands", "`spouse` `marriage` `marriageprofile`\n`love`"),
                ("Notes", "Marriage is persistent per server.\nOnly one spouse at a time.\nProposals require the target user to confirm with `accept`."),
                ("Examples", "`propose @user`\n`accept`\n`marriageprofile`"),
            ],
            "profile_xp": [
                ("Core Commands", "`profile` `profile @user`\n`rank` `xp` `level`\n`leaderboard` `topxp`"),
                ("Examples", "`profile`\n`rank @user`\n`leaderboard`"),
            ],
            "avatar_tools": [
                ("Core Commands", "`avatar` `avatar @user`\n`pfp` `pp`\n`banner`\n`userinfo`"),
                ("Examples", "`avatar @user`\n`banner`\n`userinfo @user`"),
            ],
            "text_tools": [
                ("Core Commands", "`translate <text>` `tr <text>`\n`rewrite <text>` `rewrite formal <text>`\n`rewrite simple <text>` `rewrite verysimple <text>`\n`explain <text>` `explain verysimple <text>`"),
                ("Advanced Commands", "`summarize <text>` `keywords <text>`\n`fix <text>` `shorten <text>` `expand <text>`\n`tone casual <text>` `tone formal <text>`"),
                ("Examples", "`summarize long text here`\n`keywords this message about dungeon rewards`\n`tone formal can you send the file today`"),
            ],
            "moderation": [
                ("Core Commands", "`purge <amount>`"),
                ("Examples", "`purge 5`\n`purge 20`"),
            ],
        }
        return pages.get(category, [])

    def build_help_embed(self, category: Optional[str] = None) -> discord.Embed:
        title = "Cadis Etrama Di Raizel"
        category_titles = {
            "playback": "Playback",
            "filters": "Filters",
            "history": "History",
            "minigame": "Minigame",
            "utility": "Utility / QoL",
            "stats": "Stats / Analytics",
            "marriage": "Marriage",
            "profile_xp": "Profile / XP",
            "avatar_tools": "Avatar Tools",
            "text_tools": "Text Tools",
            "moderation": "Moderation",
        }
        descriptions = {
            "playback": "Core music playback, queue, seek, and playlist commands.",
            "filters": "Real FFmpeg-based audio effects with per-filter off support.",
            "history": "See per-user song history and most-played tracks.",
            "minigame": "English-only economy, PvP tables, guessing games, dungeon, shop, and pet systems.",
            "utility": "Practical reminder, notes, timer, calculator, and status tools.",
            "stats": "Personal analytics, win/loss tracking, and expanded leaderboards.",
            "marriage": "Persistent proposal, spouse, and relationship profile commands.",
            "profile_xp": "Local server XP, rank, and profile tracking.",
            "avatar_tools": "Avatar, banner, and user information tools.",
            "text_tools": "Local deterministic text utilities without external AI.",
            "moderation": "Quick moderation utility commands.",
        }
        if category is None:
            embed = discord.Embed(
                title=title,
                description="An advanced interactive command system.\nUse the buttons below to move between clean category pages.",
                color=EMBED_COLOR,
            )
            embed.set_author(name="Interactive Help Menu")
            embed.add_field(name="Categories", value="\n".join(["🎵 Playback", "🎚 Filters", "📜 History", "🎮 Minigame", "⚙ Utility", "📊 Stats"]), inline=True)
            embed.add_field(name="Categories 2", value="\n".join(["💍 Marriage", "👤 Profile / XP", "🖼 Avatar Tools", "🧠 Text Tools", "🛠 Moderation", "🧩 Smart Help"]), inline=True)
            embed.add_field(name="Quick Access", value="`help dungeon`\n`help slots`\n`help drawgame`\n`help marriage`", inline=False)
            embed.add_field(name="Tips", value="Use the buttons below for categories.\nUse `help <topic>` for focused system pages.", inline=False)
            embed.set_footer(text="Interactive help menu")
            return embed

        embed = discord.Embed(title=title, description=descriptions.get(category, "Command reference."), color=EMBED_COLOR)
        embed.set_author(name=category_titles.get(category, "Help"))
        for field_name, field_value in self._help_page_sections(category):
            for index, chunk in enumerate(self._split_help_chunks(field_value), start=1):
                embed.add_field(name=field_name if index == 1 else f"{field_name} {index}", value=chunk[:1024], inline=False)
        embed.add_field(name="Notes", value="Use `help <topic>` when you want syntax, examples, and mechanics for one system.", inline=False)
        embed.set_footer(text=f"Category: {category_titles.get(category, 'Help')}")
        return embed

    def _resolve_help_topic(self, topic: Optional[str]) -> Optional[str]:
        normalized = _normalize_lookup(topic or "")
        if not normalized:
            return None
        aliases = {
            "dungeon": "dungeon",
            "ancient dungeon": "dungeon",
            "slots": "slots",
            "slot": "slots",
            "drawgame": "drawgame",
            "hangman": "hangman",
            "wordchain": "wordchain",
            "chainword": "wordchain",
            "trivia": "trivia",
            "job": "job",
            "jobs": "job",
            "crash": "crash",
            "marriage": "marriage",
            "shop": "shop",
            "shopview": "shop",
            "market": "shop",
            "duel": "duel",
            "profile": "profile",
            "stats": "stats",
        }
        return aliases.get(normalized)

    def _build_topic_help_embed(self, topic_key: str) -> discord.Embed:
        topics: dict[str, dict[str, str]] = {
            "dungeon": {
                "title": "Dungeon Help",
                "summary": "A risk-based dungeon climb with lives, companions, Ancient Dungeon continuation, and leave cashout.",
                "syntax": "`dungeon <amount>`\n`dungeon run <amount>`\n`pve <amount>`",
                "examples": "`dungeon 500`\n`pve 1200`",
                "notes": "Attack pushes the run forward. Leave returns your original bet plus cleared-floor rewards. Level 10 pays first, then can unlock the Ancient Dungeon choice.",
            },
            "slots": {
                "title": "Slots Help",
                "summary": "Animated emoji reels with multiple win tiers, including jackpot results.",
                "syntax": "`slots <amount>`\n`slot <amount>`\n`spin <amount>`",
                "examples": "`slots 500`\n`spin 250`",
                "notes": "One live message spins the reels and resolves the wallet safely in SQLite.",
            },
            "drawgame": {
                "title": "Drawgame Help",
                "summary": "A Quick Draw-style guessing game with progressive PNG reveals rendered through Pillow.",
                "syntax": "`drawgame`\n`hint`\n`reveal`\n`enddrawgame`",
                "examples": "`drawgame`\n`hint`",
                "notes": "Normal chat messages become guesses only while a drawgame session is active in that channel.",
            },
            "hangman": {
                "title": "Hangman Help",
                "summary": "Guess letters or the full word in normal chat before the attempt counter runs out.",
                "syntax": "`hangman`",
                "examples": "`hangman`",
                "notes": "The bot updates one embed with the masked word, guessed letters, remaining attempts, and reward preview.",
            },
            "wordchain": {
                "title": "Word Chain Help",
                "summary": "Keep a word chain alive by sending valid words that start with the required last letter.",
                "syntax": "`wordchain`\n`chainword`",
                "examples": "`wordchain`",
                "notes": "The most recent valid contributor gets paid if the chain times out without a follow-up.",
            },
            "trivia": {
                "title": "Trivia Help",
                "summary": "Start a question-based guessing game fed by Open Trivia DB.",
                "syntax": "`trivia`\n`trivia start`",
                "examples": "`trivia`\nAnswer in chat: `paris` or `b`",
                "notes": "The bot asks a multiple-choice question, users answer directly in chat, and the first correct answer wins coins and XP. Questions refresh in 5-question batches automatically.",
            },
            "job": {
                "title": "Job Help",
                "summary": "Choose a profession, level it up, and use earning actions tied to your economy profile.",
                "syntax": "`jobs`\n`choosejob <name>`\n`job choose <name>`\n`myjob`\n`job upgrade`",
                "examples": "`choosejob blacksmith`\n`myjob`\n`job upgrade`",
                "notes": "Profession level improves work-style rewards and is stored persistently.",
            },
            "crash": {
                "title": "Crash Help",
                "summary": "A live multiplier game with a Cash Out button and one continuously updated message.",
                "syntax": "`crash <amount>`",
                "examples": "`crash 800`",
                "notes": "Cash out before the run breaks. The same message updates live to keep the UI clean.",
            },
            "marriage": {
                "title": "Marriage Help",
                "summary": "A persistent social system with proposals, spouse status, and relationship profiles.",
                "syntax": "`propose @user`\n`marry @user`\n`accept`\n`decline`\n`divorce`",
                "examples": "`propose @Raizel`\n`accept`\n`marriageprofile`",
                "notes": "Only one spouse per server. Proposals do not auto-complete; the target user must confirm.",
            },
            "shop": {
                "title": "Shop Help",
                "summary": "Economy market browsing with visible item effects, shopview UI, and pets inside the main market.",
                "syntax": "`shop`\n`market`\n`shopview`\n`buy <item>`\n`sell <item>` `sellall`\n`inventory`\n`use <item>`",
                "examples": "`shopview`\n`buy coffee machine`\n`sell golden throne`\n`use phone @user`",
                "notes": "Item effects are visible in shop pages and inventory. Pets are bought from the market's Pets category. Selling returns 70% of original value.",
            },
            "duel": {
                "title": "Duel Help",
                "summary": "A live best-of-three Rock / Paper / Scissors match with a locked wager for both players.",
                "syntax": "`duel @user <amount>`",
                "examples": "`duel @user 500`",
                "notes": "Only the two duel participants can interact. The winner takes the full pot.",
            },
            "profile": {
                "title": "Profile Help",
                "summary": "XP, level, server rank, profession snapshot, prestige, and relationship details in one profile card.",
                "syntax": "`profile`\n`profile @user`\n`rank`\n`xp`\n`level`",
                "examples": "`profile`\n`rank @user`",
                "notes": "Profile uses local XP data plus economy data to build a combined overview.",
            },
            "stats": {
                "title": "Stats Help",
                "summary": "Analytics for economy progress, casino results, dungeon performance, and action usage.",
                "syntax": "`mystats`\n`dungeonstats`\n`casinostats`\n`jobstats`\n`winrate`\n`lossrate`\n`mostused`\n`playtime`",
                "examples": "`mystats`\n`topdungeon`\n`topwins`",
                "notes": "Stats use local SQLite tracking and avoid external services.",
            },
        }
        topic = topics[topic_key]
        embed = discord.Embed(title="Cadis Etrama Di Raizel", description=topic["summary"], color=EMBED_COLOR)
        embed.set_author(name=topic["title"])
        embed.add_field(name="Syntax", value=topic["syntax"], inline=False)
        embed.add_field(name="Examples", value=topic["examples"], inline=False)
        embed.add_field(name="Tips", value=topic["notes"], inline=False)
        embed.set_footer(text=f"Help Topic: {topic['title']}")
        return embed

    async def help_func(self, message: discord.Message, *, topic: Optional[str] = None) -> str:
        resolved_topic = self._resolve_help_topic(topic)
        if topic and resolved_topic is None:
            embed = discord.Embed(
                title="Cadis Etrama Di Raizel",
                description="I do not have a focused help page for that topic yet.",
                color=EMBED_COLOR,
            )
            embed.add_field(
                name="Available Topics",
                value="`dungeon` `slots` `drawgame` `hangman` `wordchain` `trivia` `job` `crash` `marriage` `shop` `duel` `profile` `stats`",
                inline=False,
            )
            await message.reply(embed=embed)
            return "Unknown help topic"
        if resolved_topic is not None:
            await message.reply(embed=self._build_topic_help_embed(resolved_topic))
            return f"Help topic shown for {resolved_topic}"
        categories = self._available_help_categories()
        view = HelpMenuView(cog=self, author_id=message.author.id, categories=categories)
        sent = await message.reply(embed=self.build_help_embed(), view=view)
        view.bind_message(sent)
        return "Interactive help shown"

    def _parse_duration_with_remainder(self, raw_text: str) -> tuple[int, str]:
        cleaned = (raw_text or "").strip()
        if not cleaned:
            raise ValueError("Give a duration like `10m`, `90s`, or `1h 30m`.")
        colon_match = re.match(r"^(\d+):(\d{1,2})(?::(\d{1,2}))?(?:\s+(.+))?$", cleaned)
        if colon_match:
            first = int(colon_match.group(1))
            second = int(colon_match.group(2))
            third = colon_match.group(3)
            seconds = first * 60 + second if third is None else first * 3600 + second * 60 + int(third)
            return seconds, (colon_match.group(4) or "").strip()
        unit_seconds = {
            "d": 86400, "day": 86400, "days": 86400,
            "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
            "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
            "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
        }
        cursor = 0
        total_seconds = 0
        matched_any = False
        while True:
            match = re.match(
                r"\s*(\d+)\s*(days?|d|hours?|hrs?|hr|h|minutes?|mins?|min|m|seconds?|secs?|sec|s)\b",
                cleaned[cursor:],
                flags=re.IGNORECASE,
            )
            if not match:
                break
            matched_any = True
            total_seconds += int(match.group(1)) * unit_seconds[match.group(2).lower()]
            cursor += match.end()
        if matched_any:
            return total_seconds, cleaned[cursor:].strip()
        seconds_only = re.match(r"^(\d+)(?:\s+(.+))?$", cleaned)
        if seconds_only:
            return int(seconds_only.group(1)), (seconds_only.group(2) or "").strip()
        raise ValueError("Could not parse that duration. Try `10m`, `90s`, or `1h 30m`.")

    def _safe_eval_expression(self, expression: str) -> float:
        raw = (expression or "").strip()
        if not raw:
            raise ValueError("Usage: calc <expression>")
        if len(raw) > 200:
            raise ValueError("That expression is too long.")
        tree = ast.parse(raw, mode="eval")
        allowed_binops = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.FloorDiv: operator.floordiv,
            ast.Mod: operator.mod,
            ast.Pow: operator.pow,
        }
        allowed_unary = {
            ast.UAdd: lambda value: value,
            ast.USub: lambda value: -value,
        }
        allowed_funcs = {
            "abs": abs,
            "round": round,
            "sqrt": math.sqrt,
            "ceil": math.ceil,
            "floor": math.floor,
        }
        allowed_names = {"pi": math.pi, "e": math.e}

        def _eval(node: ast.AST) -> float:
            if isinstance(node, ast.Expression):
                return _eval(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return float(node.value)
            if isinstance(node, ast.BinOp) and type(node.op) in allowed_binops:
                left = _eval(node.left)
                right = _eval(node.right)
                if isinstance(node.op, ast.Pow) and abs(right) > 6:
                    raise ValueError("Exponent is too large.")
                return float(allowed_binops[type(node.op)](left, right))
            if isinstance(node, ast.UnaryOp) and type(node.op) in allowed_unary:
                return float(allowed_unary[type(node.op)](_eval(node.operand)))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in allowed_funcs:
                args = [_eval(arg) for arg in node.args]
                return float(allowed_funcs[node.func.id](*args))
            if isinstance(node, ast.Name) and node.id in allowed_names:
                return float(allowed_names[node.id])
            raise ValueError("Only simple math is allowed.")

        result = _eval(tree)
        if not math.isfinite(result):
            raise ValueError("Result is not finite.")
        if abs(result) > 1_000_000_000_000:
            raise ValueError("Result is too large.")
        return result

    def _format_calc_result(self, result: float) -> str:
        if float(result).is_integer():
            return str(int(result))
        return f"{result:.8f}".rstrip("0").rstrip(".")

    def _schedule_runtime_reminder(
        self,
        *,
        channel: discord.abc.Messageable,
        mention_text: str,
        wait_seconds: int,
        body: str,
    ) -> None:
        # Runtime-only by design to avoid invasive restart persistence changes.
        async def _runner() -> None:
            try:
                await asyncio.sleep(wait_seconds)
                with contextlib.suppress(discord.HTTPException, AttributeError):
                    await channel.send(f"{mention_text} {body}".strip())
            except asyncio.CancelledError:
                return

        task = asyncio.create_task(_runner())
        self._reminder_tasks.add(task)
        task.add_done_callback(lambda done: self._reminder_tasks.discard(done))

    def _add_note_sync(self, user_id: int, guild_id: int, content: str) -> dict[str, Any]:
        with self._connect_db() as conn:
            cursor = conn.execute(
                "INSERT INTO utility_notes (user_id, guild_id, content, created_at) VALUES (?, ?, ?, ?)",
                (user_id, guild_id, content, _utcnow().isoformat()),
            )
            return {"note_id": int(cursor.lastrowid), "content": content}

    def _list_notes_sync(self, user_id: int) -> list[dict[str, Any]]:
        with self._connect_db() as conn:
            rows = conn.execute(
                "SELECT note_id, guild_id, content, created_at FROM utility_notes WHERE user_id = ? ORDER BY note_id ASC",
                (user_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def _delete_note_sync(self, user_id: int, note_id: int) -> dict[str, Any]:
        with self._connect_db() as conn:
            row = conn.execute(
                "SELECT note_id, content FROM utility_notes WHERE note_id = ? AND user_id = ?",
                (note_id, user_id),
            ).fetchone()
            if row is None:
                return {"status": "missing"}
            conn.execute("DELETE FROM utility_notes WHERE note_id = ? AND user_id = ?", (note_id, user_id))
            return {"status": "success", "content": str(row["content"])}

    def _record_message_activity_sync(self, guild_id: int, user_id: int, display_name: str) -> None:
        with self._connect_db() as conn:
            self._prepare_profile_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name)
            self._record_progress_event_conn(
                conn,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
                stat_updates={"active_minutes": 1},
            )

    async def _record_message_activity(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        last = self._activity_cooldowns.get(key)
        if last is not None and (now - last) < 60.0:
            return
        self._activity_cooldowns[key] = now
        with contextlib.suppress(Exception):
            await self._run_db(
                self._record_message_activity_sync,
                message.guild.id,
                message.author.id,
                _display_name(message.author),
            )

    def _get_relationship_row_conn(self, conn: sqlite3.Connection, *, guild_id: int, user_id: int) -> Optional[sqlite3.Row]:
        return conn.execute(
            """
            SELECT user_id, spouse_id, spouse_name, married_at, love_score
            FROM marriage_relationships
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        ).fetchone()

    def _get_marriage_status_sync(self, guild_id: int, user_id: int) -> dict[str, Any]:
        with self._connect_db() as conn:
            relationship = self._get_relationship_row_conn(conn, guild_id=guild_id, user_id=user_id)
            incoming = conn.execute(
                """
                SELECT proposer_user_id, proposer_name, created_at
                FROM marriage_proposals
                WHERE guild_id = ? AND target_user_id = ?
                """,
                (guild_id, user_id),
            ).fetchone()
            outgoing = conn.execute(
                """
                SELECT target_user_id, proposer_name, created_at
                FROM marriage_proposals
                WHERE guild_id = ? AND proposer_user_id = ?
                """,
                (guild_id, user_id),
            ).fetchone()
            return {
                "relationship": dict(relationship) if relationship is not None else None,
                "incoming": dict(incoming) if incoming is not None else None,
                "outgoing": dict(outgoing) if outgoing is not None else None,
            }

    def _propose_marriage_sync(
        self,
        guild_id: int,
        proposer_id: int,
        proposer_name: str,
        target_id: int,
        target_name: str,
    ) -> dict[str, Any]:
        with self._connect_db() as conn:
            if proposer_id == target_id:
                return {"status": "self"}
            if self._get_relationship_row_conn(conn, guild_id=guild_id, user_id=proposer_id) is not None:
                return {"status": "proposer_married"}
            if self._get_relationship_row_conn(conn, guild_id=guild_id, user_id=target_id) is not None:
                return {"status": "target_married"}
            outgoing = conn.execute(
                "SELECT target_user_id FROM marriage_proposals WHERE guild_id = ? AND proposer_user_id = ?",
                (guild_id, proposer_id),
            ).fetchone()
            if outgoing is not None:
                return {"status": "outgoing_exists", "target_user_id": int(outgoing["target_user_id"])}
            incoming = conn.execute(
                """
                SELECT proposer_user_id, proposer_name
                FROM marriage_proposals
                WHERE guild_id = ? AND target_user_id = ?
                """,
                (guild_id, target_id),
            ).fetchone()
            if incoming is not None:
                if int(incoming["proposer_user_id"]) == proposer_id:
                    return {"status": "duplicate"}
                return {"status": "target_pending", "existing_name": str(incoming["proposer_name"] or "Someone")}
            conn.execute(
                """
                INSERT INTO marriage_proposals (guild_id, target_user_id, proposer_user_id, proposer_name, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (guild_id, target_id, proposer_id, proposer_name, _utcnow().isoformat()),
            )
            return {"status": "success", "target_name": target_name}

    def _accept_marriage_sync(self, guild_id: int, target_id: int, target_name: str) -> dict[str, Any]:
        with self._connect_db() as conn:
            proposal = conn.execute(
                """
                SELECT proposer_user_id, proposer_name, created_at
                FROM marriage_proposals
                WHERE guild_id = ? AND target_user_id = ?
                """,
                (guild_id, target_id),
            ).fetchone()
            if proposal is None:
                return {"status": "missing"}
            proposer_id = int(proposal["proposer_user_id"])
            proposer_name = str(proposal["proposer_name"] or f"User {proposer_id}")
            if self._get_relationship_row_conn(conn, guild_id=guild_id, user_id=target_id) is not None:
                return {"status": "target_married"}
            if self._get_relationship_row_conn(conn, guild_id=guild_id, user_id=proposer_id) is not None:
                return {"status": "proposer_married", "proposer_name": proposer_name}
            married_at = _utcnow().isoformat()
            conn.execute(
                """
                INSERT INTO marriage_relationships (guild_id, user_id, spouse_id, spouse_name, married_at, love_score)
                VALUES (?, ?, ?, ?, ?, 10)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    spouse_id = excluded.spouse_id,
                    spouse_name = excluded.spouse_name,
                    married_at = excluded.married_at,
                    love_score = excluded.love_score
                """,
                (guild_id, target_id, proposer_id, proposer_name, married_at),
            )
            conn.execute(
                """
                INSERT INTO marriage_relationships (guild_id, user_id, spouse_id, spouse_name, married_at, love_score)
                VALUES (?, ?, ?, ?, ?, 10)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    spouse_id = excluded.spouse_id,
                    spouse_name = excluded.spouse_name,
                    married_at = excluded.married_at,
                    love_score = excluded.love_score
                """,
                (guild_id, proposer_id, target_id, target_name, married_at),
            )
            conn.execute(
                """
                DELETE FROM marriage_proposals
                WHERE guild_id = ? AND (target_user_id IN (?, ?) OR proposer_user_id IN (?, ?))
                """,
                (guild_id, target_id, proposer_id, target_id, proposer_id),
            )
            return {
                "status": "success",
                "proposer_id": proposer_id,
                "proposer_name": proposer_name,
                "married_at": married_at,
            }

    def _decline_marriage_sync(self, guild_id: int, target_id: int) -> dict[str, Any]:
        with self._connect_db() as conn:
            proposal = conn.execute(
                """
                SELECT proposer_user_id, proposer_name
                FROM marriage_proposals
                WHERE guild_id = ? AND target_user_id = ?
                """,
                (guild_id, target_id),
            ).fetchone()
            if proposal is None:
                return {"status": "missing"}
            conn.execute(
                "DELETE FROM marriage_proposals WHERE guild_id = ? AND target_user_id = ?",
                (guild_id, target_id),
            )
            return {
                "status": "success",
                "proposer_id": int(proposal["proposer_user_id"]),
                "proposer_name": str(proposal["proposer_name"] or "Unknown User"),
            }

    def _divorce_sync(self, guild_id: int, user_id: int) -> dict[str, Any]:
        with self._connect_db() as conn:
            relationship = self._get_relationship_row_conn(conn, guild_id=guild_id, user_id=user_id)
            if relationship is None:
                return {"status": "missing"}
            spouse_id = int(relationship["spouse_id"])
            spouse_name = str(relationship["spouse_name"] or f"User {spouse_id}")
            conn.execute(
                "DELETE FROM marriage_relationships WHERE guild_id = ? AND user_id IN (?, ?)",
                (guild_id, user_id, spouse_id),
            )
            conn.execute(
                """
                DELETE FROM marriage_proposals
                WHERE guild_id = ? AND (target_user_id IN (?, ?) OR proposer_user_id IN (?, ?))
                """,
                (guild_id, user_id, spouse_id, user_id, spouse_id),
            )
            return {"status": "success", "spouse_id": spouse_id, "spouse_name": spouse_name}

    def _split_sentences_locally(self, raw_text: str) -> list[str]:
        cleaned = self._capitalize_sentences(self._normalize_text_locally(raw_text))
        return [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", cleaned) if segment.strip()]

    def _finalize_local_text(self, text: str) -> str:
        cleaned = self._capitalize_sentences(self._normalize_text_locally(text))
        if cleaned and cleaned[-1] not in ".!?":
            cleaned += "."
        return cleaned

    def _extract_keywords_locally(self, raw_text: str, *, limit: int = 8) -> list[str]:
        stopwords = {
            "the", "and", "for", "that", "with", "this", "from", "your", "have", "will", "into", "about",
            "there", "their", "they", "them", "were", "been", "when", "what", "where", "while", "would",
            "could", "should", "just", "really", "very", "more", "some", "than", "then", "over", "under",
            "after", "before", "because", "since", "also", "only", "still", "once",
        }
        counts: dict[str, int] = {}
        for word in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", self._normalize_text_locally(raw_text).lower()):
            if word in stopwords:
                continue
            counts[word] = counts.get(word, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))
        return [word for word, _ in ranked[:limit]]

    def _summarize_locally(self, raw_text: str, *, max_sentences: int = 2, max_words: int = 38) -> str:
        sentences = self._split_sentences_locally(raw_text)
        if not sentences:
            return ""
        chosen: list[str] = []
        word_total = 0
        for sentence in sentences:
            sentence_words = sentence.split()
            if chosen and (len(chosen) >= max_sentences or word_total + len(sentence_words) > max_words):
                break
            chosen.append(sentence)
            word_total += len(sentence_words)
        summary = " ".join(chosen)
        words = summary.split()
        if len(words) > max_words:
            summary = " ".join(words[:max_words]).rstrip(" ,;:") + "..."
        return self._finalize_local_text(summary)

    def _shorten_locally(self, raw_text: str) -> str:
        summary = self._summarize_locally(raw_text, max_sentences=1, max_words=22)
        words = summary.split()
        if len(words) > 22:
            summary = " ".join(words[:22]).rstrip(" ,;:") + "..."
        return summary

    def _expand_locally(self, raw_text: str) -> str:
        base = self._finalize_local_text(raw_text)
        keywords = self._extract_keywords_locally(base, limit=3)
        if keywords:
            return f"{base} Main focus: {', '.join(keywords)}."
        return f"{base} This adds a little more context while keeping the main point clear."

    def _tone_casual_locally(self, raw_text: str) -> str:
        result = self._finalize_local_text(raw_text)
        replacements = {
            "cannot": "can't",
            "do not": "don't",
            "will not": "won't",
            "I am": "I'm",
            "you are": "you're",
            "thank you": "thanks",
            "going to": "gonna",
        }
        for source, target in replacements.items():
            result = re.sub(rf"\b{re.escape(source)}\b", target, result, flags=re.IGNORECASE)
        return result

    def _tone_formal_locally(self, raw_text: str) -> str:
        return self._finalize_local_text(self._apply_formal_rewrite(raw_text))

    def _get_stats_snapshot_sync(self, guild_id: int, user_id: int, display_name: str) -> dict[str, Any]:
        with self._connect_db() as conn:
            profile = self._prepare_profile_conn(conn, guild_id=guild_id, user_id=user_id, display_name=display_name)
            stats_map = self._get_stats_map_conn(conn, guild_id=guild_id, user_id=user_id)
            marriage = self._get_relationship_row_conn(conn, guild_id=guild_id, user_id=user_id)
            return {
                "profile": profile,
                "stats": stats_map,
                "marriage": dict(marriage) if marriage is not None else None,
            }

    def _total_wins_from_stats(self, stats_map: dict[str, int]) -> int:
        keys = (
            "gamble_wins",
            "blackjack_wins",
            "slots_wins",
            "crash_wins",
            "duel_wins",
            "dungeon_wins",
            "rob_successes",
            "steal_successes",
            "heist_successes",
        )
        return sum(int(stats_map.get(key, 0)) for key in keys)

    def _total_losses_from_stats(self, stats_map: dict[str, int]) -> int:
        keys = (
            "gamble_losses",
            "blackjack_losses",
            "slots_losses",
            "crash_losses",
            "duel_losses",
            "dungeon_failures",
            "rob_failures",
            "steal_failures",
            "heist_failures",
        )
        return sum(int(stats_map.get(key, 0)) for key in keys)

    def _casino_volume_from_stats(self, stats_map: dict[str, int]) -> int:
        keys = ("gamble_plays", "blackjack_plays", "slots_plays", "crash_plays")
        return sum(int(stats_map.get(key, 0)) for key in keys)

    def _most_used_action_from_stats(self, stats_map: dict[str, int]) -> tuple[str, int]:
        labels = {
            "work_uses": "work",
            "beg_uses": "beg",
            "fish_uses": "fish",
            "hunt_uses": "hunt",
            "search_uses": "search",
            "mine_uses": "mine",
            "deliver_uses": "deliver",
            "scavenge_uses": "scavenge",
            "freelance_uses": "freelance",
            "craft_uses": "craft",
            "repair_uses": "repair",
            "patrol_uses": "patrol",
            "gamble_plays": "gamble",
            "blackjack_plays": "blackjack",
            "slots_plays": "slots",
            "crash_plays": "crash",
            "dungeon_wins": "dungeon clears",
        }
        ranked = sorted(
            ((label, int(stats_map.get(key, 0))) for key, label in labels.items()),
            key=lambda item: (-item[1], item[0]),
        )
        return ranked[0] if ranked and ranked[0][1] > 0 else ("No tracked action yet", 0)

    def _get_stats_leaderboard_sync(self, guild_id: int, mode: str) -> list[dict[str, Any]]:
        with self._connect_db() as conn:
            profile_rows = conn.execute(
                "SELECT user_id, last_known_name, wallet FROM economy_profiles WHERE guild_id = ?",
                (guild_id,),
            ).fetchall()
            stat_rows = conn.execute(
                "SELECT user_id, stat_key, value FROM economy_user_stats WHERE guild_id = ?",
                (guild_id,),
            ).fetchall()
            stats_by_user: dict[int, dict[str, int]] = {}
            for row in stat_rows:
                bucket = stats_by_user.setdefault(int(row["user_id"]), {})
                bucket[str(row["stat_key"])] = int(row["value"])
            results: list[dict[str, Any]] = []
            for row in profile_rows:
                user_id = int(row["user_id"])
                stats_map = stats_by_user.get(user_id, {})
                if mode == "dungeon":
                    score = int(stats_map.get("dungeon_wins", 0))
                elif mode == "gamblers":
                    score = self._casino_volume_from_stats(stats_map)
                elif mode == "wins":
                    score = self._total_wins_from_stats(stats_map)
                elif mode == "losses":
                    score = self._total_losses_from_stats(stats_map)
                else:
                    score = 0
                if score <= 0:
                    continue
                results.append(
                    {
                        "user_id": user_id,
                        "last_known_name": str(row["last_known_name"] or f"User {user_id}"),
                        "wallet": int(row["wallet"] or 0),
                        "score": score,
                    }
                )
            results.sort(key=lambda entry: (-int(entry["score"]), -int(entry["wallet"]), int(entry["user_id"])))
            return results

    def _build_ranked_embed(
        self,
        *,
        title: str,
        description: str,
        guild: discord.Guild,
        rows: list[dict[str, Any]],
        page: int,
        value_label: str,
    ) -> discord.Embed:
        total_pages = max(1, (len(rows) + ECONOMY_LEADERBOARD_PAGE_SIZE - 1) // ECONOMY_LEADERBOARD_PAGE_SIZE)
        safe_page = max(1, min(page, total_pages))
        start_index = (safe_page - 1) * ECONOMY_LEADERBOARD_PAGE_SIZE
        page_rows = rows[start_index:start_index + ECONOMY_LEADERBOARD_PAGE_SIZE]
        lines: list[str] = []
        for offset, row in enumerate(page_rows, start=start_index + 1):
            member = guild.get_member(int(row["user_id"]))
            name = _display_name(member) if member else str(row["last_known_name"])
            lines.append(f"`{offset}.` {name} - {int(row['score'])} {value_label}")
        embed = discord.Embed(title="Cadis Etrama Di Raizel", description=description, color=EMBED_COLOR)
        embed.set_author(name=title)
        embed.add_field(name="Rankings", value="\n".join(lines) or "No data recorded yet.", inline=False)
        embed.set_footer(text=f"Page {safe_page}/{total_pages}")
        return embed

    async def profile_func(self, message: discord.Message, *, target_user: Optional[discord.abc.User] = None) -> str:
        if message.guild is None:
            await message.reply("Profiles are only available inside a server.")
            return "Profile unavailable in DMs"
        target = target_user or message.author
        async with self._profile_lock:
            snapshot = self._profile_snapshot(guild=message.guild, target_user=target)
        economy_profile = await self._run_db(
            self._get_economy_profile_sync,
            message.guild.id,
            target.id,
            _display_name(target),
        )
        marriage_status = await self._run_db(self._get_marriage_status_sync, message.guild.id, target.id)
        embed = self._build_profile_embed(
            guild=message.guild,
            target_user=target,
            snapshot=snapshot,
            economy_profile=economy_profile,
        )
        relationship = marriage_status.get("relationship")
        if relationship:
            married_at = dt.datetime.fromisoformat(str(relationship["married_at"]))
            days_married = max(0, (_utcnow() - married_at).days)
            embed.add_field(
                name="Marriage",
                value=(
                    f"Spouse: **{relationship['spouse_name']}**\n"
                    f"Love: **{int(relationship['love_score'])}**\n"
                    f"Married: **{days_married} day(s)**"
                ),
                inline=False,
            )
        await message.reply(embed=embed)
        return f"Profile shown for {_display_name(target)}"

    async def ping_func(self, message: discord.Message) -> str:
        latency_ms = int(round(float(self.bot.latency) * 1000))
        embed = discord.Embed(title="Cadis Etrama Di Raizel", description="Current gateway latency.", color=EMBED_COLOR)
        embed.set_author(name="Ping")
        embed.add_field(name="Latency", value=f"**{latency_ms} ms**", inline=False)
        await message.reply(embed=embed)
        return "Ping shown"

    async def uptime_func(self, message: discord.Message) -> str:
        elapsed = max(0, int((_utcnow() - self._started_at).total_seconds()))
        embed = discord.Embed(
            title="Cadis Etrama Di Raizel",
            description="Bot runtime since the current process started.",
            color=EMBED_COLOR,
        )
        embed.set_author(name="Uptime")
        embed.add_field(name="Started", value=discord.utils.format_dt(self._started_at, "F"), inline=False)
        embed.add_field(name="Elapsed", value=_format_relative_seconds(elapsed), inline=False)
        await message.reply(embed=embed)
        return "Uptime shown"

    async def calc_func(self, message: discord.Message, *, raw_expression: str) -> str:
        try:
            result = self._safe_eval_expression(raw_expression)
        except Exception as exc:
            await message.reply(f"Calculator error: {exc}")
            return "Calc failed"
        embed = discord.Embed(title="Cadis Etrama Di Raizel", description="Safe local calculator result.", color=EMBED_COLOR)
        embed.set_author(name="Calculator")
        embed.add_field(name="Expression", value=(raw_expression or "").strip()[:1024] or "(empty)", inline=False)
        embed.add_field(name="Result", value=self._format_calc_result(result), inline=False)
        await message.reply(embed=embed)
        return "Calc shown"

    async def timer_func(self, message: discord.Message, *, raw_duration: str) -> str:
        try:
            seconds, remainder = self._parse_duration_with_remainder(raw_duration)
        except ValueError as exc:
            await message.reply(str(exc))
            return "Timer usage error"
        if seconds <= 0:
            await message.reply("Timer duration must be greater than zero.")
            return "Timer invalid"
        self._schedule_runtime_reminder(
            channel=message.channel,
            mention_text=message.author.mention,
            wait_seconds=seconds,
            body=f"your timer finished after **{_format_relative_seconds(seconds)}**.",
        )
        extra = f"\nExtra text ignored: `{remainder}`" if remainder else ""
        await message.reply(f"Timer started for **{_format_relative_seconds(seconds)}**.{extra}")
        return "Timer started"

    async def remind_func(self, message: discord.Message, *, raw_input: str) -> str:
        try:
            seconds, reminder_text = self._parse_duration_with_remainder(raw_input)
        except ValueError as exc:
            await message.reply(str(exc))
            return "Reminder usage error"
        if seconds <= 0:
            await message.reply("Reminder duration must be greater than zero.")
            return "Reminder invalid"
        if not reminder_text:
            await message.reply("Usage: remind <time> <text>")
            return "Reminder text missing"
        self._schedule_runtime_reminder(
            channel=message.channel,
            mention_text=message.author.mention,
            wait_seconds=seconds,
            body=f"reminder: {reminder_text}",
        )
        await message.reply(
            f"Reminder set for **{_format_relative_seconds(seconds)}**.\n"
            f"Text: {reminder_text}"
        )
        return "Reminder started"

    async def notes_add_func(self, message: discord.Message, *, raw_text: str) -> str:
        content = (raw_text or "").strip()
        if not content:
            await message.reply("Usage: notes add <text>")
            return "Notes add empty"
        result = await self._run_db(
            self._add_note_sync,
            message.author.id,
            message.guild.id if message.guild else 0,
            content,
        )
        await message.reply(f"Saved note **#{result['note_id']}**.")
        return "Note added"

    async def notes_list_func(self, message: discord.Message) -> str:
        rows = await self._run_db(self._list_notes_sync, message.author.id)
        embed = discord.Embed(title="Cadis Etrama Di Raizel", description="Your saved notes.", color=EMBED_COLOR)
        embed.set_author(name="Notes")
        if not rows:
            embed.add_field(name="Notes", value="You have not saved any notes yet.", inline=False)
            await message.reply(embed=embed)
            return "Notes empty"
        lines = [f"`#{int(row['note_id'])}` {str(row['content'])}" for row in rows[:NOTES_LIST_PAGE_SIZE]]
        embed.add_field(name="Entries", value="\n".join(lines), inline=False)
        if len(rows) > NOTES_LIST_PAGE_SIZE:
            embed.set_footer(text=f"Showing {NOTES_LIST_PAGE_SIZE} of {len(rows)} notes")
        await message.reply(embed=embed)
        return "Notes shown"

    async def notes_delete_func(self, message: discord.Message, *, note_id: int) -> str:
        if note_id <= 0:
            await message.reply("Usage: notes delete <id>")
            return "Notes delete invalid"
        result = await self._run_db(self._delete_note_sync, message.author.id, note_id)
        if result["status"] != "success":
            await message.reply("That note was not found in your saved notes.")
            return "Notes delete missing"
        await message.reply(f"Deleted note **#{note_id}**.")
        return "Note deleted"

    def _build_local_text_embed(self, *, author: str, description: str, output: str, input_text: Optional[str] = None) -> discord.Embed:
        embed = discord.Embed(title="Cadis Etrama Di Raizel", description=description, color=EMBED_COLOR)
        embed.set_author(name=author)
        if input_text:
            embed.add_field(name="Input", value=input_text[:1024], inline=False)
        embed.add_field(name="Output", value=(output or "(empty)")[:1024], inline=False)
        return embed

    async def summarize_func(self, message: discord.Message, *, raw_text: str) -> str:
        content = (raw_text or "").strip()
        if not content:
            await message.reply("Usage: summarize <text>")
            return "Summarize usage error"
        result = self._summarize_locally(content)
        await message.reply(embed=self._build_local_text_embed(author="Summarize", description="Local heuristic summary.", input_text=content, output=result))
        return "Summarize complete"

    async def keywords_func(self, message: discord.Message, *, raw_text: str) -> str:
        content = (raw_text or "").strip()
        if not content:
            await message.reply("Usage: keywords <text>")
            return "Keywords usage error"
        output = ", ".join(self._extract_keywords_locally(content)) or "No strong keywords found."
        await message.reply(embed=self._build_local_text_embed(author="Keywords", description="Local keyword extraction.", input_text=content, output=output))
        return "Keywords complete"

    async def fix_func(self, message: discord.Message, *, raw_text: str) -> str:
        content = (raw_text or "").strip()
        if not content:
            await message.reply("Usage: fix <text>")
            return "Fix usage error"
        output = self._finalize_local_text(content)
        await message.reply(embed=self._build_local_text_embed(author="Fix", description="Local grammar-lite cleanup.", input_text=content, output=output))
        return "Fix complete"

    async def shorten_func(self, message: discord.Message, *, raw_text: str) -> str:
        content = (raw_text or "").strip()
        if not content:
            await message.reply("Usage: shorten <text>")
            return "Shorten usage error"
        output = self._shorten_locally(content)
        await message.reply(embed=self._build_local_text_embed(author="Shorten", description="Local shorter rewrite.", input_text=content, output=output))
        return "Shorten complete"

    async def expand_func(self, message: discord.Message, *, raw_text: str) -> str:
        content = (raw_text or "").strip()
        if not content:
            await message.reply("Usage: expand <text>")
            return "Expand usage error"
        output = self._expand_locally(content)
        await message.reply(embed=self._build_local_text_embed(author="Expand", description="Local lightweight expansion.", input_text=content, output=output))
        return "Expand complete"

    async def tone_func(self, message: discord.Message, *, mode: str, raw_text: str) -> str:
        content = (raw_text or "").strip()
        if not content:
            await message.reply("Usage: tone casual <text> or tone formal <text>")
            return "Tone usage error"
        output = self._tone_formal_locally(content) if mode == "formal" else self._tone_casual_locally(content)
        await message.reply(embed=self._build_local_text_embed(author=f"Tone ({mode})", description="Local deterministic tone adjustment.", input_text=content, output=output))
        return f"Tone complete ({mode})"

    def _build_stats_overview_embed(self, *, display_name: str, profile: dict[str, Any], stats_map: dict[str, int]) -> discord.Embed:
        wins = self._total_wins_from_stats(stats_map)
        losses = self._total_losses_from_stats(stats_map)
        most_used_label, most_used_count = self._most_used_action_from_stats(stats_map)
        active_minutes = int(stats_map.get("active_minutes", 0))
        embed = discord.Embed(title="Cadis Etrama Di Raizel", description=f"Stats overview for **{display_name}**.", color=EMBED_COLOR)
        embed.set_author(name="My Stats")
        embed.add_field(
            name="Economy",
            value=(
                f"Wallet: **{int(profile.get('wallet', 0))} coins**\n"
                f"Earned: **{int(profile.get('total_earned', 0))}**\n"
                f"Spent: **{int(profile.get('total_spent', 0))}**"
            ),
            inline=False,
        )
        embed.add_field(
            name="Games",
            value=(
                f"Wins: **{wins}**\n"
                f"Losses: **{losses}**\n"
                f"Dungeon Clears: **{int(stats_map.get('dungeon_wins', 0))}**"
            ),
            inline=False,
        )
        embed.add_field(
            name="Usage",
            value=(
                f"Most Used: **{most_used_label}** ({most_used_count})\n"
                f"Active Time: **{active_minutes} minute(s)**\n"
                f"Daily Claims: **{int(stats_map.get('daily_claims', 0))}**"
            ),
            inline=False,
        )
        return embed

    async def mystats_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Stats are only available inside a server.")
            return "Stats unavailable in DMs"
        snapshot = await self._run_db(self._get_stats_snapshot_sync, message.guild.id, message.author.id, _display_name(message.author))
        await message.reply(embed=self._build_stats_overview_embed(display_name=_display_name(message.author), profile=snapshot["profile"], stats_map=snapshot["stats"]))
        return "Stats shown"

    async def dungeonstats_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Dungeon stats are only available inside a server.")
            return "Dungeon stats unavailable in DMs"
        snapshot = await self._run_db(self._get_stats_snapshot_sync, message.guild.id, message.author.id, _display_name(message.author))
        stats_map = snapshot["stats"]
        wins = int(stats_map.get("dungeon_wins", 0))
        losses = int(stats_map.get("dungeon_failures", 0))
        total = wins + losses
        winrate = (wins / total * 100.0) if total else 0.0
        embed = discord.Embed(title="Cadis Etrama Di Raizel", description="Dungeon performance breakdown.", color=EMBED_COLOR)
        embed.set_author(name="Dungeon Stats")
        embed.add_field(name="Clears", value=str(wins), inline=True)
        embed.add_field(name="Failures", value=str(losses), inline=True)
        embed.add_field(name="Win Rate", value=f"{winrate:.1f}%", inline=True)
        embed.add_field(
            name="Run Resources",
            value=(
                f"Lives: **{int(snapshot['profile'].get('dungeon_lives', 0))}/{DUNGEON_LIFE_MAX}**\n"
                f"Prestige: **{int(snapshot['profile'].get('prestige', 0))}**"
            ),
            inline=False,
        )
        await message.reply(embed=embed)
        return "Dungeon stats shown"

    async def casinostats_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Casino stats are only available inside a server.")
            return "Casino stats unavailable in DMs"
        snapshot = await self._run_db(self._get_stats_snapshot_sync, message.guild.id, message.author.id, _display_name(message.author))
        stats_map = snapshot["stats"]
        embed = discord.Embed(title="Cadis Etrama Di Raizel", description="Casino and risk-game record.", color=EMBED_COLOR)
        embed.set_author(name="Casino Stats")
        embed.add_field(name="Gamble", value=f"Plays: **{int(stats_map.get('gamble_plays', 0))}**\nWins: **{int(stats_map.get('gamble_wins', 0))}**\nLosses: **{int(stats_map.get('gamble_losses', 0))}**", inline=True)
        embed.add_field(name="Blackjack", value=f"Plays: **{int(stats_map.get('blackjack_plays', 0))}**\nWins: **{int(stats_map.get('blackjack_wins', 0))}**\nLosses: **{int(stats_map.get('blackjack_losses', 0))}**", inline=True)
        embed.add_field(
            name="Slots / Crash",
            value=(
                f"Slots: **{int(stats_map.get('slots_plays', 0))}** plays\n"
                f"Slot Wins: **{int(stats_map.get('slots_wins', 0))}**\n"
                f"Crash Wins: **{int(stats_map.get('crash_wins', 0))}**"
            ),
            inline=True,
        )
        await message.reply(embed=embed)
        return "Casino stats shown"

    async def jobstats_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Job stats are only available inside a server.")
            return "Job stats unavailable in DMs"
        snapshot = await self._run_db(self._get_stats_snapshot_sync, message.guild.id, message.author.id, _display_name(message.author))
        profile = snapshot["profile"]
        stats_map = snapshot["stats"]
        profession = self._resolve_profession(profile.get("profession"))
        embed = discord.Embed(title="Cadis Etrama Di Raizel", description="Work and profession progression.", color=EMBED_COLOR)
        embed.set_author(name="Job Stats")
        embed.add_field(
            name="Profession",
            value=(
                f"Current: **{profession['name']}**\n"
                f"Level: **{int(profile.get('profession_level', 1))}**\n"
                f"XP: **{int(profile.get('profession_xp', 0))} / {int(profile.get('profession_xp_needed', 0))}**"
            ),
            inline=False,
        )
        embed.add_field(
            name="Usage",
            value=(
                f"Work: **{int(stats_map.get('work_uses', 0))}**\n"
                f"Job Upgrades: **{int(stats_map.get('job_upgrades', 0))}**\n"
                f"Most Used: **{self._most_used_action_from_stats(stats_map)[0]}**"
            ),
            inline=False,
        )
        await message.reply(embed=embed)
        return "Job stats shown"

    async def winrate_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Win rate is only available inside a server.")
            return "Win rate unavailable in DMs"
        snapshot = await self._run_db(self._get_stats_snapshot_sync, message.guild.id, message.author.id, _display_name(message.author))
        wins = self._total_wins_from_stats(snapshot["stats"])
        losses = self._total_losses_from_stats(snapshot["stats"])
        total = wins + losses
        rate = (wins / total * 100.0) if total else 0.0
        await message.reply(f"Overall win rate: **{rate:.1f}%** ({wins} wins / {total} tracked results)")
        return "Win rate shown"

    async def lossrate_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Loss rate is only available inside a server.")
            return "Loss rate unavailable in DMs"
        snapshot = await self._run_db(self._get_stats_snapshot_sync, message.guild.id, message.author.id, _display_name(message.author))
        wins = self._total_wins_from_stats(snapshot["stats"])
        losses = self._total_losses_from_stats(snapshot["stats"])
        total = wins + losses
        rate = (losses / total * 100.0) if total else 0.0
        await message.reply(f"Overall loss rate: **{rate:.1f}%** ({losses} losses / {total} tracked results)")
        return "Loss rate shown"

    async def mostused_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Usage stats are only available inside a server.")
            return "Most used unavailable in DMs"
        snapshot = await self._run_db(self._get_stats_snapshot_sync, message.guild.id, message.author.id, _display_name(message.author))
        label, count = self._most_used_action_from_stats(snapshot["stats"])
        await message.reply(f"Most used tracked action: **{label}** ({count})")
        return "Most used shown"

    async def playtime_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Playtime is only available inside a server.")
            return "Playtime unavailable in DMs"
        snapshot = await self._run_db(self._get_stats_snapshot_sync, message.guild.id, message.author.id, _display_name(message.author))
        active_minutes = int(snapshot["stats"].get("active_minutes", 0))
        hours = active_minutes / 60.0
        await message.reply(f"Tracked active time: **{active_minutes} minute(s)**\nApproximate hours: **{hours:.1f}h**")
        return "Playtime shown"

    async def topdungeon_func(self, message: discord.Message, *, page: int = 1) -> str:
        if message.guild is None:
            await message.reply("Dungeon leaderboard is only available inside a server.")
            return "Top dungeon unavailable in DMs"
        rows = await self._run_db(self._get_stats_leaderboard_sync, message.guild.id, "dungeon")
        await message.reply(embed=self._build_ranked_embed(title="Top Dungeon", description="Most dungeon clears in this server.", guild=message.guild, rows=rows, page=page, value_label="clears"))
        return f"Top dungeon page {page}"

    async def topgamblers_func(self, message: discord.Message, *, page: int = 1) -> str:
        if message.guild is None:
            await message.reply("Gambler leaderboard is only available inside a server.")
            return "Top gamblers unavailable in DMs"
        rows = await self._run_db(self._get_stats_leaderboard_sync, message.guild.id, "gamblers")
        await message.reply(embed=self._build_ranked_embed(title="Top Gamblers", description="Most recorded casino plays in this server.", guild=message.guild, rows=rows, page=page, value_label="plays"))
        return f"Top gamblers page {page}"

    async def topwins_func(self, message: discord.Message, *, page: int = 1) -> str:
        if message.guild is None:
            await message.reply("Wins leaderboard is only available inside a server.")
            return "Top wins unavailable in DMs"
        rows = await self._run_db(self._get_stats_leaderboard_sync, message.guild.id, "wins")
        await message.reply(embed=self._build_ranked_embed(title="Top Wins", description="Most tracked wins across minigames and PvP.", guild=message.guild, rows=rows, page=page, value_label="wins"))
        return f"Top wins page {page}"

    async def toplosses_func(self, message: discord.Message, *, page: int = 1) -> str:
        if message.guild is None:
            await message.reply("Loss leaderboard is only available inside a server.")
            return "Top losses unavailable in DMs"
        rows = await self._run_db(self._get_stats_leaderboard_sync, message.guild.id, "losses")
        await message.reply(embed=self._build_ranked_embed(title="Top Losses", description="Most tracked losses across risk systems.", guild=message.guild, rows=rows, page=page, value_label="losses"))
        return f"Top losses page {page}"

    def _build_marriage_embed(self, *, title: str, description: str, relationship: Optional[dict[str, Any]]) -> discord.Embed:
        embed = discord.Embed(title="Cadis Etrama Di Raizel", description=description, color=EMBED_COLOR)
        embed.set_author(name=title)
        if relationship:
            married_at = dt.datetime.fromisoformat(str(relationship["married_at"]))
            days_married = max(0, (_utcnow() - married_at).days)
            embed.add_field(name="Spouse", value=str(relationship["spouse_name"]), inline=True)
            embed.add_field(name="Love", value=str(int(relationship["love_score"])), inline=True)
            embed.add_field(name="Days Married", value=str(days_married), inline=True)
            embed.add_field(name="Married At", value=discord.utils.format_dt(married_at, "F"), inline=False)
        return embed

    async def propose_func(self, message: discord.Message, *, target_user: Optional[discord.abc.User]) -> str:
        if message.guild is None:
            await message.reply("Marriage proposals are only available inside a server.")
            return "Marriage unavailable in DMs"
        if target_user is None:
            await message.reply("Use `propose @user` or `marry @user`.")
            return "Marriage target missing"
        result = await self._run_db(
            self._propose_marriage_sync,
            message.guild.id,
            message.author.id,
            _display_name(message.author),
            target_user.id,
            _display_name(target_user),
        )
        if result["status"] == "self":
            await message.reply("You cannot propose to yourself.")
            return "Marriage self blocked"
        if result["status"] == "proposer_married":
            await message.reply("You are already married in this server.")
            return "Marriage proposer married"
        if result["status"] == "target_married":
            await message.reply(f"{_display_name(target_user)} is already married in this server.")
            return "Marriage target married"
        if result["status"] == "outgoing_exists":
            await message.reply("You already have a pending proposal in this server.")
            return "Marriage outgoing exists"
        if result["status"] == "target_pending":
            await message.reply(f"{_display_name(target_user)} already has a pending proposal.")
            return "Marriage target pending"
        if result["status"] == "duplicate":
            await message.reply(f"You already proposed to **{_display_name(target_user)}**.")
            return "Marriage duplicate"
        await message.reply(f"Proposal sent to **{_display_name(target_user)}**.\nThey can answer with `accept` or `decline`.")
        return "Marriage proposal created"

    async def marry_func(self, message: discord.Message, *, target_user: Optional[discord.abc.User]) -> str:
        return await self.propose_func(message, target_user=target_user)

    async def accept_marriage_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Marriage proposals are only available inside a server.")
            return "Marriage unavailable in DMs"
        result = await self._run_db(self._accept_marriage_sync, message.guild.id, message.author.id, _display_name(message.author))
        if result["status"] == "missing":
            await message.reply("You do not have a pending proposal to accept.")
            return "Marriage accept missing"
        if result["status"] in {"target_married", "proposer_married"}:
            await message.reply("That proposal is no longer valid because one side is already married.")
            return "Marriage accept invalid"
        married_at = dt.datetime.fromisoformat(result["married_at"])
        await message.reply(
            f"**{_display_name(message.author)}** and **{result['proposer_name']}** are now married.\n"
            f"Married at: {discord.utils.format_dt(married_at, 'F')}"
        )
        return "Marriage accepted"

    async def decline_marriage_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Marriage proposals are only available inside a server.")
            return "Marriage unavailable in DMs"
        result = await self._run_db(self._decline_marriage_sync, message.guild.id, message.author.id)
        if result["status"] != "success":
            await message.reply("You do not have a pending proposal to decline.")
            return "Marriage decline missing"
        await message.reply(f"You declined the proposal from **{result['proposer_name']}**.")
        return "Marriage declined"

    async def divorce_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Divorce is only available inside a server.")
            return "Divorce unavailable in DMs"
        result = await self._run_db(self._divorce_sync, message.guild.id, message.author.id)
        if result["status"] != "success":
            await message.reply("You are not married in this server.")
            return "Divorce missing"
        await message.reply(f"Your marriage with **{result['spouse_name']}** has been dissolved.")
        return "Divorce complete"

    async def spouse_func(self, message: discord.Message, *, target_user: Optional[discord.abc.User] = None) -> str:
        if message.guild is None:
            await message.reply("Marriage status is only available inside a server.")
            return "Spouse unavailable in DMs"
        target = target_user or message.author
        status = await self._run_db(self._get_marriage_status_sync, message.guild.id, target.id)
        relationship = status.get("relationship")
        if relationship is None:
            await message.reply(f"**{_display_name(target)}** is not married in this server.")
            return "Spouse empty"
        await message.reply(embed=self._build_marriage_embed(title="Spouse", description=f"Relationship status for **{_display_name(target)}**.", relationship=relationship))
        return "Spouse shown"

    async def marriage_func(self, message: discord.Message, *, target_user: Optional[discord.abc.User] = None) -> str:
        return await self.spouse_func(message, target_user=target_user)

    async def marriageprofile_func(self, message: discord.Message, *, target_user: Optional[discord.abc.User] = None) -> str:
        return await self.spouse_func(message, target_user=target_user)

    async def love_func(self, message: discord.Message) -> str:
        if message.guild is None:
            await message.reply("Love status is only available inside a server.")
            return "Love unavailable in DMs"
        status = await self._run_db(self._get_marriage_status_sync, message.guild.id, message.author.id)
        relationship = status.get("relationship")
        if relationship is None:
            await message.reply("You are not married in this server.")
            return "Love empty"
        married_at = dt.datetime.fromisoformat(str(relationship["married_at"]))
        days_married = max(0, (_utcnow() - married_at).days)
        await message.reply(
            f"Love score: **{int(relationship['love_score'])}**\n"
            f"Spouse: **{relationship['spouse_name']}**\n"
            f"Days together: **{days_married}**"
        )
        return "Love shown"

    async def richest_func(self, message: discord.Message, *, page: int = 1) -> str:
        if message.guild is None:
            await message.reply("Richest leaderboard is only available inside a server.")
            return "Richest unavailable in DMs"
        rows = await self._run_db(self._get_richest_sync, message.guild.id)
        if not rows:
            await message.reply("No economy profiles have been created yet.")
            return "Richest empty"
        total_pages = max(1, (len(rows) + ECONOMY_LEADERBOARD_PAGE_SIZE - 1) // ECONOMY_LEADERBOARD_PAGE_SIZE)
        safe_page = max(1, min(page, total_pages))
        start_index = (safe_page - 1) * ECONOMY_LEADERBOARD_PAGE_SIZE
        page_rows = rows[start_index:start_index + ECONOMY_LEADERBOARD_PAGE_SIZE]
        lines = []
        for offset, row in enumerate(page_rows, start=start_index + 1):
            member = message.guild.get_member(int(row["user_id"]))
            name = _display_name(member) if member else (row.get("last_known_name") or f"User {row['user_id']}")
            lines.append(f"`{offset}.` {name} - {int(row['wallet'])} coins")
        embed = discord.Embed(title="Cadis Etrama Di Raizel", description="\n".join(lines), color=EMBED_COLOR)
        embed.set_author(name="Richest Users")
        embed.set_footer(text=f"Page {safe_page}/{total_pages}")
        await message.reply(embed=embed)
        return f"Richest page {safe_page}"

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        await self._award_xp(message)
        await self._record_message_activity(message)
        if await self._process_active_trivia_message(message):
            return
        await self._process_active_text_game_message(message)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Community(bot))
