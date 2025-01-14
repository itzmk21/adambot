from typing import Optional

import discord
from discord.ext import commands
import asyncio
import re
from emoji import get_emoji_regexp
from libs.misc.decorators import is_staff
from libs.misc.utils import get_user_avatar_url, get_guild_icon_url


class Starboard:
    class Entry:
        @classmethod
        async def make_entry(cls, record: dict, bot: discord.Client) -> None:
            super().__init__(cls)
            self = Starboard.Entry()
            self.bot = bot
            self.bot_message_id = record["bot_message_id"]
            self.message_id = record["message_id"]
            self.channel_id = record["starboard_channel_id"]  # Channel ID of bot message
            try:
                self.channel = bot.get_channel(self.channel_id)
                self.bot_message = await self.channel.fetch_message(self.bot_message_id)
            except discord.NotFound:
                self.channel = self.bot_message = None
            return self

        async def update_bot_message(self, new_msg: discord.Message) -> None:
            self.bot_message = new_msg
            self.bot_message_id = new_msg.id
            async with self.bot.pool.acquire() as connection:
                await connection.execute("UPDATE starboard_entry SET bot_message_id = $1 WHERE starboard_channel_id = $2 AND message_id = $3;", self.bot_message_id, self.channel_id, self.message_id)

    def __init__(self, record: dict, bot: discord.Client) -> None:
        self.bot = bot
        self.channel = self.bot.get_channel(record["channel_id"])
        self.guild = self.channel.guild
        self.emoji = record["emoji"]
        self.emoji_id = record["emoji_id"]
        self.minimum_stars = record["minimum_stars"]
        self.embed_colour = record["embed_colour"]
        self.allow_self_star = record["allow_self_star"]
        self.record = record
        self.entries = []

    @classmethod
    async def make_starboards(cls, records: list, entries: list, bot: discord.Client) -> dict:
        """
        Makes a dict of {channel_id: Starboard} for the given starboards and entries from the DB
        """

        starboards = {}
        for record in records:
            obj = Starboard(record, bot)
            starboards[obj.channel.id] = obj  # Make empty starboard
        for entry in entries:
            obj = await Starboard.Entry.make_entry(entry, bot)
            starboards[entry["starboard_channel_id"]].entries.append(obj)  # Add all entries to their respective starboard
        return starboards

    def get_record(self) -> dict:
        """
        Function that returns the record in the database for the starboard
        """
        return self.record

    def get_string_emoji(self) -> str:
        """
        Returns the unicode emoji or a discord formatted custom emoji as a string
        """

        custom_emoji = self.bot.get_emoji(self.emoji_id) if self.emoji_id else None
        emoji = self.emoji if self.emoji else f"<:{custom_emoji.name}:{custom_emoji.id}>"
        return emoji

    async def update(self, new_starboard_data: dict) -> None:
        """
        Update a starboard to its current given state
        """

        async with self.bot.pool.acquire() as connection:
            await connection.execute("UPDATE starboard SET emoji = $1, emoji_id = $2, minimum_stars = $3, embed_colour = $4, allow_self_star = $5 WHERE channel_id = $6;", new_starboard_data["emoji"], new_starboard_data["emoji_id"], new_starboard_data["minimum_stars"], new_starboard_data["embed_colour"], new_starboard_data["allow_self_star"], self.channel.id)
        self.emoji = new_starboard_data["emoji"]
        self.emoji_id = new_starboard_data["emoji_id"]
        self.minimum_stars = new_starboard_data["minimum_stars"]
        self.embed_colour = new_starboard_data["embed_colour"]
        self.allow_self_star = new_starboard_data["allow_self_star"]

    async def try_get_entry(self, message_id: int) -> Optional[Entry]:
        """
        Returns either a starboard entry or None if it doesn't exist
        """

        for entry in self.entries:
            if entry.message_id == message_id:
                return entry
        return None

    async def create_entry(self, message_id: int, bot_message_id: int, starboard_channel_id: int, bot: discord.Client) -> None:
        """
        Creates a starboard entry for an existing starboard (adds to the DB too)
        """

        async with self.bot.pool.acquire() as connection:
            await connection.execute("INSERT INTO starboard_entry (message_id, starboard_channel_id, bot_message_id) VALUES ($1, $2, $3);", message_id, self.channel.id, bot_message_id)
        self.entries.append(await self.Entry.make_entry({
            "message_id": message_id,
            "bot_message_id": bot_message_id,
            "starboard_channel_id": starboard_channel_id
        }, bot))

    async def delete_entry(self, message_id: int) -> None:
        """
        Deletes a starboard entry from an existing starboard (removes from the DB too)
        """

        async with self.bot.pool.acquire() as connection:
            await connection.execute("DELETE FROM starboard_entry WHERE starboard_channel_id = $1 AND message_id = $2;", self.channel.id, message_id)
        indx = -1
        for i, e in enumerate(self.entries):  # TODO: What happens if found_entry is still None after search i.e. entry not found
            if e.message_id == message_id:
                indx = i
                break
        self.entries.pop(indx)


class StarboardCog(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.starboards = {}  # Links channel_id -> Starboard

    # TODO: Some help commands when args are missing would be nice

    # --- Starboard embed ---
    async def make_starboard_embed(self, message: discord.Message, stars: int, emoji: discord.Emoji, color: discord.Color) -> discord.Embed:
        """
        Turns the message into an Embed that can be sent in the starboard channel
        """

        embed = discord.Embed(title=f"{stars} {emoji} (in #{message.channel.name})", color=color if color else self.bot.GOLDEN_YELLOW, description=message.content)
        embed.set_author(name=message.author.display_name, icon_url=get_user_avatar_url(message.author, mode=1)[0])
        if message.embeds:
            embedded_data = message.embeds[0]
            if embedded_data.type == "image" and not self.is_url_spoiler(message.content, embedded_data.url):
                embed.set_image(url=embedded_data.url)
            else:
                embed.add_field(name="Message is an embed", value="Press the message link to view", inline=False)

        if message.reference:
            embed.add_field(name="In response to...", value=f"{message.reference.resolved.author.display_name}#{message.reference.resolved.author.discriminator}", inline=False)

        if message.attachments:
            attatched = message.attachments[0]
            is_spoiler = attatched.is_spoiler()
            if not is_spoiler and attatched.url.lower().endswith(("png", "jpeg", "jpg", "gif", "webp")):
                embed.set_image(url=attatched.url)
            elif is_spoiler:
                embed.add_field(name="Attachment", value=f"||[{attatched.filename}]({attatched.url})||", inline=False)
            else:
                embed.add_field(name="Attachment", value=f"[{attatched.filename}]({attatched.url})", inline=False)

        embed.add_field(name="Message link", value=f"[Click me!]({message.jump_url})")
        embed.set_footer(text=self.bot.correct_time().strftime("%H:%M on %m/%d/%Y"))
        return embed

    # --- Utility functions ---

    async def _get_starboards(self, guild_id: int) -> list:
        """
        Returns all a list of Starboard for a given guild
        """

        results = []
        for starboard in self.starboards.values():
            if starboard.guild.id == guild_id:
                results.append(starboard)
        return results

    async def _try_get_starboard(self, channel_id: int) -> Optional[Starboard]:
        """
        Return the starboard for the given text channel or None if it doesn't exist
        """

        return self.starboards.get(channel_id, None)

    async def _create_starboard(self, channel: discord.TextChannel | discord.Thread, is_custom_emoji: bool, emoji: discord.Emoji | str, minimum_stars: int, embed_colour: str = None, allow_self_star: bool = True) -> None:
        """
        Creates a starboard in the database and add it to `self.starboards`
        """

        async with self.bot.pool.acquire() as connection:
            if is_custom_emoji:
                await connection.execute("INSERT INTO starboard (guild_id, channel_id, emoji_id, minimum_stars, embed_colour, allow_self_star) VALUES ($1, $2, $3, $4, $5, $6);", channel.guild.id, channel.id, emoji.id, minimum_stars, embed_colour, allow_self_star)  # If custom emoji, store ID in DB
            else:
                await connection.execute("INSERT INTO starboard (guild_id, channel_id, emoji, minimum_stars, embed_colour, allow_self_star) VALUES ($1, $2, $3, $4, $5, $6);", channel.guild.id, channel.id, emoji, minimum_stars, embed_colour, allow_self_star)  # If not custom emoji, store emoji in DB
        new_starboard = Starboard({
            "channel_id": channel.id,
            "guild_id": channel.guild.id,
            "emoji": None if is_custom_emoji else emoji,
            "emoji_id": None if not is_custom_emoji else emoji.id,
            "minimum_stars": minimum_stars,
            "embed_colour": embed_colour,
            "allow_self_star": allow_self_star
        })
        self.starboards[channel.id] = new_starboard

    async def _delete_starboard(self, channel: discord.TextChannel | discord.Thread) -> None:
        """
        Deletes a starboard channel and all its entries from the database
        """

        del self.starboards[channel.id]  # Remove from starboards
        async with self.bot.pool.acquire() as connection:
            await connection.execute("DELETE FROM starboard WHERE channel_id = $1;", channel.id)

    @staticmethod
    async def _is_valid_emoji(emoji: str, msg_context: commands.Context) -> list[bool, discord.Emoji | str | bool]:
        """
        Checks if a given emoji can be used. If it can be used it returns a list where the first element is True/False if its a custom emoji and second is the emoji itself or None if the emoji cannot be used.
        """

        try:
            return_emoji = await commands.EmojiConverter().convert(msg_context, emoji) or None
            custom_emoji = True
        except commands.errors.EmojiNotFound:
            # If here, emoji is either a standard emoji, or a custom one from another guild
            match = re.match(r"<(a?):([a-zA-Z0-9]{1,32}):([0-9]{15,20})>$", emoji)  # True if custom emoji (obtained from https://github.com/Rapptz/discord.py/blob/master/discord/ext/commands/converter.py)
            if not match:
                custom_emoji = False
                return_emoji = emoji if bool(get_emoji_regexp().search(emoji)) else None  # If `emoji` is an actual unicode emoji, this will set `return_emoji` to it, otherwise None
        return [custom_emoji, return_emoji]

    @staticmethod
    def _is_valid_hex_colour(string: str) -> str | bool:
        """
        Returns either a decimal denoting the colour if the colour is valid, or False if not valid
        """

        parsed_colour = string.lower().replace("#", "")
        if len(parsed_colour) != 6:
            return False
        try:
            int(parsed_colour, 16)  # Convert from base 16 into an integer for storage
            return "#" + parsed_colour.upper()  # If no errors at this point, the colour can be assumed to be valid
        except ValueError:
            return False

    async def boolean_reaction_getter(self, ctx: commands.Context, message: discord.Message, timeout: int = 300) -> bool:  # TODO: Could move this to utils if needed in the future
        """
        Method that can be used to get either a True/False from the user in a given `timeout`. Returns the answer, or None if timeout experienced
        """

        possible_responses = {
            self.bot.EmojiEnum.TRUE: True,
            self.bot.EmojiEnum.FALSE: False
        }

        def check(r: discord.Reaction, u: discord.Member | discord.User) -> bool:
            return r.emoji in possible_responses.keys() and u == ctx.author

        for emoji in possible_responses.keys():
            await message.add_reaction(emoji)
        
        try:
            reaction, user = await self.bot.wait_for("reaction_add", check=check, timeout=timeout)
            return possible_responses[reaction.emoji]
        except asyncio.TimeoutError:
            return None

    # --- Listeners ---

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload) -> None:
        await self.on_raw_reaction_event(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload) -> None:
        await self.on_raw_reaction_event(payload)
    
    async def on_raw_reaction_event(self, payload) -> None:
        try:
            message = await self.bot.get_channel(payload.channel_id).fetch_message(payload.message_id)
        except discord.NotFound:
            return

        starboards = await self._get_starboards(payload.guild_id)
        for starboard in starboards:
            if message.channel.id == starboard.channel.id:  # stops people spamming star react onto starboard embeds
                continue

            # Parse the colour if one exists
            if starboard.embed_colour:
                colour = starboard.embed_colour  # colour is now a hex code in the format "#FFFFFF"
                r = int(colour[1] + colour[2], 16)
                g = int(colour[3] + colour[4], 16)
                b = int(colour[5] + colour[6], 16)
                colour = discord.Color.from_rgb(r, g, b)
            else:
                colour = self.bot.GOLDEN_YELLOW

            if (starboard.emoji is not None and starboard.emoji == payload.emoji.name) or (starboard.emoji_id is not None and starboard.emoji_id == payload.emoji.id):  # Valid emoji
                # Get the amount of stars (we fetch this from Discord instead of having a field in starboard_entry record because new emoji's may be added when bot is offline)
                # Find the correct reaction
                stars = 0
                for r in message.reactions:
                    if (not r.is_custom_emoji() and r.emoji == payload.emoji.name) or (r.is_custom_emoji() and r.emoji.id == payload.emoji.id):
                        # This is the reaction we want to process
                        stars = r.count
                        # If the starboard has self star disabled, we need to remove a star if the author has reacted, as well as all stars from a bot
                        deducted_stars = [u.id for u in await r.users().flatten() if u.bot or (not starboard.allow_self_star and u.id == message.author.id)]  # Means that bots cannot star nor the author IF allow self star is False
                        stars -= len(deducted_stars)
                
                minimum_met = stars >= starboard.minimum_stars
                entry = await starboard.try_get_entry(payload.message_id)
                if not minimum_met:
                    if entry:
                        await starboard.delete_entry(payload.message_id)
                        if entry.bot_message:
                            await entry.bot_message.delete()
                            
                elif entry and entry.bot_message:  # If minimum met and entry
                    new_embed = await self.make_starboard_embed(message, stars, payload.emoji, colour)
                    try:
                        # Update bot message
                        await entry.bot_message.edit(embed=new_embed)
                    except discord.NotFound:
                        # Bot message deleted
                        msg = await starboard.channel.send(embed=new_embed)
                        await entry.update_bot_message(msg)
                else:
                    message = await self.bot.get_channel(payload.channel_id).fetch_message(payload.message_id)
                    # Message doesn't exist, make a new one
                    msg = await starboard.channel.send(embed=await self.make_starboard_embed(message, stars, payload.emoji, colour))
                    if not entry:
                        await starboard.create_entry(payload.message_id, msg.id, starboard.channel.id, self.bot)
                    elif entry or entry.bot_message is None:
                        await entry.update_bot_message(msg)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.TextChannel | discord.Thread) -> None:
        starboard = await self._try_get_starboard(channel.id)
        if starboard:
            await self._delete_starboard(channel)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        while not self.bot.online:
            await asyncio.sleep(1)  # Wait else DB won't be available

        async with self.bot.pool.acquire() as connection:
            starboards = await connection.fetch("SELECT * FROM starboard;")
            entries = await connection.fetch("SELECT * FROM starboard_entry;")
            self.starboards = await Starboard.make_starboards(starboards, entries, self.bot)
            
    # --- Commands ---

    @commands.group()
    async def starboard(self, ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.send(f"```{ctx.prefix}help starboard```")

    @starboard.command(aliases=["list"])
    @commands.guild_only()
    @is_staff()
    async def view(self, ctx: commands.Context) -> None:
        """
        View all of the starboards in the current guild
        """
        
        starboards = await self._get_starboards(ctx.guild.id)
        embed = self.bot.EmbedPages(
            self.bot.PageTypes.STARBOARD_LIST,
            starboards,
            f":information_source: {ctx.guild.name}'s starboards",
            self.bot.GOLDEN_YELLOW,
            self.bot,
            ctx.author,
            ctx.channel,
            thumbnail_url=get_guild_icon_url(ctx.guild),
            icon_url=get_user_avatar_url(ctx.author, mode=1)[0],
            footer=f"Requested by: {ctx.author.display_name} ({ctx.author})\n" + self.bot.correct_time().strftime(self.bot.ts_format),
        )

        await embed.set_page(1)
        await embed.send()

    @starboard.command()
    @commands.guild_only()
    @is_staff()
    async def create(self, ctx: commands.Context) -> None:
        """
        Start the set up for the creation of a starboard
        """
        
        try:
            while True:  # Get the channel
                await self.bot.DefaultEmbedResponses.question_embed(self.bot, ctx, "1. Starboard channel?", desc="Starboard setup started. To continue with the setup you need to provide me with a few things. If you want to cancel the setup type 'cancel' (there is a 60 second timeout on each question).")
                m = await self.bot.wait_for("message", timeout=60)
                if m.content.lower() == "cancel":
                    await self.bot.DefaultEmbedResponses.error_embed(self.bot, ctx, "Setup cancelled")
                    return
                context = await self.bot.get_context(m)
                try:
                    channel = await commands.TextChannelConverter().convert(context, m.content)  # If not found do not cache
                except commands.errors.ChannelNotFound:
                    try:
                        channel = await commands.ThreadConverter().convert(context, m.content)
                    except commands.errors.ThreadNotFound:
                        await self.bot.DefaultEmbedResponses.error_embed(self.bot, ctx, "Channel not found", desc="Please try again with another channel")
                        continue

                    pre_existing = await self._try_get_starboard(channel.id)
                    if pre_existing:
                        await self.bot.DefaultEmbedResponses.error_embed(self.bot, ctx, "The channel already has a starboard, please try again")
                        continue  # Jump to next loop iteration to cancel moving onto the next setup stage

                if channel:
                    break

            while True:  # Get the emoji
                await self.bot.DefaultEmbedResponses.question_embed(self.bot, ctx, "2. Emoji?")
                m = await self.bot.wait_for("message", timeout=60)
                if m.content.lower() == "cancel":
                    await self.bot.DefaultEmbedResponses.error_embed(self.bot, ctx, "Setup cancelled")
                    return
                context = await self.bot.get_context(m)
                custom_emoji, emoji = await self._is_valid_emoji(m.content, context)
                if emoji:
                    break
                else:
                    await self.bot.DefaultEmbedResponses.error_embed(self.bot, ctx, "Emoji not found", desc="Please try again with a Discord emoji")

            while True:  # Get the minimum emoji needed
                await self.bot.DefaultEmbedResponses.question_embed(self.bot, ctx, f"**3.** Minimum amount of {emoji} to get on starboard?", desc="Must be 1 or above")
                m = await self.bot.wait_for("message", timeout=60)
                if m.content.lower() == "cancel":
                    await self.bot.DefaultEmbedResponses.error_embed(self.bot, ctx, "Setup cancelled")
                    return
                minimum = int(m.content) if m.content.isdigit() and int(m.content) > 0 else None
                if minimum:
                    break
                else:
                    await self.bot.DefaultEmbedResponses.error_embed(self.bot, ctx, "Invalid minimum", desc="Please try again with a number greater than 0.")

            while True:  # Get the colour (if wanted)
                await self.bot.DefaultEmbedResponses.question_embed(self.bot, ctx, f"**4.** Hex code of the colour of embeds on the starboard?", desc="If you say 'skip' it will default to gold")
                m = await self.bot.wait_for("message", timeout=60)
                if m.content.lower() == "cancel":
                    await self.bot.DefaultEmbedResponses.error_embed(self.bot, ctx, "Setup cancelled")
                    return
                if m.content.lower() == "skip":
                    embed_colour = None
                    break
                
                embed_colour = self._is_valid_hex_colour(m.content)
                if not embed_colour:
                    await self.bot.DefaultEmbedResponses.error_embed(self.bot, ctx, "Invalid hex colour", desc="Please try again with a 6 digit hex code or type 'skip'")
                else:
                    break

            question = await self.bot.DefaultEmbedResponses.question_embed(self.bot, ctx, f"**5.** Allow people to star their own messages?", desc="React with the correct response")
            response = await self.boolean_reaction_getter(ctx, question, timeout=60)
            if response is not None:
                allow_self_star = response  # Convert to correct boolean if boolean given

            await self._create_starboard(channel, custom_emoji, emoji, minimum, embed_colour=embed_colour, allow_self_star=allow_self_star)
            await self.bot.DefaultEmbedResponses.success_embed(self.bot, ctx, "Starboard created!", desc=f"Starboard created in {channel.mention}. Messages with {minimum} or more {emoji} reactions will appear there.")

        except asyncio.TimeoutError:
            await self.bot.DefaultEmbedResponses.error_embed(self.bot, ctx, "Setup timed-out.")
    
    @starboard.command()
    @commands.guild_only()
    @is_staff()
    async def edit(self, ctx: commands.Context, channel: discord.TextChannel | discord.Thread, option: str, value: str) -> None:
        """
        Edit a starboard setup. `option` can either be "minimum", "emoji", "colour"/"color"/"embed_colour", or "self_star"
        """
        
        option = option.lower()
        starboard = await self._try_get_starboard(channel.id)
        if not starboard:
            await self.bot.DefaultEmbedResponses.error_embed(self.bot, ctx, "Starboard does not exist")
            return
        
        starboard_data = dict(starboard.get_record())
        if option == "minimum":
            if not (value.isdigit() and int(value) > 0):
                await self.bot.DefaultEmbedResponses.error_embed(self.bot, ctx, "Invalid minimum given - it must be above 0")
                return
            # At this point its okay to change data
            starboard_data["minimum_stars"] = int(value)
        
        elif option == "emoji":
            custom_emoji, emoji = await self._is_valid_emoji(value, ctx)
            if not emoji:
                await self.bot.DefaultEmbedResponses.error_embed(self.bot, ctx, "Invalid emoji given")
                return
            # At this point its okay to change data
            if custom_emoji:
                starboard_data["emoji"] = None
                starboard_data["emoji_id"] = emoji.id
            else:
                starboard_data["emoji_id"] = None
                starboard_data["emoji"] = emoji
        
        elif option in ["color", "colour", "embed_colour"]:
            new_colour = self._is_valid_hex_colour(value)
            if not new_colour:
                await self.bot.DefaultEmbedResponses.error_embed(self.bot, ctx, "Invalid hex colour", desc="Please try again with a 6 digit hex code")
                return
            starboard_data["embed_colour"] = new_colour
        
        elif option == "self_star":
            if value.lower() in ["true", "yes", "y"]:
                starboard_data["allow_self_star"] = True  # Convert to correct boolean if boolean given
            elif value.lower() in ["false", "no", "n"]:
                starboard_data["allow_self_star"] = False
            else:
                await self.bot.DefaultEmbedResponses.error_embed(self.bot, ctx, "Invalid value given", desc="Allow self star option must be either 'yes' or 'no'")
                return
        else:
            await self.bot.DefaultEmbedResponses.error_embed(self.bot, ctx, "Invalid option given, must be either 'minimum' or 'emoji'")
            return

        # If execution is here, the data has been changed, log the new change
        await starboard.update(starboard_data)
        await self.bot.DefaultEmbedResponses.success_embed(self.bot, ctx, "Successfully updated the starboard!")
        if option in ["color", "colour", "embed_colour"]:
            await channel.send(f"From this point onwards, all starboard embeds have the colour: {new_colour}!")
        elif option in ["emoji", "minimum"]:
            await channel.send(f"From this point onwards, it takes {starboard_data['minimum_stars']}x {starboard.get_string_emoji()}{'s' if starboard_data['minimum_stars'] > 1 else ''} to get onto the starboard!")
        elif option == "self_star":
            await channel.send(f"From this point onwards, message authors {'can' if starboard_data['allow_self_star'] == True else 'cannot'} star their own messages to get them onto the starboard!")

    @starboard.command()
    @commands.guild_only()
    @is_staff()
    async def delete(self, ctx: commands.Context, channel: discord.TextChannel | discord.Thread) -> None:
        """
        Delete a starboard setup and all its entries from the bot
        """
        
        starboard = await self._try_get_starboard(channel.id)
        if not starboard:
            await self.bot.DefaultEmbedResponses.error_embed(self.bot, ctx, "Starboard does not exist")
            return
        
        question = await self.bot.DefaultEmbedResponses.question_embed(self.bot, ctx, "Are you sure you wish to delete the starboard setup?", desc="React with the correct response")
        response = await self.boolean_reaction_getter(ctx, question)
        if response:
            await self._delete_starboard(channel)
            await self.bot.DefaultEmbedResponses.success_embed(self.bot, ctx, "Starboard deleted!", desc=f"The starboard setup and all associated entries have been deleted from the bot.")
        else:
            await self.bot.DefaultEmbedResponses.success_embed(self.bot, ctx, "Starboard deletion cancelled")

    # --- Error handlers ---
    @edit.error
    async def starboard_edit_error(self, ctx: commands.Context, error) -> None:
        """
        Handles errors that occur in the edit command
        """

        if isinstance(error, commands.errors.ChannelNotFound):
            await self.bot.DefaultEmbedResponses.error_embed(self.bot, ctx, "That channel does not exist")
        elif isinstance(error, commands.MissingRequiredArgument):
            await self.bot.DefaultEmbedResponses.information_embed(self.bot, ctx, "Starboard edit help", desc=f"""To edit the starbooard you need to execute the command like this: `{ctx.prefix}starboard edit #starboard_channel option value`
 `option` must be one of 'minimum', 'emoji', 'colour'/'color'/'embed_colour', or 'self_star'\n`value` is the value that you want to change it do""")

    @delete.error
    async def starboard_delete_error(self, ctx: commands.Context, error) -> None:
        """
        Handles errors that occur in the delete command
        """

        if isinstance(error, commands.errors.ChannelNotFound):
            await self.bot.DefaultEmbedResponses.error_embed(self.bot, ctx, "That channel does not exist")


async def setup(bot) -> None:
    await bot.add_cog(StarboardCog(bot))
