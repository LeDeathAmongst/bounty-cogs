import asyncio
import time
import logging
from typing import Dict, Optional

import discord
from discord.ext import tasks
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.menus import start_adding_reactions
from redbot.core.utils.chat_formatting import humanize_list

from .constants import class_spec_dict, emoji_class_dict
from .model import Event, Flags

log = logging.getLogger("red.misan-cogs.eventmanager")


class EventManager(commands.Cog):
    """A cog to create and manage events."""
    
    __version__ = "1.0.0" # starting versioning now to keep track so starting from 1.0.0
    __author__ = ["crayyy_zee#2900"]

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0x352567829, force_registration=True)
        self.config.init_custom("events", 2)
        self.cache: Dict[int, Dict[int, Event]] = {}
        
    def format_help_for_context(self, ctx: commands.Context) -> str:
        pre_processed = super().format_help_for_context(ctx) or ""
        n = "\n" if "\n\n" not in pre_processed else ""
        text = [
            f"{pre_processed}{n}",
            f"Cog Version: **{self.__version__}**",
            f"Author: {humanize_list(self.__author__)}",
        ]
        return "\n".join(text)

    async def to_cache(self):
        all_guilds = await self.config.custom("events").all()
        for guild_id, guild_config in all_guilds.items():
            g = self.cache.setdefault(int(guild_id), {})
            for event in guild_config.values():
                try:
                    g[event["message_id"]] = Event.from_json(self.bot, event)

                except Exception as e:
                    log.exception("Error occurred when caching: ", exc_info=e)

    async def to_config(self):
        for guild_config in self.cache.values():
            for event in guild_config.values():
                json = event.json
                await self.config.custom("events", event.guild_id, event.message_id).set(json)

    def cog_unload(self):
        asyncio.create_task(self.to_config())

    @commands.command(name="event")
    async def event(self, ctx: commands.Context, *, flags: Flags):
        """
        Start an event.

        Valid flags are:
        `--end` - The time the event ends.
        `--image` - The image to use for the event.
        `--name` - The name of the event.
        `--description` - The description of the event.
        `--channel` - The channel to post the event in. [optional]
        """
        flags["channel_id"] = flags.get("channel_id") or ctx.channel.id
        event = Event(
            ctx.bot,
            message_id=ctx.message.id,
            guild_id=ctx.guild.id,
            author_id=ctx.author.id,
            **flags,
        )
        msg = await ctx.send(embed=event.embed)
        event.message_id = msg.id
        start_adding_reactions(msg, [i for i in emoji_class_dict.keys()] + ["❌", "🧻"])
        self.cache.setdefault(ctx.guild.id, {})[msg.id] = event

    @commands.Cog.listener()
    async def on_member_leave(self, member: discord.Member):
        if member.guild.id not in self.cache:
            return

        for event in self.cache[member.guild.id].values():
            if entrant := event.get_entrant(member.id):
                event.remove_entrant(entrant)
                msg = await event.message()
                if not msg:
                    continue

                await msg.edit(embed=event.embed)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if not payload.guild_id:
            return

        if not (data := self.cache.get(payload.guild_id)):
            return

        if not (event := data.get(payload.message_id)):
            return

        message = await event.message()

        if not message:
            return  # idk what could be the reason message is none tbh.

        user: Optional[discord.User] = self.bot.get_user(payload.user_id)

        if not user:
            return

        if user.bot:
            return

        emoji = str(payload.emoji)

        if not emoji in emoji_class_dict and emoji not in ["❌", "🧻"]:
            try:
                await message.remove_reaction(emoji, user)
                # to not clutter the menu with useless reactions
            except Exception:
                pass
            return

        if emoji in emoji_class_dict:

            if entrant := event.get_entrant(user.id):
                emoji_to_remove = class_spec_dict[entrant.category_class]["emoji"]
                try:
                    await message.remove_reaction(emoji_to_remove, user)
                except Exception:
                    pass

            class_name = emoji_class_dict[emoji]

            details = class_spec_dict[class_name]

            valid_specs = [(k, v["emoji"]) for k, v in details["specs"].items()]

            embed = discord.Embed(
                title="Select a spec for the class {}".format(class_name),
                description="\n".join(
                    f"{ind+1}. {spec[1]} {spec[0]}" for ind, spec in enumerate(valid_specs)
                )
                + "\nSend the correct number to select a spec.",
                color=discord.Color.green(),
            )
            try:
                await user.send(embed=embed)

            except Exception:
                await message.channel.send(
                    f"I couldn't dm you to select a spec {user.mention}.\nMake sure your dms are open."
                )
                return

            answer = None
            while answer is None:
                try:
                    msg = await self.bot.wait_for(
                        "message",
                        check=lambda m: m.author == user
                        and not m.guild
                        and m.channel.recipient == user,
                        timeout=60,
                    )

                except asyncio.TimeoutError:
                    await user.send("You took too long to respond. Cancelling.")
                    try:
                        await message.remove_reaction(emoji, user)
                    except Exception:
                        pass
                    return

                if not msg.content.isdigit() or int(msg.content) not in [
                    i + 1 for i in range(len(valid_specs))
                ]:
                    await user.send(
                        f"That's not a valid answer. You must write a number from 1 to {len(valid_specs)}"
                    )
                    continue

                answer = int(msg.content)

            spec = valid_specs[answer - 1][0]

            event.add_entrant(user.id, class_name, details["specs"][spec]["categories"][0], spec)

            await user.send("You have been signed up to the event.")

            embed = event.embed

            await message.edit(embed=embed)

            try:
                await message.remove_reaction(emoji, user)
            except Exception:
                pass

        elif emoji == "❌":
            if not event.author_id == user.id:
                try:
                    await message.remove_reaction(emoji, user)
                except Exception:
                    pass
                return

            try:
                await message.clear_reactions()

            except Exception:
                pass

            embed = event.end()

            await user.send("The event was ended.")

            await message.edit(embed=embed)

        elif emoji == "🧻":
            try:
                await message.remove_reaction(emoji, user)

            except Exception:
                pass

            if entrant := event.get_entrant(user.id):
                event.remove_entrant(entrant)

                await user.send("You have been removed from the event.")

                await message.edit(embed=event.embed)

            else:
                await user.send("You weren't signed up to the event.")

    @tasks.loop(minutes=2)
    async def check_events(self):
        
        await self.to_config()
        
        await self.cache.clear()
        
        await self.to_cache()
        
        for guild_config in self.cache.copy().values():
            for event in guild_config.values():
                if event.end_time.timestamp() <= time.time():
                    embed = event.end()
                    msg = await event.message()
                    
                    if not msg:
                        continue
                    
                    await msg.edit(embed=embed)
                    
                    