import discord
from discord import Embed, Colour
from discord.ext import commands
from discord.ext.commands import has_permissions
from discord.utils import get
from .utils import Permissions, Todo, is_dev
from datetime import datetime, timedelta


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_member_obj(self, ctx, member):
        """
        Attempts to get user/member object from mention/user ID.
        Independent of whether the user is a member of a shared guild
        Perhaps merge with utils function
        """
        in_guild = True
        try:
            print("Attempted member conversion")
            member = await commands.MemberConverter().convert(ctx, member)  # converts mention to member object
        except Exception as e:
            print(e)
            try:  # assumes id
                member = member.replace("<@!", "").replace(">", "")
                # fix for funny issue with mentioning users that aren't guild members
                member = await self.bot.fetch_user(member)
                # gets object from id, seems to work for users not in the server
                in_guild = False
            except Exception as e:
                print(e)
                return None, None
        return member, in_guild

    async def is_user_banned(self, ctx, user):
        try:
            await ctx.guild.fetch_ban(user)
        except discord.errors.NotFound:
            return False
        return True

    async def timer(self, todo, seconds, member_id):
        """Writes to todo table with the time to perform the given todo (e.g. timer(4, 120) would mean 4 is carried out in 120 seconds)"""
        timestamp = datetime.utcnow()
        new_timestamp = timestamp + timedelta(seconds=seconds)
        async with self.bot.pool.acquire() as connection:
            await connection.execute('INSERT INTO todo (todo_id, todo_time, member_id) values ($1, $2, $3)', todo,
                                     new_timestamp, member_id)

    async def advance_user(self, ctx: commands.Context, member: discord.Member, print=False): # TODO: This is GCSE9-1 specific
        roles = [y.name for y in member.roles]
        years = ['Y9', 'Y10', 'Y11', 'Post-GCSE']
        total = 0
        for year in years:
            if year in roles:
                total += 1
        if total > 1:
            if print:
                await ctx.send('Cannot advance this user: they have more that 1 year role.')
            return 'multiple years'
        elif total == 0:
            if print:
                await ctx.send('Cannot advance this user: they have no year role.')
            return 'no year'
        for i in range(len(years) - 1):
            year = years[i]
            if 'Post-GCSE' in roles:
                if print:
                    await ctx.send('Cannot advance this user: they are Post-GCSE already.')
                return 'postgcse error'
            elif year in roles:
                await member.remove_roles(get(member.guild.roles, name=year))
                await member.add_roles(get(member.guild.roles, name=years[i + 1]))
                if print:
                    await ctx.send(':ok_hand: The year has been advanced!')
                return 'success'

    # -----------------------CLOSE COMMAND-----------------------

    @commands.command(pass_context=True, name="close")
    @commands.guild_only()
    @is_dev()
    async def botclose(self, ctx):
        await self.bot.close(ctx)

    # -----------------------PURGE------------------------------

    @commands.command(pass_context=True)
    @commands.has_permissions(manage_messages = True) # TODO: Perhaps make it possible to turn some commands, like purge, off
    async def purge(self, ctx, limit='5', member: discord.Member = None):
        """Purges the channel.
Usage: `-purge 50`"""
        channel = ctx.channel

        if limit.isdigit():
            await ctx.message.delete()
            if not member:
                deleted = await channel.purge(limit=int(limit))
            else:
                try:
                    deleted = []
                    async for message in channel.history():
                        if len(deleted) == int(limit):
                            break
                        if message.author == member:
                            deleted.append(message)
                    await ctx.channel.delete_messages(deleted)
                except discord.ClientException:
                    await ctx.send(
                        "The amount of messages cannot be more than 100 when deleting a single users messages. Messages older than 14 days also cannot be deleted this way.")

            await ctx.send(f"Purged **{len(deleted)}** messages!", delete_after=3)

            await self.bot.add_config(ctx.guild.id)
            channel_id = self.bot.configs[ctx.guild.id]["mod_log_channel"]
            if channel_id is None:
                return
            channel = self.bot.get_channel(channel_id)

            embed = Embed(title='Purge', color=Colour.from_rgb(175, 29, 29))
            embed.add_field(name='Count', value=len(deleted))
            embed.add_field(name='Channel', value=channel.mention)
            embed.set_footer(text=self.bot.correct_time().strftime(self.bot.ts_format))
            await channel.send(embed=embed)
        else:
            await ctx.send(f'Please use an integer for the amount of messages to delete, not `{limit}` :ok_hand:')

    # -----------------------KICK------------------------------

    @commands.command(pass_context=True)
    @has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, args=""):
        """Kicks a given user.
Kick members perm needed"""
        reason = None
        if args:
            parsed_args = self.bot.flag_handler.separate_args(args, fetch=["reason"], blank_as_flag="reason")
            reason = parsed_args["reason"]
        if not reason:
            reason = f'No reason provided'
        try:  # perhaps add some like `attempt_dm` thing in utils instead of this?
            await member.send(f"You have been kicked from {ctx.guild} ({reason})")
        except discord.errors.Forbidden:
            print(f"Could not DM {member.display_name} about their kick!")
        await member.kick(reason=reason)
        await ctx.send(f'{member.mention} has been kicked :boot:')

        await self.bot.add_config(ctx.guild.id)
        channel_id = self.bot.configs[ctx.guild.id]["mod_log_channel"]
        if channel_id is None:
            return
        channel = self.bot.get_channel(channel_id)
        
        embed = Embed(title='Kick', color=Colour.from_rgb(220, 123, 28))
        embed.add_field(name='Member', value=f'{member.mention} ({member.id})')
        embed.add_field(name='Reason', value=reason + f" (kicked by {ctx.author.name})")
        embed.set_thumbnail(url=member.avatar_url)
        embed.set_footer(text=self.bot.correct_time().strftime(self.bot.ts_format))
        await channel.send(embed=embed)

    # -----------------------BAN------------------------------

    @commands.command(pass_context=True, aliases=["hackban", "massban"])
    @has_permissions(ban_members=True)
    async def ban(self, ctx, member, *, args=""):
        """Bans a given user.
        Merged with previous command hackban
        Single bans work with user mention or user ID
        Mass bans work with user IDs currently, reason flag HAS to be specified if setting
        Ban members perm needed"""
        reason = "No reason provided"
        massban = (ctx.invoked_with == "massban")
        timeperiod = None
        if args:
            parsed_args = self.bot.flag_handler.separate_args(args, fetch=["time", "reason"],
                                                              blank_as_flag="reason" if not massban else None)
            timeperiod = parsed_args["time"]
            reason = parsed_args["reason"]

        if massban:
            members = ctx.message.content[ctx.message.content.index(" ") + 1:].split(" ")
            members = [member for member in members if len(member) == 18 and str(member).isnumeric()]
            # possibly rearrange at some point to allow checking if the member/user object can be obtained?
            tracker = await ctx.send(f"Processed bans for 0/{len(members)} members")
        else:
            members = [member]
        already_banned = []
        not_found = []
        ban = 0
        for ban, member_ in enumerate(members, start=1):
            if massban:
                await tracker.edit(content=f"Banning {ban}/{len(members)} users" + (
                    f", {len(not_found)} users not found" if len(not_found) > 0 else "") + (
                    f", {len(already_banned)} users already banned" if len(already_banned) > 0 else "")
                )
            member, in_guild = await self.get_member_obj(ctx, member_)
            if timeperiod:
                await self.timer(Todo.UNBAN, timeperiod, member.id)
            print(f"MEMBER IS TYPE {type(member).__name__}")
            if not member:
                not_found.append(member_)
                if not massban:
                    await ctx.send(f"Couldn't find that user ({member_})!")
                    return
                else:
                    continue
            if await self.is_user_banned(ctx, member):
                already_banned.append(member.mention)
                if not massban:
                    await ctx.send(f"{member.mention} is already banned!")
                    return
                else:
                    continue
            try:
                await member.send(f"You have been banned from {ctx.guild.name} ({reason})")
            except discord.errors.Forbidden:
                print(f"Could not DM {member.id} about their ban!")
            await ctx.guild.ban(member, reason=reason, delete_message_days=0)
            if not massban:
                await ctx.send(f'{member.mention} has been banned.')

            await self.bot.add_config(ctx.guild.id)
            channel_id = self.bot.configs[ctx.guild.id]["mod_log_channel"]
            if channel_id is None:
                return
            channel = self.bot.get_channel(channel_id)

            embed = Embed(title='Ban' if in_guild else 'Hackban', color=Colour.from_rgb(255, 255, 255))
            embed.add_field(name='Member', value=f'{member.mention} ({member.id})')
            embed.add_field(name='Moderator', value=str(ctx.author))
            embed.add_field(name='Reason', value=reason)
            embed.set_thumbnail(url=member.avatar_url)
            embed.set_footer(text=self.bot.correct_time().strftime(self.bot.ts_format))

            await channel.send(embed=embed)
        if massban:
            # chr(10) used for \n since you can't have backslash characters in f string fragments
            await tracker.edit(content=f"Processed bans for {ban}/{len(members)} users" +
                                       (
                                           f"\n__**These users weren't found**__:\n\n - {f'{chr(10)} - '.join(f'{a_not_found}' for a_not_found in not_found)}\n" if len(
                                               not_found) > 0 else ""
                                       ) +
                                       (
                                           f"\n__**These users are already banned**__:\n\n - {f'{chr(10)} - '.join(f'{a_already_banned}' for a_already_banned in already_banned)}" if len(
                                               already_banned) > 0 else ""
                                       )
                               )

    @commands.command(pass_context=True)
    @has_permissions(ban_members=True)
    async def unban(self, ctx, member, *, args=""):
        """Unbans a given user with the ID.
        Ban members perm needed."""
        reason = "No reason provided"
        if args:
            parsed_args = self.bot.flag_handler.separate_args(args, fetch=["reason"], blank_as_flag="reason")
            reason = parsed_args["reason"]

        member, in_guild = await self.get_member_obj(ctx, member)
        if not member:
            await ctx.send("Couldn't find that user!")
            return

        if not await self.is_user_banned(ctx, member):
            await ctx.send(f'{member.mention} is not already banned.')
            return

        await ctx.guild.unban(member, reason=reason)
        await ctx.send(f'{member.mention} has been unbanned!')

        await self.bot.add_config(ctx.guild.id)
        channel_id = self.bot.configs[ctx.guild.id]["mod_log_channel"]
        if channel_id is None:
            return
        channel = self.bot.get_channel(channel_id)

        embed = Embed(title='Unban', color=Colour.from_rgb(76, 176, 80))
        embed.add_field(name='Member', value=f'{member.mention} ({member.id})')
        embed.add_field(name='Moderator', value=str(ctx.author))
        embed.add_field(name='Reason', value=reason)
        embed.set_thumbnail(url=member.avatar_url)
        embed.set_footer(text=self.bot.correct_time().strftime(self.bot.ts_format))
        await channel.send(embed=embed)

    # -----------------------MUTES------------------------------

    @commands.command(pass_context=True)
    @commands.has_permissions(manage_roles = True)
    async def mute(self, ctx, member: discord.Member, *, args=""):
        """Gives a given user the Muted role.
Manage roles perm needed."""
        reason, timeperiod = None, None
        if args:
            parsed_args = self.bot.flag_handler.separate_args(args, fetch=["time", "reason"], blank_as_flag="reason")
            timeperiod = parsed_args["time"]
            reason = parsed_args["reason"]

            if timeperiod:
                await self.timer(Todo.UNMUTE, timeperiod, member.id)

        role = get(member.guild.roles, name='Muted')
        await member.add_roles(role, reason=reason if reason else f'No reason - muted by {ctx.author.name}')
        await ctx.send(':ok_hand:')
        # 'you are muted ' + timestring
        if not timeperiod:
            timestring = 'indefinitely'
        else:
            time = (self.bot.correct_time() + timedelta(seconds=timeperiod))  # + timedelta(hours = 1)
            timestring = 'until ' + time.strftime('%H:%M on %d/%m/%y')

        if not reason or reason is None:
            reasonstring = 'an unknown reason (the staff member did not give a reason)'
        else:
            reasonstring = reason
        try:
            await member.send(f'You have been muted {timestring} for {reasonstring}.')
        except discord.errors.Forbidden:
            print(f"NOTE: Could not DM {member.display_name} about their mute")

        await self.bot.add_config(ctx.guild.id)
        channel_id = self.bot.configs[ctx.guild.id]["mod_log_channel"]
        if channel_id is None:
            return
        channel = self.bot.get_channel(channel_id)

        embed = Embed(title='Member Muted', color=Colour.from_rgb(172, 32, 31))
        embed.add_field(name='Member', value=f'{member.mention} ({member.id})')
        embed.add_field(name='Moderator', value=str(ctx.author))
        embed.add_field(name='Reason', value=reason)
        embed.add_field(name='Expires',
                        value=timestring.replace('until ', '') if timestring != 'indefinitely' else "Never")
        embed.set_thumbnail(url=member.avatar_url)
        embed.set_footer(text=self.bot.correct_time().strftime(self.bot.ts_format))
        await channel.send(embed=embed)

    @commands.command(pass_context=True)
    @commands.has_permissions(manage_roles = True)
    async def unmute(self, ctx, member: discord.Member, *, args=""):
        """Removes Muted role from a given user.
Manage roles perm needed."""
        reason = None
        if args:
            parsed_args = self.bot.flag_handler.separate_args(args, fetch=["reason"], blank_as_flag="reason")
            reason = parsed_args["reason"]

        role = get(member.guild.roles, name='Muted')
        await member.remove_roles(role,
                                  reason=reason if reason else f'No reason - unmuted by {ctx.author.name}')
        await ctx.send(':ok_hand:')

    # -----------------------SLOWMODE------------------------------

    @commands.command(pass_context=True)
    async def slowmode(self, ctx, time):
        """Adds slowmode in a specific channel. Time is given in seconds."""
        if not ctx.channel.permissions_for(ctx.author).manage_channel:
            await ctx.send("You do not have permissions for that :sob:")
            return

        try:
            if int(time) <= 60:
                await ctx.channel.edit(slowmode_delay=int(time))
                if int(time) == 0:
                    await ctx.send(':ok_hand: slowmode removed from this channel.')
                else:
                    await ctx.send(f':ok_hand: Slowmode of {time} seconds added.')
            else:
                await ctx.send('You cannot add a slowmode greater than 60.')
        except Exception as e:
            print(e)

    # -----------------------JAIL & BANISH------------------------------

    @commands.command(pass_context=True)
    @commands.has_permissions(manage_roles = True)
    async def jail(self, ctx, member: discord.Member):
        """Lets a member view whatever channel has been set up with view channel perms for the Jail role.
Manage roles perm needed."""
        role = get(member.guild.roles, name='Jail')
        await member.add_roles(role)
        await ctx.send(f':ok_hand: {member.mention} has been jailed.')

    @commands.command(pass_context=True)
    @commands.has_permissions(manage_roles = True)
    async def unjail(self, ctx, member: discord.Member):
        """Puts a member in #the-court.
Manage roles perm needed."""
        try:
            role = get(member.guild.roles, name='Jail')
            await member.remove_roles(role)
            await ctx.send(f':ok_hand: {member.mention} has been unjailed.')
        except Exception:
            await ctx.send(f'{member.mention} could not be unjailed. Please do it manually.')

    @commands.command(pass_context=True)
    @commands.has_permissions(manage_roles = True)
    async def banish(self, ctx, member: discord.Member):
        """Removes all roles from a user, rendering them powerless.
Manage roles perm needed."""
        await member.edit(roles=[])
        await ctx.send(f':ok_hand: {member.mention} has been banished.')

    # -----------------------ADVANCEMENT------------------------------

    @commands.group(pass_context=True)
    @commands.guild_only()
    async def advance(self, ctx):
        """Results day command.
Y11 -> Post-GCSE
Y10 -> Y11
Y9 -> Y10"""
        if ctx.invoked_subcommand is None:
            await ctx.send('```-advance member @Member``` or ```-advance all```')

    @advance.command(pass_context=True)
    @commands.has_permissions(administrator = True)
    async def memberx(self, ctx, member: discord.Member):
        """Advances one user.
Moderator role needed."""
        try:
            await self.advance_user(ctx, member)
            await ctx.send(':ok_hand: the year has been advanced.')
        except Exception as e:
            ctx.send('''Unexpected error...
```{}```'''.format(e))

    @advance.command(pass_context=True)
    @commands.has_permissions(administrator = True)
    async def allx(self, ctx):
        """Advances everybody in the server.
Administrator role needed."""
        msg = await ctx.send('Doing all, please wait...')
        members = ctx.guild.members  # everyone
        errors = []

        n = len(members)
        for i, member in enumerate(members):
            try:
                advance = await self.advance_user(ctx, member)
                if advance != 'success' or advance != 'postgcse error':
                    errors.append([member, advance])
                await msg.edit(content=f"Doing all, please wait... currently on {i + 1}/{n}")
            except Exception as e:
                errors.append([member, f'unexpected: {e}'])

        await ctx.send('Advanced everyone\'s year!')

        await self.bot.add_config(ctx.guild.id)
        channel_id = self.bot.configs[ctx.guild.id]["mod_log_channel"]
        if channel_id is None:
            return
        channel = self.bot.get_channel(channel_id)
            
        for error in errors:
            await channel.send(f'{error[0].mention} = {error[1]}')

    # @all.error
    # async def all_handler(self, ctx, error):
    #    if isinstance(error, commands.CheckFailure):
    #        await ctx.send('`Administrator` role needed.')

    # -----------------------MISC------------------------------

    @commands.command()
    async def say(self, ctx, channel: discord.TextChannel, *, text):
        """Say a given string in a given channel
Staff role needed."""
        if await self.bot.is_staff(ctx):
            await channel.send(text[5:] if text.startswith("/tts") else text, tts=text.startswith("/tts ") and channel.permissions_for(ctx.author).send_tts_messages)
        else:
            await ctx.send("You do not have permissions to do that :sob:")

    @commands.command()
    @commands.is_owner()
    async def reset_invites(self, ctx):
        """A command for adam only which resets the invites"""
        invites = await ctx.guild.invites()
        async with self.bot.pool.acquire() as connection:
            await connection.execute('DELETE FROM invites')
            for invite in invites:
                try:
                    data = [invite.inviter.id,
                            invite.code,
                            invite.uses,
                            invite.max_uses,
                            invite.created_at,
                            invite.max_age]

                    await connection.execute(
                        'INSERT INTO invites (inviter, code, uses, max_uses, created_at, max_age) values ($1, $2, $3, $4, $5, $6)',
                        *data)
                except Exception:
                    pass

    @commands.command(pass_context=True)
    @commands.has_permissions(manage_guild = True)
    async def revokeinvite(self, ctx, invite_code):
        """
        Command that revokes an invite from a server
        """
        try:
            await self.bot.delete_invite(invite_code)
            await ctx.send(f"Invite code {invite_code} has been deleted :ok_hand:")
        except discord.Forbidden:
            await ctx.send("Adam-Bot does not have permissions to revoke invites.")
        except discord.NotFound:
            await ctx.send("Invite code was not found - it's either invalid or expired :sob:")
        except Exception as e:
            await ctx.send(f"Invite revoking failed: {e}")


def setup(bot):
    bot.add_cog(Moderation(bot))
