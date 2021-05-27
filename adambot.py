import time

from discord.ext.commands.core import command
start_time = time.time()
import discord
from discord.ext.commands import Bot, when_mentioned_or
from discord.utils import get
import asyncio
import time
import os
from datetime import datetime, timedelta
from csv import reader
import asyncpg
import cogs.utils as utils
from cogs.utils import EmojiEnum, Todo
import pytz
from tzlocal import get_localzone
import argparse
import sys

def get_credentials(filename):
    """Command that checks if a credentials file is available. If it is it puts the vars into environ and returns True, else returns False"""
    try:
        with open(filename) as f:
            for credential in reader(f):
                os.environ[credential[0]] = credential[1]
        return True
    except FileNotFoundError:
        return False

class AdamBot(Bot):
    @classmethod # Does not depend on self - can be called as AdamBot._determine_prefix
    async def _determine_prefix(cls, bot, message):
        """Procedure that determines the prefix for a guild. This determines the prefix when a global one is not being used"""
        guild_prefix = bot.configs[message.guild.id]["prefix"]
        return when_mentioned_or(guild_prefix)(bot, message)

    def __init__(self, local, cogs, start_time, command_prefix=None, *args, **kwargs):
        if command_prefix is None:
            # Respond to guild specific pings, and mentions
            kwargs["command_prefix"] = AdamBot._determine_prefix
        else:
            # Respond to the global prefix, and mentions
            kwargs["command_prefix"] = when_mentioned_or(command_prefix)
        
        super().__init__(*args, **kwargs)
        self.__dict__.update(utils.__dict__)

        self.configs = {} # Used to store configuration for guilds
        self.flag_handler = self.flags()
        # Hopefully can eventually move these out to some sort of config system
        self.flag_handler.set_flag("time", {"flag": "t", "post_parse_handler": self.flag_methods.str_time_to_seconds})
        self.flag_handler.set_flag("reason", {"flag": "r"})
        self.token = kwargs.get("token", None)
        self.connections = kwargs.get("connections", 10) # Max DB pool connections
        self.online = True
        self.COGS = cogs
        self.LOCAL_HOST = local
        self.DB = os.environ.get('DATABASE_URL')
        self.pages = []  # List of active pages that can be used
        self.last_active = {}  # easiest to put here for now, may move to a cog later
        self.timezone = get_localzone()
        #self.timezone = pytz.timezone(
        #    'UTC')  # change as required, perhaps have some config for it? also perhaps detect from sys
        self.display_timezone = pytz.timezone('Europe/London')
        self.ts_format = '%A %d/%m/%Y %H:%M:%S'
        self.start_time = start_time
        self._init_time = time.time()
        print(f"BOT INITIALISED {self._init_time - start_time} seconds")
        self.start_up()

    async def close(self, ctx=None):  # ctx = None because this is also called upon CTRL+C in command line
        """Procedure that closes down AdamBot, using the standard client.close() command, as well as some database handling methods."""
        self.online = False  # This is set to false to prevent DB things going on in the background once bot closed
        user = f"{self.user.mention} " if self.user else "" 
        p_s = f"Beginning process of shutting {user}down. DB pool shutting down..."
        (await ctx.send(p_s), print(p_s)) if ctx else print(p_s)
        if hasattr(self, "pool"):
            self.pool.terminate()  # TODO: Make this more graceful
        c_s = "Closing connection to Discord..."
        (await ctx.send(c_s), print(c_s)) if ctx else print(c_s)
        try:
            await self.change_presence(status=discord.Status.offline)
        except AttributeError:
            pass  # hasattr returns true but then you get yelled at if you use it
        await super().close()
        time.sleep(1)  # stops bs RuntimeError spam at the end
        print(f"Bot closed after {time.time() - self.start_time} seconds")

    def start_up(self):
        """Command that starts AdamBot, is run in AdamBot.__init__"""
        print("Loading cogs...")
        self.load_cogs()
        self.cog_load = time.time()
        print(f"Loaded all cogs in {self.cog_load - self._init_time} seconds ({self.cog_load - self.start_time} seconds total)")
        print("Creating DB pool...")
        self.loop.create_task(self.execute_todos())
        self.pool: asyncpg.pool.Pool = self.loop.run_until_complete(asyncpg.create_pool(self.DB + "?sslmode=require", max_size=self.connections))
        # Moved to here as it makes more sense to not load everything then tell the user they did an oopsies
        print(f'Bot fully setup!\nDB took {time.time() - self.cog_load} seconds to connect to ({time.time() - self.start_time} seconds total)')
        token = os.environ.get('TOKEN') if not self.token else self.token
        print("Logging into Discord...")
        try:
            self.run(token)
        except Exception as e:
            print("Something went wrong handling the token!")
            print(f"The error was {type(e).__name__}: {e}")
            # overridden close cleans this up neatly

    def load_cogs(self):
        """Procedure that loads all the cogs, listed in `self.COGS`"""
        for cog in self.COGS:
            if cog == "trivia" and self.LOCAL_HOST:  # Don't load trivia if running locally
                continue
            self.load_extension(f'cogs.{cog}')
            print(f"Loaded: {cog}")

    def correct_time(self, conv_time=None, timezone_="system"):
        if not conv_time:
            conv_time = datetime.now()
        if timezone_ == "system":
            tz_obj = self.timezone
        else:
            tz_obj = pytz.timezone(timezone_)
        return tz_obj.localize(conv_time).astimezone(self.display_timezone)

    async def on_ready(self):
        self.login_time = time.time()
        print(f'Bot logged into Discord ({self.login_time - self.start_time} seconds total)')
        await self.change_presence(activity=discord.Game(name=f'Type `help` for help'),
                                   status=discord.Status.online)
        await self.add_all_guild_configs()

    async def add_all_guild_configs(self):
        for guild in self.guilds:
            await self.add_config(guild.id)

    async def on_guild_join(self, guild):  # if a bot joins a guild whilst offline it should be picked up in add_all_guild_configs when it's next started
        await self.add_config(guild.id)
   
    async def on_message(self, message):
        """Event that has checks that stop bots from executing commands"""
        if type(message.channel) == discord.DMChannel or message.author.bot:
            return
        if message.guild.id not in self.last_active:
            self.last_active[message.guild.id] = []  # create the dict key for that guild if it doesn't exist
        last_active_list = self.last_active[message.guild.id]
        if message.author in last_active_list:
            last_active_list.remove(message.author)
        last_active_list.insert(0, message.author)
        await self.process_commands(message)

    async def on_reaction_add(self, reaction, user):
        """Subroutine used to control EmbedPages stored within self.pages"""
        if not user.bot:
            for page in self.pages:
                if reaction.message == page.message and user == page.initiator:
                    # Do stuff
                    if reaction.emoji == EmojiEnum.LEFT_ARROW:
                        await page.previous_page()
                    elif reaction.emoji == EmojiEnum.RIGHT_ARROW:
                        await page.next_page()
                    elif reaction.emoji == EmojiEnum.CLOSE:
                        await reaction.message.delete()
                    elif reaction.emoji == EmojiEnum.MIN_BUTTON:
                        await page.first_page()
                    elif reaction.emoji == EmojiEnum.MAX_BUTTON:
                        await page.last_page()

                    if reaction.emoji != EmojiEnum.CLOSE: # Fixes errors that occur when deleting the embed above
                        await reaction.message.remove_reaction(reaction.emoji, user)
                    break

    async def on_message_delete(self, message):
        """Event that ensures that memory is freed up once a message containing an embed page is deleted."""
        for page in self.pages:
            if message == page.message:
                del page
                break

    async def execute_todos(self):
        """The loop that continually checks the DB for todos.
            The todo table looks like:
	            id SERIAL PRIMARY KEY,
	            todo_id int,
	            todo_time timestamptz,
	            member_id bigint
                member_id may not always be a member ID, and can sometimes be a FK to demographic_roles.id"""

        await self.wait_until_ready()
        while self.online:
            try:
                async with self.pool.acquire() as connection:
                    todos = await connection.fetch('SELECT * FROM todo WHERE todo_time <= now()')
                    for todo in todos:
                        try:
                            if todo[1] == Todo.UNMUTE:
                                member = get(self.get_all_members(), id=todo[3])
                                await member.remove_roles(get(member.guild.roles, name='Muted'), reason='Auto unmuted')
                                await connection.execute('DELETE FROM todo WHERE id = ($1)', todo[0])

                            elif todo[1] == Todo.UNBAN:
                                user = await self.fetch_user(todo[3])
                                guild = self.get_guild(445194262947037185)
                                await guild.unban(user, reason='Auto unbanned')
                                await connection.execute('DELETE FROM todo WHERE id = ($1)', todo[0])

                            elif todo[1] == Todo.DEMOGRAPHIC_SAMPLE or todo[1] == Todo.ONE_OFF_DEMOGRAPHIC_SAMPLE:
                                demographic_role_id = todo[3]
                                results = await connection.fetch(
                                    "SELECT role_id, guild_id, sample_rate FROM demographic_roles WHERE id = $1",
                                    demographic_role_id)
                                guild = self.get_guild(results[0][1])
                                role_id = results[0][0]
                                sample_rate = results[0][2]
                                n = len([x for x in guild.members if role_id in [y.id for y in x.roles]])
                                await connection.execute(
                                    "INSERT INTO demographic_samples (n, role_reference) VALUES ($1, $2)", n,
                                    demographic_role_id)
                                await connection.execute('DELETE FROM todo WHERE id = ($1)', todo[0])

                                if todo[1] == Todo.DEMOGRAPHIC_SAMPLE:  # IF NOT A ONE OFF SAMPLE, PERFORM IT AGAIN
                                    await connection.execute(
                                        "INSERT INTO todo (todo_id, todo_time, member_id) VALUES ($1, $2, $3)",
                                        Todo.DEMOGRAPHIC_SAMPLE, datetime.utcnow() + timedelta(days=sample_rate),
                                        demographic_role_id)

                        except Exception as e:
                            print(f'{type(e).__name__}: {e}')
                            await connection.execute('DELETE FROM todo WHERE id = ($1)', todo[0])

                    reminds = await connection.fetch('SELECT * FROM remind WHERE reminder_time <= now()')
                    for remind in reminds:
                        try:
                            member = get(self.get_all_members(), id=remind[1])
                            message = f'You told me to remind you about this:\n{remind[3]}'
                            try:
                                await member.send(message)
                            except discord.Forbidden:
                                channel = self.get_channel(remind[5]) # Get the channel it was invoked from
                                await channel.send(member.mention + ", " + message)
                            finally:
                                await connection.execute('DELETE FROM remind WHERE id = ($1)', remind[0])
                        except Exception as e:
                            print(f'REMIND: {type(e).__name__}: {e}')
            except (OSError, asyncpg.exceptions.ConnectionDoesNotExistError):
                await asyncio.sleep(5)  # workaround for task crashing when connection temporarily drops with db

            await asyncio.sleep(5)


    # General configuration workflow:
    # 1) Call bot.add_config(guild.id) which makes sure there is that guild's config stuff in bot.configs dict
    # 2) Make any edits directly to bot.configs[guild.id]
    # 3) Call bot.propagate_config(guild.id) which propagates any edits to the DB

    async def add_config(self, guild_id):
        """
        Method that gets the configuraton for a guild and puts it into self.configs dictionary (with the guild ID as the key). The data
        is stored in the `config` table. If no configuration is found, a new record is made and a blank configuration dict.
        """
        if guild_id not in self.configs: # This check (to see if a DB call is needed) is okay because any updates made will be directly made to self.configs (before DB propagation) TODO: Perhaps limit number of items in this
            async with self.pool.acquire() as connection:
                record = await connection.fetchrow("SELECT * FROM config WHERE guild_id = $1;", guild_id)
                if not record:
                    await connection.execute("INSERT INTO config (guild_id) VALUES ($1);", guild_id)
                    record = await connection.fetchrow("SELECT * FROM config WHERE guild_id = $1;", guild_id) # Fetch configuration record

            keys = list(record.keys())[1:]
            values = list(record.values())[1:] # Include all keys and values apart from the first one (guild_id)
            self.configs[guild_id] = dict(zip(keys, values)) # Turns the record into a dictionary (column name = key, value = value)

    async def propagate_config(self, guild_id):
        """
        Method that sends the config data stored in self.configs and propagates them to the DB.
        """
        data = self.configs[guild_id]
        length = len(data.keys())
        
        # Make SQL
        sql_part = ""
        keys = list(data) # List of the keys (current column names in the database)
        for i in range(length):
            sql_part += f"{keys[i]} = (${i + 1})" # For each key, add "{nth key_name} = $n+1"
            if i != length - 1:
                sql_part += ", " # If not the last element, add a ", "

        sql = f"UPDATE config SET {sql_part} WHERE guild_id = {guild_id};"
        async with self.pool.acquire() as connection:
            await connection.execute(sql, *data.values())

    async def is_staff(self, ctx):
        """
        Method that checks if a user is staff in their guild or not
        """
        staff_role_id = self.configs[ctx.guild.id]["staff_role"]
        return staff_role_id in [y.id for y in ctx.author.roles]

if __name__ == "__main__":
    local_host = get_credentials('credentials.csv')

    intents = discord.Intents.default()
    intents.members = True
    intents.presences = True
    intents.reactions = True
    intents.typing = True
    intents.dm_messages = True
    intents.guilds = True

    parser = argparse.ArgumentParser()
    args = sys.argv[1:]
    # todo: make this more customisable
    
    parser.add_argument("-p", "--prefix", nargs="?", default=None)
    parser.add_argument("-t", "--token", nargs="?", default=None)  # can change token on the fly/keep env clean
    parser.add_argument("-c", "--connections", nargs="?", default=10) # DB pool max_size (how many concurrent connections the pool can have)
    args = parser.parse_args()
    cog_names = ['member',
                 'moderation',
                 'questionotd',
                 'waitingroom',
                 'support',
                 'reputation',
                 'trivia',
                 'demographics',
                 'spotify',
                 'warnings',
                 'logging',
                 'eval',
                 'config'] # Make this dynamic?
    bot = AdamBot(local_host, cog_names, start_time, token=args.token, connections=args.connections, intents=intents, command_prefix=args.prefix) # If the prefix given == None use the guild ones, otherwise use the given prefix
    # bot.remove_command("help")