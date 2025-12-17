import pytest
import asyncio

from types import SimpleNamespace

import discord

from cogs.status import StatusCog
from messages import MESSAGES


class FakeEmbed:
    def __init__(self, title=None):
        self.title = title


class FakeMessage:
    def __init__(self, id_, embeds=None):
        self.id = id_
        self.embeds = embeds or []


def make_cog_without_init():
    # Create instance without running __init__ (avoid starting tasks)
    cog = object.__new__(StatusCog)
    cog._ranking_message_id = None
    cog._ranking_embed_title = MESSAGES.get("rank", {}).get("embed_title", "🏆 今週の作業時間ランキング")
    return cog


def test_is_ranking_message_and_filter():
    cog = make_cog_without_init()

    ranking_msg = FakeMessage(123, embeds=[FakeEmbed(title=cog._ranking_embed_title)])
    other_msg = FakeMessage(456, embeds=[FakeEmbed(title="Other")])

    assert cog._is_ranking_message(ranking_msg)
    assert not cog._is_ranking_message(other_msg)

    msgs = [ranking_msg, other_msg]
    filtered = cog._filter_status_messages(msgs)

    assert len(filtered) == 1
    assert filtered[0].id == other_msg.id
    assert cog._ranking_message_id == ranking_msg.id


@pytest.mark.asyncio
async def test_build_ranking_embed_empty():
    # Prepare a fake bot with a db that returns empty ranking
    class DummyDB:
        async def get_weekly_ranking(self, monday_iso):
            return []

        async def get_random_tip(self):
            return None

    class DummyBot:
        def __init__(self):
            self.db = DummyDB()

    # Build a cog-like object to call _build_ranking_embed
    cog = make_cog_without_init()
    cog.bot = DummyBot()

    embed = await StatusCog._build_ranking_embed(cog)
    rank_config = MESSAGES.get("rank", {})
    expected = rank_config.get("empty_message", "今週はまだ誰も作業していません...！")
    assert embed.description == expected
