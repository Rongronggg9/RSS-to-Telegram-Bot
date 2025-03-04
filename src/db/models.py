"""
RSStT db models
"""
#  RSS to Telegram Bot
#  Copyright (C) 2021-2024  Rongrong <i@rong.moe>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class Base:
    """
    Model template.

    Contains `created_at` and `updated_at`.
    """
    created_at = fields.DatetimeField(auto_now_add=True, description='The time this row was created')
    updated_at = fields.DatetimeField(auto_now=True, description='The time this row was updated')


class User(Model, Base):
    """
    User model.

    Stores users, their info and their default feed options.
    """
    id = fields.BigIntField(pk=True, description='Telegram user id, 8Bytes')
    state = fields.SmallIntField(
        default=0,
        description='User state: '
                    '-1=banned, 0=guest, 1=user, 50=channel, 51=group, 100=admin',
    )
    lang = fields.CharField(default='zh-Hans', max_length=16, description='Preferred language, lang code')
    admin = fields.BigIntField(
        null=True,
        description='One of the admins of the channel or group, can be null if this "user" is not a channel or a group',
    )
    sub_limit = fields.SmallIntField(null=True, description='Subscription number limit')

    subs: fields.ReverseRelation['Sub']

    # default options of a user's feeds
    interval = fields.SmallIntField(null=True)
    notify = fields.SmallIntField(default=1)
    send_mode = fields.SmallIntField(default=0)
    length_limit = fields.SmallIntField(default=0)
    link_preview = fields.SmallIntField(default=0)
    display_author = fields.SmallIntField(default=0)
    display_via = fields.SmallIntField(default=0)
    display_title = fields.SmallIntField(default=0)
    display_entry_tags = fields.SmallIntField(default=-1)
    style = fields.SmallIntField(default=0)
    display_media = fields.SmallIntField(default=0)

    class Meta:
        table = 'user'

    def __str__(self):
        return self.id


class Feed(Model, Base):
    """
    Feed model.

    Stores feeds and their info.
    """
    id = fields.IntField(pk=True)
    state = fields.SmallIntField(
        default=1,
        description='Feed state: '
                    '0=deactivated, 1=activated',
    )
    link = fields.CharField(
        max_length=4096,  # hey, is there really any rss feed url > 4096B?
        unique=True,  # will also be indexed
        description='Feed link',
    )
    title = fields.CharField(max_length=1024, description='Feed title')
    interval = fields.SmallIntField(
        null=True,
        description='Monitoring task interval. '
                    'Should be the minimal interval of all subs to the feed,'
                    'default interval will be applied if null',
    )
    entry_hashes = fields.JSONField(null=True, description='Hashes (CRC32) of entries')
    etag = fields.CharField(
        max_length=128,
        null=True,
        description='The etag of webpage, will be changed each time the feed is updated. '
                    'Can be null because some websites do not support',
    )
    last_modified = fields.DatetimeField(null=True, description='The last modified time of webpage. ')
    error_count = fields.SmallIntField(
        default=0,
        description='Error counts. If too many, deactivate the feed. '
                    '+1 if an error occurs, reset to 0 if feed fetched successfully',
    )
    next_check_time = fields.DatetimeField(
        null=True,
        description='Next checking time. '
                    'If too many errors occur, let us wait sometime',
    )
    subs: fields.ReverseRelation['Sub']

    class Meta:
        table = 'feed'

    def __str__(self):
        return self.link


# TODO: migrate the default value of all fields after `notify` (inclusive) to -100
# TODO: description makes a lot trouble on SQLite, remove the description of all fields after `notify` (inclusive)
class Sub(Model, Base):
    """
    Sub model.

    Stores subscriptions (who subscribed which feed) and their options, many to many relation.
    """
    id = fields.IntField(pk=True)
    state = fields.SmallIntField(
        default=1,
        description='Sub state: '
                    '0=deactivated, 1=activated',
    )
    user: fields.ForeignKeyRelation['User'] = fields.ForeignKeyField(
        'models.User',
        related_name='subs',
        to_field='id',
        on_delete=fields.CASCADE,
    )
    user_id: int  # type hint stub
    feed: fields.ForeignKeyRelation['Feed'] = fields.ForeignKeyField(
        'models.Feed',
        related_name='subs',
        to_field='id',
        on_delete=fields.CASCADE,
    )
    feed_id: int  # type hint stub
    title = fields.CharField(max_length=1024, null=True, description='Sub title, overriding feed title if set')
    tags = fields.CharField(max_length=255, null=True, description='Tags of the sub')
    interval = fields.SmallIntField(
        null=True,
        description='Interval of the sub monitor task, '
                    'default interval will be applied if null',
    )
    notify = fields.SmallIntField(
        default=1,
        description='Enable notification or not? '
                    '0: disable, 1=enable',
    )
    send_mode = fields.SmallIntField(
        default=0,
        description='Send mode: '
                    '-1=force link, 0=auto, 1=force Telegraph, 2=force message',
    )
    length_limit = fields.SmallIntField(
        default=0,
        description='Telegraph length limit, valid when send_mode==0. '
                    'If exceed, send via Telegraph; '
                    'If is 0, send via Telegraph when a post cannot be send in a single message',
    )
    link_preview = fields.SmallIntField(
        default=0,
        description='Enable link preview or not? '
                    '0=auto, 1=force enable',
    )
    display_author = fields.SmallIntField(
        default=0,
        description='Display author or not?'
                    '-1=disable, 0=auto, 1=force display',
    )
    display_via = fields.SmallIntField(
        default=0,
        description='Display via or not?'
                    '-2=completely disable, -1=disable but display link, 0=auto, 1=force display',
    )
    display_title = fields.SmallIntField(
        default=0,
        description='Display title or not?'
                    '-1=disable, 0=auto, 1=force display',
    )
    # new field, use the de facto default value (-100) and with description unset to avoid future migration
    display_entry_tags = fields.SmallIntField(default=-100)
    style = fields.SmallIntField(
        default=0,
        description='Style of posts: '
                    '0=RSStT, 1=flowerss',
    )
    display_media = fields.SmallIntField(
        default=0,
        description='Display media or not?'
                    '-1=disable, 0=enable',
    )

    class Meta:
        table = 'sub'
        unique_together = ('user_id', 'feed_id')  # will also be indexed


class Option(Model, Base):
    """
    Option model.

    Stores options set by admins.
    """
    id = fields.IntField(pk=True)
    key = fields.CharField(max_length=255, unique=True)  # will also be indexed
    value = fields.TextField(null=True)

    class Meta:
        table = 'option'
