from __future__ import annotations

import logging

import discord
from discord.ext import commands

from cogs.ai_cog import RaizelChatCog
from cogs.community_cog import Community
from cogs.music_cog import Music
from config import DISCORD_BOT_TOKEN, DISCORD_STATUS_MESSAGE, INTENTS


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


class RaizelBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix="!",
            intents=INTENTS,
            help_command=None,
        )

    async def setup_hook(self) -> None:
        await self.add_cog(Music(self))
        await self.add_cog(Community(self))
        await self.add_cog(RaizelChatCog(self))

        try:
            await self.tree.sync()
        except Exception as e:
            logging.exception("Slash command sync failed: %s", e)

    async def on_ready(self) -> None:
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name=DISCORD_STATUS_MESSAGE,
            )
        )
        logging.info("Logged in as %s (%s)", self.user, self.user.id)

    async def on_command_error(
        self,
        ctx: commands.Context,
        error: Exception,
    ) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        logging.exception("Command error", exc_info=error)


bot = RaizelBot()


def main() -> None:
    bot.run(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    try:
        import uvloop

        uvloop.install()
    except ImportError:
        pass

    main()
