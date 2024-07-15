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

from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "aerich" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "version" VARCHAR(255) NOT NULL,
    "app" VARCHAR(20) NOT NULL,
    "content" JSON NOT NULL
);
CREATE TABLE IF NOT EXISTS "feed" (
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP /* The time this row was created */,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP /* The time this row was updated */,
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "state" SMALLINT NOT NULL  DEFAULT 1 /* Feed state: 0=deactivated, 1=activated */,
    "link" VARCHAR(4096) NOT NULL UNIQUE /* Feed link */,
    "title" VARCHAR(1024) NOT NULL  /* Feed title */,
    "interval" SMALLINT   /* Monitoring task interval. Should be the minimal interval of all subs to the feed,default interval will be applied if null */,
    "entry_hashes" TEXT   /* Hashes (CRC32) of entries */,
    "etag" VARCHAR(128)   /* The etag of webpage, will be changed each time the feed is updated. Can be null because some websites do not support */,
    "error_count" SMALLINT NOT NULL  DEFAULT 0 /* Error counts. If too many, deactivate the feed. +1 if an error occurs, reset to 0 if feed fetched successfully */,
    "next_check_time" TIMESTAMP   /* Next checking time. If too many errors occur, let us wait sometime */
) /* Feed model. */;
CREATE TABLE IF NOT EXISTS "option" (
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP /* The time this row was created */,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP /* The time this row was updated */,
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "key" VARCHAR(255) NOT NULL UNIQUE,
    "value" TEXT
) /* Option model. */;
CREATE TABLE IF NOT EXISTS "user" (
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP /* The time this row was created */,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP /* The time this row was updated */,
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL /* Telegram user id, 8Bytes */,
    "state" SMALLINT NOT NULL  DEFAULT 0 /* User state: -1=banned, 0=guest, 1=user, 50=channel, 51=group, 100=admin */,
    "lang" VARCHAR(16) NOT NULL  DEFAULT 'zh-Hans' /* Preferred language, lang code */,
    "admin" BIGINT   /* One of the admins of the channel or group, can be null if this "user" is not a channel or a group */
) /* User model. */;
CREATE TABLE IF NOT EXISTS "sub" (
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP /* The time this row was created */,
    "updated_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP /* The time this row was updated */,
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "state" SMALLINT NOT NULL  DEFAULT 1 /* Sub state: 0=deactivated, 1=activated */,
    "tags" VARCHAR(255)   /* Tags of the sub */,
    "interval" SMALLINT   /* Interval of the sub monitor task, default interval will be applied if null */,
    "notify" SMALLINT NOT NULL  DEFAULT 1 /* Enable notification or not? 0: disable, 1=enable */,
    "send_mode" SMALLINT NOT NULL  DEFAULT 0 /* Send mode: -1=force link, 0=auto, 1=force Telegraph, 2=force message */,
    "length_limit" SMALLINT NOT NULL  DEFAULT 0 /* Telegraph length limit, valid when send_mode==0. If exceed, send via Telegraph; If is 0, send via Telegraph when a post cannot be send in a single message */,
    "link_preview" SMALLINT NOT NULL  DEFAULT 0 /* Enable link preview or not? 0=auto, 1=force enable */,
    "display_author" SMALLINT NOT NULL  DEFAULT 0 /* Display author or not?-1=disable, 0=auto, 1=force display */,
    "display_via" SMALLINT NOT NULL  DEFAULT 0 /* Display via or not?-2=completely disable, -1=disable but display link, 0=auto, 1=force display */,
    "display_title" SMALLINT NOT NULL  DEFAULT 0 /* Display title or not?-1=disable, 0=auto, 1=force display */,
    "style" SMALLINT NOT NULL  DEFAULT 0 /* Style of posts: 0=RSStT, 1=flowerss */,
    "feed_id" INT NOT NULL REFERENCES "feed" ("id") ON DELETE CASCADE,
    "user_id" BIGINT NOT NULL REFERENCES "user" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_sub_user_id_029239" UNIQUE ("user_id", "feed_id")
) /* Sub model. */;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """
