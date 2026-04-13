# My-Advanced-Bot-Project
Highly Advanced Discord music bot with filters, real-time controls, history tracking, and interactive systems


#  Raizel — Advanced Discord System Bot

 Raizel is a system-driven Discord bot that combines a full music player, advanced audio filters, interactive help UI, persistent economy features, PvP and dungeon mechanics, and multiple session-based guessing games.

This project is built around behavior, structure, and interaction design rather than just adding isolated commands. The goal is to make the bot feel like a complete interactive Discord system instead of a simple utility script.

## Features

### Music System
The bot includes a full music playback system with real-time control.

It supports:
- YouTube playback from links or search queries
- queue management
- pause, resume, skip, stop
- shuffle and loop
- forward and backward seeking
- now playing support
- per-user history tracking

### Audio Filters
The music system includes a wide filter layer for sound customization.

Available filter support includes:
- nightcore
- bassboost
- slow
- reverb
- echo
- karaoke
- speed and pitch control
- lowpass and highpass
- equalizer
- compressor
- 8D
- vaporwave
- lofi

### Interactive Help Menu
The bot uses a button-based interactive help interface instead of a single command dump.

Help categories include:
- Playback
- Filters
- History
- Minigame
- Utility / QoL
- Stats / Analytics
- Marriage
- Profile / XP
- Avatar Tools
- Text Tools
- Moderation
- Smart Help

Focused help is also supported with topic-based usage such as:
- `help dungeon`
- `help slots`
- `help drawgame`
- `help marriage`

### Minigame / Economy System
The bot contains a persistent economy and gameplay layer.

Core economy features include:
- wallet and balance tracking
- daily rewards
- quests and missions
- achievements and badges
- income and passive property systems
- gifting coins to other users
- money leaderboards

### Jobs and Earning Actions
The economy includes jobs and multiple earning methods.

Supported earning/job features include:
- job selection
- job upgrading
- profession progression
- work
- beg
- quiz
- fish
- hunt
- search
- mine
- deliver
- scavenge
- freelance
- craft
- repair
- patrol
- quick earn panel

### Casino / Risk Systems
The bot includes live-risk and gambling systems.

Available systems include:
- gamble / bet
- blackjack
- player-vs-player blackjack
- coinflip versus another player
- slot machine
- crash
- guess-based betting

### PvP and Dungeon Systems
The bot includes combat-style competitive and progression systems.

Available systems include:
- duel
- dungeon run
- PvE dungeon mode
- steal
- rob
- heist

Dungeon features include:
- session-based runs
- fighter selection
- companions
- purchasable extra lives
- leave cashout logic
- Ancient Dungeon continuation after level 10
- fixed elite bosses for the Ancient Dungeon
- persistent reward logic

### Guessing Games
The bot includes multiple channel-based guessing games using normal chat messages as input.

Available guessing games:
- drawgame
- hangman
- wordchain
- trivia

These games are channel-scoped and only one of them can run in a channel at a time, so message-based guessing does not collide across systems.

### Shop, Inventory, and Pets
The bot includes a full item economy layer.

Available features include:
- shop
- market
- shopview
- inventory
- item buying
- item selling
- sellall
- item usage
- item effects
- pets integrated into the main market

Items can provide actual passive or active effects such as:
- income bonuses
- XP bonuses
- progression bonuses
- system-specific boosts

The sell system returns 70% of the original purchase value.

### Profile, Stats, and Analytics
The bot tracks player progress and statistics across systems.

This includes:
- profile and XP systems
- rank information
- personal statistics
- dungeon stats
- casino stats
- job stats
- usage-based analytics
- server leaderboards

### Utility / QoL Tools
The bot also includes quality-of-life features and local utility tools.

These include:
- calculator
- notes
- reminders and timers
- uptime and ping
- local text utilities such as rewrite-style helpers, summarize-style helpers, and focused text tools

### Marriage System
The bot includes a persistent marriage/social system with proposal, acceptance, relationship status, and related profile information.

## Command Overview

### Music
- `play <song>`
- `pause`
- `resume`
- `skip`
- `stop`
- `queue`
- `shuffle`
- `loop`
- `seek <time>`

### Filters
- `nightcore`
- `bassboost`
- `slow`
- `reverb`
- `echo`
- `karaoke`
- `8d`
- `vaporwave`
- `lofi`
- `filter off`

### History
- `history @user`
- `history me`
- `mostplayed @user`

### Economy
- `balance`
- `bal`
- `wallet`
- `daily`
- `quests`
- `missions`
- `achievements`
- `badges`
- `income`
- `collect`
- `property`
- `gift @user <amount>`
- `richest`
- `topmoney`

### Jobs
- `jobs`
- `choosejob <name>`
- `job choose <name>`
- `myjob`
- `job upgrade`
- `level job`

### Earning Commands
- `work`
- `beg`
- `quiz`
- `answer <number>`
- `fish`
- `hunt`
- `search`
- `mine`
- `deliver`
- `scavenge`
- `freelance`
- `craft`
- `repair`
- `patrol`
- `earn`
- `quickearn`
- `workpanel`

### Casino
- `gamble <amount>`
- `bet <amount>`
- `blackjack <amount>`
- `bj <amount>`
- `bj @user <amount>`
- `coinflip @user <amount>`
- `cf @user <amount>`
- `slots <amount>`
- `slot <amount>`
- `spin <amount>`
- `crash <amount>`
- `guess <amount>`

### PvP / Dungeon
- `duel @user <amount>`
- `dungeon <amount>`
- `dungeon run <amount>`
- `pve <amount>`
- `steal @user`
- `rob @user`
- `heist @user`

### Guessing Games
- `drawgame`
- `hint`
- `hangman`
- `wordchain`
- `chainword`
- `trivia`
- `reveal`
- `enddrawgame`

### Shop / Inventory / Pets
- `shop`
- `market`
- `shopview`
- `inventory`
- `buy <item>`
- `sell <item>`
- `sellall`
- `use <item>`
- `mypet`
- `equippet <name>`
- `feedpet`
- `petinfo`

### Help
- `help`
- `help dungeon`
- `help slots`
- `help drawgame`
- `help marriage`
- `help stats`

## Tech Stack

This project is built primarily with:
- Python
- discord.py
- FFmpeg
- yt-dlp
- SQLite

## Project Philosophy

This bot is built with a system-first mindset.

The focus is on:
- interaction flow
- session behavior
- feature cohesion
- persistent progression
- layered mechanics
- expandability

A lot of the design choices were made to make the bot feel alive, interactive, and complete rather than just technically functional.

## Notes

- Guessing games are session-based and channel-scoped.
- Only one message-driven guessing game runs in a channel at a time.
- The economy system is persistent.
- Shop items can provide actual effects.
- The interactive help menu is the recommended way to explore the bot.
- Topic-based help can be used for focused guidance on larger systems.

## Author

Fırat Akyol

## Final Note

The coding and implementation side of this project is AI-assisted, but the ideas, structure, mechanics, systems, and design decisions behind it are fully my own.

This project reflects how I think: starting from behavior and structure first, then building the implementation around it with attention to small details, system interaction, and long-term expandability.
