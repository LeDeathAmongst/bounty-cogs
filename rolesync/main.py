from operator import attrgetter

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from .views import GuildSelectView


class RoleSync(commands.Cog):
    """A cog that syncs roles and their properties across multiple servers."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=1234567890, force_registration=True
        )
        self.config.register_guild(roles={}, synced_roles={})

    @commands.group(name="rolesync", aliases=["rsync"], invoke_without_command=True)
    @commands.guild_only()
    @commands.is_owner()
    async def rs(self, ctx: commands.Context):
        """Sync role states between guilds"""
        await ctx.send_help()

    @rs.command(name="add")
    async def rs_add(self, ctx: commands.Context, role: discord.Role, *guild_ids: int):
        """Add a role to sync between guilds

        The role argument must be a role mention or ID.
        The guild_ids argument accepts multiple guild IDs"""
        if len(guild_ids) < 1:
            return await ctx.send("Please provide at least one guild ID to sync with.")

        guilds = [self.bot.get_guild(gid) for gid in guild_ids if self.bot.get_guild(gid)]
        if not guilds:
            return await ctx.send("No valid guilds found with the provided IDs.")

        async with self.config.guild(ctx.guild).roles() as roles:
            roles[str(role.id)] = list(
                set(roles.get(str(role.id), [])).union(map(lambda g: g.id, guilds))
            )

            for guild in guilds:
                async with self.config.guild(guild).synced_roles() as synced_roles:
                    if str(role.id) not in synced_roles:
                        synced_roles[str(role.id)] = (
                            await guild.create_role(
                                name=role.name,
                                permissions=role.permissions,
                                colour=role.colour,
                                hoist=role.hoist,
                                mentionable=role.mentionable,
                                reason=f"Synced from {ctx.guild.name}",
                            )
                        ).id

        await ctx.tick()
        return await ctx.send(f"Synced {role.mention} in the specified guilds")

    @rs.command(name="remove")
    async def rs_remove(self, ctx: commands.Context, role: discord.Role, *guild_ids: int):
        """Remove a role from sync in specified guilds

        If no guild IDs are provided, the role will be removed from all synced guilds."""
        async with self.config.guild(ctx.guild).roles() as roles:
            if str(role.id) not in roles:
                return await ctx.send("This role is not synced to any guilds.")

            guilds_to_remove = guild_ids if guild_ids else roles[str(role.id)]
            for gid in guilds_to_remove:
                guild = self.bot.get_guild(gid)
                if guild is None:
                    continue

                async with self.config.guild(guild).synced_roles() as synced_roles:
                    if str(role.id) in synced_roles:
                        sr = guild.get_role(synced_roles[str(role.id)])
                        if sr is None:
                            continue
                        await sr.delete(reason=f"Unsynced from {ctx.guild.name}")
                        del synced_roles[str(role.id)]

                roles[str(role.id)].remove(gid)

            if not roles[str(role.id)]:
                del roles[str(role.id)]

        await ctx.tick()
        return await ctx.send(f"Removed {role.mention} from sync in specified guilds")

    @rs.command(name="list")
    async def rs_list(self, ctx: commands.Context):
        """List synced roles"""
        roles = await self.config.guild(ctx.guild).roles()
        if not roles:
            return await ctx.send("No roles are synced in this guild.")

        msg = ""
        for role_id, guilds in roles.items():
            role = ctx.guild.get_role(int(role_id))
            if role is None:
                continue

            msg += f"- {role.mention} synced in {len(guilds)} guilds\n"
            for gid in guilds:
                guild = self.bot.get_guild(gid)
                if guild is None:
                    continue
                role = guild.get_role(
                    await self.config.guild(guild).synced_roles.get_raw(role_id)
                )
                if not role:
                    continue
                msg += f"\t- {guild.name}: {role.id}\n"

            msg += "\n"

        await ctx.send(msg)

    @rs.command(name="forcesync", aliases=["fsync"])
    async def rs_fsync(self, ctx: commands.Context):
        roles = await self.config.guild(ctx.guild).roles()
        if not roles:
            return await ctx.send("No roles are synced in this guild.")

        for role_id, guilds in roles.items():
            role = ctx.guild.get_role(int(role_id))
            role1 = {
                "name": role.name,
                "permissions": role.permissions,
                "colour": role.colour,
                "hoist": role.hoist,
                "mentionable": role.mentionable,
            }
            if role is None:
                continue

            for gid in guilds:
                guild = self.bot.get_guild(gid)
                if guild is None:
                    continue
                r = guild.get_role(
                    await self.config.guild(guild).synced_roles.get_raw(str(role_id))
                )
                if not role:
                    continue
                role2 = {
                    "name": r.name,
                    "permissions": r.permissions,
                    "colour": r.colour,
                    "hoist": r.hoist,
                    "mentionable": r.mentionable,
                }
                if role1 != role2:
                    await role.edit(
                        name=role.name,
                        permissions=role.permissions,
                        colour=role.colour,
                        hoist=role.hoist,
                        mentionable=role.mentionable,
                    )

        await ctx.tick()

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        async with self.config.guild(before.guild).roles() as roles:
            if str(before.id) not in roles:
                return

            for gid in roles[str(before.id)]:
                guild = self.bot.get_guild(gid)
                if guild is None:
                    continue

                async with self.config.guild(guild).synced_roles() as synced_roles:
                    if str(before.id) in synced_roles:
                        sr = guild.get_role(synced_roles[str(before.id)])
                        if sr is None:
                            continue
                        await sr.edit(
                            name=after.name,
                            permissions=after.permissions,
                            colour=after.colour,
                            hoist=after.hoist,
                            mentionable=after.mentionable,
                        )
