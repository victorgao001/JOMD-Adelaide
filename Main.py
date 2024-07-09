import os
from discord.ext import commands
from pathlib import Path
import discord
from utils.db import session, Problem as Problem_DB
from utils.query import Query
import asyncio
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    load_dotenv()
    BOT_TOKEN = os.getenv('BOT_TOKEN') 

    if not BOT_TOKEN:
        logger.critical('Missing bot token')
        return

    intents = discord.Intents.default()  # All but the two privileged ones
    intents.members = True  # Subscribe to the Members intent

    pref = '+'
    bot = commands.Bot(command_prefix=commands.when_mentioned_or(pref),
                       intents=intents)

    cogs = [file.stem for file in Path('cogs').glob('*.py')]
    for extension in cogs:
        bot.load_extension(f'cogs.{extension}')
    logger.debug('Cogs loaded: %s', ', '.join(bot.cogs))

    def no_dm_check(ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage('Private messages not permitted.')
        return True

    # Get preliminary data
    if session.query(Problem_DB).count() == 0:
        q = Query()
        loop = asyncio.get_event_loop()
        loop.run_until_complete(q.get_problems())

    # Restrict bot usage to inside guild channels only.
    bot.add_check(no_dm_check)

    bot.run(BOT_TOKEN)


if __name__ == '__main__':
    main()
