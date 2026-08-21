"""レーティングに応じたランクロールの自動作成・付け替え"""
import logging

import discord

from rating_ranks import RANK_TIERS, RANK_ROLE_NAMES, get_rank_info

logger = logging.getLogger("TensokuMatchBot")


async def ensure_rank_role(guild: discord.Guild, tier: dict) -> discord.Role | None:
    """指定ランクのロールを取得する。存在しなければ自動作成する"""
    role = discord.utils.get(guild.roles, name=tier["name"])
    if role is not None:
        return role
    try:
        return await guild.create_role(
            name=tier["name"],
            color=discord.Color(tier["color"]),
            mentionable=False,
            reason="レーティングランクロールの自動作成",
        )
    except discord.Forbidden:
        logger.warning(f"rank_role: ロール作成失敗（権限不足） guild={guild.id} name={tier['name']}")
        return None


async def sync_rank_role(member: discord.Member, rating: float) -> None:
    """メンバーの現在のレートに応じたランクロールを付与し、他のランク帯のロールを外す"""
    guild = member.guild
    tier = get_rank_info(rating)
    target_role = await ensure_rank_role(guild, tier)
    if target_role is None:
        return

    stale = [r for r in member.roles if r.name in RANK_ROLE_NAMES and r.id != target_role.id]
    try:
        if stale:
            await member.remove_roles(*stale, reason="レーティングランク更新")
        if target_role not in member.roles:
            await member.add_roles(target_role, reason="レーティングランク更新")
    except discord.Forbidden:
        logger.warning(f"rank_role: ロール付け替え失敗（権限不足） user={member.id}")


async def ensure_all_rank_roles(guild: discord.Guild) -> list[discord.Role]:
    """9段階すべてのランクロールを作成（既存分はそのまま）し、作成済みロールの一覧を返す"""
    roles = []
    for tier in RANK_TIERS:
        role = await ensure_rank_role(guild, tier)
        if role is not None:
            roles.append(role)
    return roles
