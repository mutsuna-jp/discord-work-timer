import pytest
import asyncio

from types import SimpleNamespace

import discord
from datetime import datetime, timedelta

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
    cog._daily_message_id = None
    cog._ranking_embed_title = MESSAGES.get("rank", {}).get("embed_title", "🏆 今週の作業時間ランキング")
    return cog


def test_is_ranking_message_and_filter():
    cog = make_cog_without_init()

    ranking_msg = FakeMessage(123, embeds=[FakeEmbed(title=cog._ranking_embed_title)])
    # server total title from config
    server_title = MESSAGES.get("rank", {}).get("server_total_title", "本日のサーバー合計作業時間")
    server_msg = FakeMessage(124, embeds=[FakeEmbed(title=server_title)])
    other_msg = FakeMessage(456, embeds=[FakeEmbed(title="Other")])

    assert cog._is_ranking_message(ranking_msg)
    assert not cog._is_ranking_message(other_msg)

    msgs = [ranking_msg, other_msg]
    filtered = cog._filter_status_messages(msgs)

    assert len(filtered) == 1
    assert filtered[0].id == other_msg.id
    assert cog._ranking_message_id == ranking_msg.id
    # server message should be recognized when present
    msgs2 = [ranking_msg, server_msg, other_msg]
    filtered2 = cog._filter_status_messages(msgs2)
    assert cog._daily_message_id == server_msg.id


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

    # Server Total should be available as a separate embed
    server_embed = await StatusCog._build_server_total_embed(cog)
    assert any(field.name == "本日のサーバー合計作業時間" for field in server_embed.fields)


@pytest.mark.asyncio
async def test_build_ranking_embed_includes_server_total_with_data():
    # Prepare a fake DB with today's logs and weekly ranking
    class DummyDB:
        async def get_weekly_ranking(self, monday_iso):
            return [("Alice", 7200), ("Bob", 3600)]

        async def get_random_tip(self):
            return None

        async def get_study_logs_in_range(self, start_date, end_date=None):
            # Return tuples (user_id, username, total_time)
            return [(1, "Alice", 7200), (2, "Bob", 3600)]

    class DummyBot:
        def __init__(self):
            self.db = DummyDB()

        def get_cog(self, name):
            # Simulate one active user with 30 minutes elapsed
            if name == "StudyCog":
                return SimpleNamespace(voice_state_log={3: datetime.now() - timedelta(minutes=30)}, voice_state_offset={})
            return None

    cog = make_cog_without_init()
    cog.bot = DummyBot()

    # Ranking embed should NOT contain server total; server total is separate
    embed = await StatusCog._build_ranking_embed(cog)
    server_fields_in_rank = [f for f in embed.fields if f.name == "本日のサーバー合計作業時間"]
    assert len(server_fields_in_rank) == 0

    server_embed = await StatusCog._build_server_total_embed(cog)
    server_fields = [f for f in server_embed.fields if f.name == "本日のサーバー合計作業時間"]
    assert len(server_fields) == 1
    assert server_fields[0].value.startswith("**")


@pytest.mark.asyncio
async def test_build_ranking_embed_includes_active_users_in_ranking():
    # Prepare a fake DB with weekly ranking and a bot with an active user not in DB
    class DummyDB:
        async def get_weekly_ranking(self, monday_iso):
            return [("Alice", 7200), ("Bob", 3600)]

        async def get_random_tip(self):
            return None

        async def get_study_logs_in_range(self, start_date, end_date=None):
            return [(1, "Alice", 7200), (2, "Bob", 3600)]

    class DummyBot:
        def __init__(self):
            self.db = DummyDB()

        def get_cog(self, name):
            if name == "StudyCog":
                # Active user 3 has been working for 30 minutes
                return SimpleNamespace(voice_state_log={3: datetime.now() - timedelta(minutes=30)}, voice_state_offset={})
            return None

        def get_user(self, user_id):
            # Return a fake user object for active user
            if user_id == 3:
                return SimpleNamespace(display_name="Charlie", name="Charlie")
            return None

    cog = make_cog_without_init()
    cog.bot = DummyBot()

    embed = await StatusCog._build_ranking_embed(cog)
    # Ensure the Top Members field contains Charlie and that Alice's time has been augmented if applicable
    top_field = next((f for f in embed.fields if f.name == "Top Members"), None)
    assert top_field is not None
    assert "Charlie" in top_field.value
    # Charlie should show roughly 30 minutes ("30分") in the formatted text
    assert "30分" in top_field.value


@pytest.mark.asyncio
async def test_upsert_ranking_message_sends_if_none_exists():
    # Minimal fake channel that has no existing messages and supports send()
    class FakeChannel:
        def __init__(self):
            self._sent = []

        async def history(self, limit=50):
            # empty async iterator
            if False:
                yield None

        async def send(self, embed=None):
            # emulate discord.Message with id
            self._sent.append(embed)
            return SimpleNamespace(id=999)

    cog = make_cog_without_init()

    class DummyDB:
        async def get_weekly_ranking(self, monday_iso):
            return []

        async def get_random_tip(self):
            return None

    class DummyBot:
        def __init__(self):
            self.db = DummyDB()

    cog.bot = DummyBot()

    fake_channel = FakeChannel()
    # call upsert; should set _ranking_message_id to returned id
    embed = await StatusCog._build_ranking_embed(cog)
    await StatusCog._upsert_ranking_message(cog, fake_channel, embed)
    assert cog._ranking_message_id == 999

    # The ranking embed should NOT include Server Total
    sent_rank = fake_channel._sent[-1]
    assert not any(field.name == "本日のサーバー合計作業時間" for field in sent_rank.fields)

    # Now upsert server total and ensure daily message id is set and embed includes Server Total
    server_embed = await StatusCog._build_server_total_embed(cog)
    await StatusCog._upsert_server_total_message(cog, fake_channel, server_embed)
    assert cog._daily_message_id == 999
    sent_server = fake_channel._sent[-1]
    assert any(field.name == "本日のサーバー合計作業時間" for field in sent_server.fields)


@pytest.mark.asyncio
async def test_update_weekly_ranking_posts_if_channel_exists(monkeypatch):
    # Prepare fake channel and bot
    class FakeChannel:
        def __init__(self):
            self._sent = []

        async def history(self, limit=50):
            if False:
                yield None

        async def send(self, embed=None):
            self._sent.append(embed)
            return SimpleNamespace(id=999)

    cog = make_cog_without_init()

    class DummyDB:
        async def get_weekly_ranking(self, monday_iso):
            return []

        async def get_random_tip(self):
            return None

    class DummyBot:
        def __init__(self, channel):
            self.db = DummyDB()
            self._channel = channel

        def get_channel(self, cid):
            return self._channel

    fake_channel = FakeChannel()
    cog.bot = DummyBot(fake_channel)

    # Ensure STATUS_CHANNEL_ID is set
    from config import Config
    Config.STATUS_CHANNEL_ID = 123

    # Bypass permission checks for simplicity
    cog._check_channel_permissions = lambda channel, ctx: True

    await StatusCog.update_weekly_ranking(cog)
    assert fake_channel._sent is not None
    assert cog._ranking_message_id == 999

    # Ranking should not include server total
    sent_rank = fake_channel._sent[-1]
    assert not any(field.name == "本日のサーバー合計作業時間" for field in sent_rank.fields)

    # Now call update_daily_server_total and check it's posted
    await StatusCog.update_daily_server_total(cog)
    assert cog._daily_message_id == 999
    assert any(field.name == "本日のサーバー合計作業時間" for field in fake_channel._sent[-1].fields)


@pytest.mark.asyncio
async def test_update_weekly_ranking_no_channel_configured():
    cog = make_cog_without_init()
    # Ensure STATUS_CHANNEL_ID is 0 (not configured)
    from config import Config
    Config.STATUS_CHANNEL_ID = 0

    # Should not raise
    await StatusCog.update_weekly_ranking(cog)
