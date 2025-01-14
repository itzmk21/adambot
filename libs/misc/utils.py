from typing import Optional

import discord
from discord import Embed, Colour, Message, File
from discord.ext import commands
from math import ceil
from datetime import timedelta
from io import BytesIO, StringIO
import asyncio


class EmbedPages:
    def __init__(self, page_type: int, data: list, title: str, colour: Colour, bot, initiator: discord.Member, channel: discord.TextChannel | discord.Thread, desc: str = "", thumbnail_url: str = "",
                 footer: str = "", icon_url: str = "") -> None:
        self.bot = bot
        self.data = data
        self.title = title
        self.page_type = page_type
        self.top_limit = 0
        self.timeout = 300  # 300 seconds, or 5 minutes
        self.embed: Embed = None  # Embed(title=title + ": Page 1", color=colour, desc=desc)
        self.message: Message = None
        self.page_num = 1
        self.initiator = initiator  # Here to stop others using the embed
        self.channel = channel

        # These are for formatting the embed
        self.desc = desc
        self.footer = footer
        self.thumbnail_url = thumbnail_url
        self.icon_url = icon_url
        self.colour = colour

    async def set_page(self, page_num: int) -> None:
        """
        Changes the embed accordingly
        """

        if self.page_type == PageTypes.REP:
            self.data = [x for x in self.data if self.channel.guild.get_member(x[0]) is not None]
            page_length = 10
        elif self.page_type == PageTypes.ROLE_LIST:
            page_length = 10
        else:
            page_length = 5
        self.top_limit = ceil(len(self.data) / page_length)

        # Clear previous data
        self.embed = Embed(title=f"{self.title} (Page {page_num}/{self.top_limit})", color=self.colour,
                           description=self.desc)
        
        if self.footer and self.icon_url:
            self.embed.set_footer(text=self.footer, icon_url=self.icon_url)
        elif self.footer:
            self.embed.set_footer(text=self.footer)  # TODO: Is there a more efficient way to cover the cases where either a footer or icon_url is given but not both?
        elif self.icon_url:
            self.embed.set_footer(icon_url=self.icon_url)
        if self.thumbnail_url:
            self.embed.set_thumbnail(url=self.thumbnail_url)  # NOTE: I WAS CHANGING ALL GUILD ICONS AND AVATARS SO THEY WORK WITH THE DEFAULTS I.E. NO AVATAR OR NO GUILD ICON

        # Gettings the wanted data
        self.page_num = page_num
        page_num -= 1
        for i in range(page_length * page_num, min(page_length * page_num + page_length, len(self.data))):
            if self.page_type == PageTypes.QOTD:
                question_id = self.data[i][0]
                question = self.data[i][1]
                member_id = int(self.data[i][2])
                user = await self.bot.fetch_user(member_id)
                date = (self.data[i][3] + timedelta(hours=1)).strftime("%H:%M on %d/%m/%y")

                self.embed.add_field(name=f"{question}",
                                     value=f"ID **{question_id}** submitted on {date} by {user.name if user else '*MEMBER NOT FOUND*'} ({member_id})",
                                     inline=False)

            elif self.page_type == PageTypes.WARN:
                staff = await self.bot.fetch_user(self.data[i][2])
                member = await self.bot.fetch_user(self.data[i][1])

                if member:
                    member_string = f"{str(member)} ({self.data[i][1]}) Reason: {self.data[i][4]}"
                else:
                    member_string = f"DELETED USER ({self.data[i][1]}) Reason: {self.data[i][4]}"

                if staff:
                    staff_string = f"{str(staff)} ({self.data[i][2]})"
                else:
                    staff_string = f"DELETED USER ({self.data[i][2]})"

                self.embed.add_field(name=f"**{self.data[i][0]}** : {member_string}",
                                     value=f"{self.data[i][3].strftime('On %d/%m/%Y at %I:%M %p')} by {staff_string}",
                                     inline=False)

            elif self.page_type == PageTypes.REP:
                member = self.channel.guild.get_member(self.data[i][0])
                self.embed.add_field(name=f"{member.display_name}", value=f"{self.data[i][1]}", inline=False)

            elif self.page_type == PageTypes.CONFIG:
                config_key = list(self.data.keys())[i]  # Change the index into the key
                config_option = self.data[config_key]  # Get the current value list from the key
                name = f"• {str(config_key)} ({config_option[1]})"  # Config name that appears on the embed
                self.embed.add_field(name=name, value=config_option[2], inline=False)

            elif self.page_type == PageTypes.ROLE_LIST:
                self.embed.add_field(name=self.data[i].name, value=self.data[i].mention, inline=False)

            elif self.page_type == PageTypes.STARBOARD_LIST:
                starboard = self.data[i]
                channel = self.bot.get_channel(starboard.channel.id)
                custom_emoji = self.bot.get_emoji(starboard.emoji_id) if starboard.emoji_id else None
                colour = starboard.embed_colour if starboard.embed_colour else "#" + "".join([str(hex(component)).replace("0x", "").upper() for component in self.bot.GOLDEN_YELLOW.to_rgb()])
                
                sub_fields = f"• Minimum stars: {starboard.minimum_stars}\n"  # Add star subfield
                sub_fields += "• Emoji: " + (starboard.emoji if starboard.emoji else f"<:{custom_emoji.name}:{custom_emoji.id}>")  # Add either the standard emoji, or the custom one
                sub_fields += "\n• Colour: " + colour
                sub_fields += "\n• Allow self starring (author can star their own message): " + str(starboard.allow_self_star)
                self.embed.add_field(name=f"#{channel.name}", value=sub_fields, inline=False)

    async def previous_page(self) -> None:
        """
        Moves the embed to the previous page
        """

        if self.page_num != 1:  # Cannot go to previous page if already on first page
            await self.set_page(self.page_num - 1)
            await self.edit()

    async def next_page(self) -> None:
        """
        Moves the embed to the next page
        """

        if self.page_num != self.top_limit:  # Can only move next if not on the limit
            await self.set_page(self.page_num + 1)
            await self.edit()

    async def first_page(self) -> None:
        """
        Moves the embed to the first page
        """

        await self.set_page(1)
        await self.edit()

    async def last_page(self) -> None:
        """
        Moves the embed to the last page
        """

        await self.set_page(self.top_limit)
        await self.edit()

    async def send(self) -> None:
        """
        Sends the embed message. The message is deleted after 300 seconds (5 minutes).
        """

        self.message = await self.channel.send(embed=self.embed)
        await self.message.add_reaction(EmojiEnum.MIN_BUTTON)
        await self.message.add_reaction(EmojiEnum.LEFT_ARROW)
        await self.message.add_reaction(EmojiEnum.RIGHT_ARROW)
        await self.message.add_reaction(EmojiEnum.MAX_BUTTON)
        await self.message.add_reaction(EmojiEnum.CLOSE)
        self.bot.pages.append(self)
        try:
            await asyncio.sleep(self.timeout)
            await self.message.clear_reactions()
        except discord.HTTPException:  # Removing reactions failed (perhaps message already deleted)
            pass

    async def edit(self) -> None:
        """
        Edits the message to the current self.embed and updates self.message
        """

        await self.message.edit(embed=self.embed)


class PageTypes:
    QOTD = 0
    WARN = 1
    REP = 2
    CONFIG = 3
    ROLE_LIST = 4
    STARBOARD_LIST = 5


class EmojiEnum:
    MIN_BUTTON = "\U000023ee"
    MAX_BUTTON = "\U000023ed"
    LEFT_ARROW = "\U000025c0"
    RIGHT_ARROW = "\U000025b6"
    BUTTON = "\U00002b55"
    CLOSE = "\N{CROSS MARK}"
    TRUE = "\U00002705"
    FALSE = "\N{CROSS MARK}"
    RECYCLE = "\U0000267b"
    SPEAKING = "\U0001F5E3"

    ONLINE = "\U0001F7E2"
    IDLE = "\U0001F7E1"
    DND = "\U0001F534"
    OFFLINE = "\U000026AB"


DEVS = [
    394978551985602571,  # Adam C
    420961337448071178,  # Hodor
    686967704116002827,  # Xp
]

CODE_URL = "https://github.com/adampy/adambot"


async def send_image_file(fig, channel: discord.TextChannel | discord.Thread, filename: str, extension: str = "png") -> None:
    """
    Send data to a channel with filename `filename`
    """

    buf = BytesIO()
    fig.savefig(buf)
    buf.seek(0)
    await channel.send(file=File(buf, filename=f"{filename}.{extension}"))


async def send_text_file(text: str, channel: discord.TextChannel | discord.Thread, filename: str, extension: str = "txt") -> None:
    """
    Send a text data to a channel with filename `filename`
    """

    buf = StringIO()
    buf.write(text)
    buf.seek(0)
    await channel.send(file=File(buf, filename=f"{filename}.{extension}"))


async def get_spaced_member(ctx: commands.Context, bot, *, args: str) -> Optional[discord.Member]:
    """
    Moves hell on Earth to get a guild member object from a given string
    Makes use of last_active, a priority temp list that stores member objects of
    the most recently active members
    """

    possible_mention = args.split(" ")[0]
    user = None
    try:
        user = await commands.MemberConverter().convert(ctx,
                                                        possible_mention)  # try standard approach before anything daft
    except commands.errors.MemberNotFound:
        try:
            user = await commands.MemberConverter().convert(ctx, args)
        except commands.errors.MemberNotFound:
            # for the love of god
            lists = [bot.last_active[ctx.guild.id], ctx.guild.members]
            attribs = ["display_name", "name"]
            for list_ in lists:
                for attrib in attribs:
                    if user is not None:
                        break
                    for member in list_:
                        name = getattr(member, attrib)
                        if possible_mention in name or args in name:
                            user = member
                            break
                    if user is None:
                        for member in list_:
                            name = getattr(member, attrib)
                            if name.lower() == possible_mention.lower() or name.lower() == args.lower():
                                # don't need normal checks for this as the converter would have got it already
                                user = member
                                break
                    if user is None:
                        for member in list_:
                            name = getattr(member, attrib)
                            if possible_mention.lower() in name.lower() or args.lower() in name.lower():
                                user = member
                                break

    return user


def make_readable(text: str) -> str:
    """
    Turns stuff like ANIMATED_ICON into Animated Icon
    """

    return " ".join([part[:1].upper() + part[1:] for part in text.lower().replace("_", " ").split()])


def ordinal(n: int) -> str:
    """
    Returns the shortened ordinal for the cardinal number given. E.g. 1 -> "1st", 74 -> "74th"
        - https://stackoverflow.com/questions/9647202/ordinal-numbers-replacement
    """

    suffix = ["th", "st", "nd", "rd", "th"][min(n % 10, 4)]
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    return str(n) + suffix


TIME_UNITS = {
    "w": {"aliases": ("weeks", "week"), "in_seconds": 604800},
    "d": {"aliases": ("days", "day"), "in_seconds": 86400},
    "h": {"aliases": ("hours", "hour", "hr"), "in_seconds": 3600},
    "m": {"aliases": ("minutes", "minute", "mins", "min"), "in_seconds": 60},
    "s": {"aliases": ("seconds", "second", "secs", "sec"), "in_seconds": 1}
}


# WARNING: You are about to observe Area 51 code, proceed with caution


class flag_methods:
    def __init__(self) -> None:
        return

    @staticmethod
    def str_time_to_seconds(string_: str) -> int:

        # when not close to having a brain aneurysm, rewrite this
        # so it can convert up and down to any defined unit, not
        # just seconds

        string = string_.replace(" ", "")
        for unit in TIME_UNITS:
            for alias in TIME_UNITS[unit]["aliases"]:
                string = string.replace(alias, unit)
        while ".." in string:  # grade A pointless feature
            string = string.replace("..", ".")
        string = list(string)
        times = []
        time_string = ""
        for pos in string:
            if pos.isdigit() or (pos == "." and "." not in time_string):
                time_string += pos
            else:
                times.append([time_string, pos])
                time_string = ""
        seconds = 0
        for time_ in times:
            if len(time_) == 2 and time_[0] and time_[1] in TIME_UNITS:  # check to weed out dodgy stuff
                seconds += float(time_[0]) * TIME_UNITS[time_[1]]["in_seconds"]
        return seconds


class flags:
    def __init__(self) -> None:
        self.flag_prefix = "-"
        self.implemented_properties = ["flag", "post_parse_handler"]
        self.flags = {"": {"flag": "", "post_parse_handler": None}}
        self.inv_flags = {"": ""}

    def set_flag(self, flag_name: str, flag_def: dict) -> None:
        assert type(flag_def) is dict and "flag" in flag_def
        assert type(flag_def["flag"]) is str
        assert callable(flag_def.get("post_parse_handler")) or flag_def.get("post_parse_handler") is None
        for property_ in self.implemented_properties:
            if property_ not in flag_def:
                flag_def[property_] = None
        self.flags[flag_name] = flag_def
        self.inv_flags[flag_def["flag"]] = flag_name

    def remove_flag(self, flag_name: str) -> None:
        if flag_name in self.flags:
            del self.flags[flag_name]

    def separate_args(self, args, fetch: list[str] = [], has_cmd: bool = False, blank_as_flag: str = "") -> dict:
        # TODO:
        #   - Use getters for the flags at some point (not strictly necessary but OOP)
        #   - Tidy up if at all possible :P
        #   - possible some of the logic could be replaced by regex but who likes regex?

        if not fetch:
            fetch = ["*"]

        args = args.strip()
        if has_cmd:
            args = " " + " ".join(args.split(" ")[1:])
        flag_dict = {}
        startswithflag = False
        for flag in self.inv_flags:
            if args.startswith(f"{self.flag_prefix}{flag}") and flag:
                startswithflag = True
                break
        if not startswithflag:  # then it's blank
            args = self.flag_prefix + (
                str(self.flags[blank_as_flag]["flag"]) if (blank_as_flag in self.flags) else "") + " " + args
        if args.startswith(self.flag_prefix):
            args = " " + args
        args = args.split(f" {self.flag_prefix}")
        args = [a.split(" ") for a in args]
        if not args[0][0]:
            del args[0]
        for a in range(len(args)):
            if len(args[a]) == 1:
                args[a].insert(0, "" if blank_as_flag not in self.flags else self.flags[blank_as_flag]["flag"])
            args[a] = [args[a][0], " ".join(args[a][1:])]
            if (args[a][0] in self.inv_flags) and (self.inv_flags[args[a][0]] in fetch or fetch == ["*"]):
                if self.inv_flags[args[a][0]] in flag_dict:
                    flag_dict[self.inv_flags[args[a][0]]] += " " + args[a][1]
                else:
                    flag_dict[self.inv_flags[args[a][0]]] = args[a][1]
        flags_found = flag_dict.keys()
        for flag in flags_found:
            post_handler = self.flags[flag]["post_parse_handler"]
            if post_handler:
                updated_flag = post_handler(flag_dict[flag])
                flag_dict[flag] = updated_flag

        for fetcher in fetch:
            if fetcher != "*" and fetcher not in flag_dict:
                flag_dict[fetcher] = None  # saves a bunch of boilerplate code elsewhere

        return flag_dict  # YES IT HAS FINISHED! FINALLY!


def time_arg(arg: str) -> int:  # rewrite
    """
    Given a time argument gets the time in seconds
    """

    total = 0
    times = arg.split(" ")
    if len(times) == 0:
        return 0
    for item in times:
        if item[-1] == "w":
            total += 7 * 24 * 60 * 60 * int(item[:-1])
        elif item[-1] == "d":
            total += 24 * 60 * 60 * int(item[:-1])
        elif item[-1] == "h":
            total += 60 * 60 * int(item[:-1])
        elif item[-1] == "m":
            total += 60 * int(item[:-1])
        elif item[-1] == "s":
            total += int(item[:-1])
    return total


def time_str(seconds: int) -> str:  # rewrite before code police get dispatched
    """
    Given a number of seconds returns the string version of the time
    Is outputted in a format that can be fed into time_arg
    """

    weeks = seconds // (7 * 24 * 60 * 60)
    seconds -= weeks * 7 * 24 * 60 * 60
    days = seconds // (24 * 60 * 60)
    seconds -= days * 24 * 60 * 60
    hours = seconds // (60 * 60)
    seconds -= hours * 60 * 60
    minutes = seconds // 60
    seconds -= minutes * 60
    seconds = round(seconds, 0 if str(seconds).endswith(".0") else 1)  # don't think the last bit needs to be as complex for all time units but oh well

    output = ""
    if weeks:
        output += f"{(str(weeks) + ' ').replace('.0 ', '').strip()}w "

    if days:
        output += f"{(str(days) + ' ').replace('.0 ', '').strip()}d "

    if hours:
        output += f"{(str(hours) + ' ').replace('.0 ', '').strip()}h "

    if minutes:
        output += f"{(str(minutes) + ' ').replace('.0 ', '').strip()}m "

    if seconds:
        output += f"{(str(seconds) + ' ').replace('.0 ', '').strip()}s"

    return output.strip()


def starts_with_any(string: str, possible_starts: list[str]) -> bool:
    """
    Given a string and a list of possible_starts, the function returns
    True if string starts with any of the starts in the possible starts.
    Otherwise it returns False.
    """

    for start in possible_starts:
        if string.startswith(start):
            return True
    return False


ERROR_RED = Colour.from_rgb(255, 7, 58)
SUCCESS_GREEN = Colour.from_rgb(57, 255, 20)
INFORMATION_BLUE = Colour.from_rgb(32, 141, 177)
GOLDEN_YELLOW = Colour.from_rgb(252, 172, 66)

# EMBED RESPONSES


class DefaultEmbedResponses:
    @staticmethod
    async def invalid_perms(bot, ctx: commands.Context, thumbnail_url: str = "", bare: bool = False) -> discord.Message:
        """
        Internal procedure that is executed when a user has invalid perms
        """

        embed = Embed(title=f":x: You do not have permissions to do that!", description="Only people with permissions (usually staff) can use this command!",
                      color=ERROR_RED)
        if not bare:
            embed.set_footer(text=f"Requested by: {ctx.author.display_name} ({ctx.author})\n" + bot.correct_time().strftime(
                bot.ts_format), icon_url=get_user_avatar_url(ctx.author, mode=1)[0])
            if thumbnail_url:
                embed.set_thumbnail(url=thumbnail_url)
        response = await ctx.reply(embed=embed)
        return response

    @staticmethod
    async def error_embed(bot, ctx: commands.Context, title: str, desc: str = "", thumbnail_url: str = "", bare: bool = False) -> discord.Message:
        embed = Embed(title=f":x: {title}", description=desc, color=ERROR_RED)
        if not bare:
            embed.set_footer(text=f"Requested by: {ctx.author.display_name} ({ctx.author})\n" + bot.correct_time().strftime(
                bot.ts_format), icon_url=get_user_avatar_url(ctx.author, mode=1)[0])
            if thumbnail_url:
                embed.set_thumbnail(url=thumbnail_url)
        response = await ctx.reply(embed=embed)
        return response

    @staticmethod
    async def success_embed(bot, ctx: commands.Context, title: str, desc: str = "", thumbnail_url: str = "", bare: bool = False) -> discord.Message:
        embed = Embed(title=f":white_check_mark: {title}", description=desc, color=SUCCESS_GREEN)
        if not bare:
            embed.set_footer(text=f"Requested by: {ctx.author.display_name} ({ctx.author})\n" + bot.correct_time().strftime(
              bot.ts_format), icon_url=get_user_avatar_url(ctx.author, mode=1)[0])
            if thumbnail_url:
                embed.set_thumbnail(url=thumbnail_url)
        response = await ctx.reply(embed=embed)
        return response

    @staticmethod
    async def information_embed(bot, ctx: commands.Context, title: str, desc: str = "", thumbnail_url: str = "", bare: bool = False) -> discord.Message:
        embed = Embed(title=f":information_source: {title}", description=desc, color=INFORMATION_BLUE)
        if not bare:
            embed.set_footer(text=f"Requested by: {ctx.author.display_name} ({ctx.author})\n" + bot.correct_time().strftime(
             bot.ts_format), icon_url=get_user_avatar_url(ctx.author, mode=1)[0])
            if thumbnail_url:
                embed.set_thumbnail(url=thumbnail_url)
        response = await ctx.reply(embed=embed)
        return response

    @staticmethod
    async def question_embed(bot, ctx: commands.Context, title: str, desc: str = "", thumbnail_url: str = "", bare: bool = False) -> discord.Message:
        embed = Embed(title=f":grey_question: {title}", description=desc, color=INFORMATION_BLUE)
        if not bare:
            embed.set_footer(text=f"Requested by: {ctx.author.display_name} ({ctx.author})\n" + bot.correct_time().strftime(
             bot.ts_format), icon_url=get_user_avatar_url(ctx.author, mode=1)[0])
            if thumbnail_url:
                embed.set_thumbnail(url=thumbnail_url)
        response = await ctx.reply(embed=embed)
        return response


def get_guild_icon_url(guild: discord.Guild) -> str:
    """
    Returns either a `str` which corresponds to `guild`'s icon. If none is present, an empty string is returned
    """
    return guild.icon if hasattr(guild, "icon") else ""


def get_user_avatar_url(member: discord.Member, mode: int = 0) -> list[str]:
    """
    Returns a `str` which corresponds to `user`'s current avatar url

    Mode:

    0 - Account avatar
    1 - Guild avatar - will return account avatar if None
    2 - Both
    """

    account_avatar_url = member.avatar
    if not account_avatar_url:
        account_avatar_url = member.default_avatar.url
    else:
        account_avatar_url = account_avatar_url.url

    guild_avatar_url = account_avatar_url if (not hasattr(member, "guild_avatar") or not hasattr(member.guild_avatar, "url") or not member.guild_avatar.url) else member.guild_avatar.url

    match mode:  # OMG A SWITCH CASE
        case 0:
            return [account_avatar_url]
        case 1:
            return [guild_avatar_url]
        case 2:
            return [account_avatar_url, guild_avatar_url]
        case _:
            return []
