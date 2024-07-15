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
    "id" SERIAL NOT NULL PRIMARY KEY,
    "version" VARCHAR(255) NOT NULL,
    "app" VARCHAR(20) NOT NULL,
    "content" JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS "feed" (
    "created_at" TIMESTAMPTZ NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "id" SERIAL NOT NULL PRIMARY KEY,
    "state" SMALLINT NOT NULL  DEFAULT 1,
    "link" VARCHAR(4096) NOT NULL UNIQUE,
    "title" VARCHAR(1024) NOT NULL,
    "interval" SMALLINT,
    "entry_hashes" TEXT,
    "etag" VARCHAR(128),
    "error_count" SMALLINT NOT NULL  DEFAULT 0,
    "next_check_time" TIMESTAMPTZ
);
COMMENT ON COLUMN "feed"."created_at" IS 'The time this row was created';
COMMENT ON COLUMN "feed"."updated_at" IS 'The time this row was updated';
COMMENT ON COLUMN "feed"."state" IS 'Feed state: 0=deactivated, 1=activated';
COMMENT ON COLUMN "feed"."link" IS 'Feed link';
COMMENT ON COLUMN "feed"."title" IS 'Feed title';
COMMENT ON COLUMN "feed"."interval" IS 'Monitoring task interval. Should be the minimal interval of all subs to the feed,default interval will be applied if null';
COMMENT ON COLUMN "feed"."entry_hashes" IS 'Hashes (CRC32) of entries';
COMMENT ON COLUMN "feed"."etag" IS 'The etag of webpage, will be changed each time the feed is updated. Can be null because some websites do not support';
COMMENT ON COLUMN "feed"."error_count" IS 'Error counts. If too many, deactivate the feed. +1 if an error occurs, reset to 0 if feed fetched successfully';
COMMENT ON COLUMN "feed"."next_check_time" IS 'Next checking time. If too many errors occur, let us wait sometime';
COMMENT ON TABLE "feed" IS 'Feed model.';
CREATE TABLE IF NOT EXISTS "option" (
    "created_at" TIMESTAMPTZ NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "id" SERIAL NOT NULL PRIMARY KEY,
    "key" VARCHAR(255) NOT NULL UNIQUE,
    "value" TEXT
);
COMMENT ON COLUMN "option"."created_at" IS 'The time this row was created';
COMMENT ON COLUMN "option"."updated_at" IS 'The time this row was updated';
COMMENT ON TABLE "option" IS 'Option model.';
CREATE TABLE IF NOT EXISTS "user" (
    "created_at" TIMESTAMPTZ NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "id" BIGSERIAL NOT NULL PRIMARY KEY,
    "state" SMALLINT NOT NULL  DEFAULT 0,
    "lang" VARCHAR(16) NOT NULL  DEFAULT 'zh-Hans',
    "admin" BIGINT
);
COMMENT ON COLUMN "user"."created_at" IS 'The time this row was created';
COMMENT ON COLUMN "user"."updated_at" IS 'The time this row was updated';
COMMENT ON COLUMN "user"."id" IS 'Telegram user id, 8Bytes';
COMMENT ON COLUMN "user"."state" IS 'User state: -1=banned, 0=guest, 1=user, 50=channel, 51=group, 100=admin';
COMMENT ON COLUMN "user"."lang" IS 'Preferred language, lang code';
COMMENT ON COLUMN "user"."admin" IS 'One of the admins of the channel or group, can be null if this \"user\" is not a channel or a group';
COMMENT ON TABLE "user" IS 'User model.';
CREATE TABLE IF NOT EXISTS "sub" (
    "created_at" TIMESTAMPTZ NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "id" SERIAL NOT NULL PRIMARY KEY,
    "state" SMALLINT NOT NULL  DEFAULT 1,
    "tags" VARCHAR(255),
    "interval" SMALLINT,
    "notify" SMALLINT NOT NULL  DEFAULT 1,
    "send_mode" SMALLINT NOT NULL  DEFAULT 0,
    "length_limit" SMALLINT NOT NULL  DEFAULT 0,
    "link_preview" SMALLINT NOT NULL  DEFAULT 0,
    "display_author" SMALLINT NOT NULL  DEFAULT 0,
    "display_via" SMALLINT NOT NULL  DEFAULT 0,
    "display_title" SMALLINT NOT NULL  DEFAULT 0,
    "style" SMALLINT NOT NULL  DEFAULT 0,
    "feed_id" INT NOT NULL REFERENCES "feed" ("id") ON DELETE CASCADE,
    "user_id" BIGINT NOT NULL REFERENCES "user" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_sub_user_id_029239" UNIQUE ("user_id", "feed_id")
);
COMMENT ON COLUMN "sub"."created_at" IS 'The time this row was created';
COMMENT ON COLUMN "sub"."updated_at" IS 'The time this row was updated';
COMMENT ON COLUMN "sub"."state" IS 'Sub state: 0=deactivated, 1=activated';
COMMENT ON COLUMN "sub"."tags" IS 'Tags of the sub';
COMMENT ON COLUMN "sub"."interval" IS 'Interval of the sub monitor task, default interval will be applied if null';
COMMENT ON COLUMN "sub"."notify" IS 'Enable notification or not? 0: disable, 1=enable';
COMMENT ON COLUMN "sub"."send_mode" IS 'Send mode: -1=force link, 0=auto, 1=force Telegraph, 2=force message';
COMMENT ON COLUMN "sub"."length_limit" IS 'Telegraph length limit, valid when send_mode==0. If exceed, send via Telegraph; If is 0, send via Telegraph when a post cannot be send in a single message';
COMMENT ON COLUMN "sub"."link_preview" IS 'Enable link preview or not? 0=auto, 1=force enable';
COMMENT ON COLUMN "sub"."display_author" IS 'Display author or not?-1=disable, 0=auto, 1=force display';
COMMENT ON COLUMN "sub"."display_via" IS 'Display via or not?-2=completely disable, -1=disable but display link, 0=auto, 1=force display';
COMMENT ON COLUMN "sub"."display_title" IS 'Display title or not?-1=disable, 0=auto, 1=force display';
COMMENT ON COLUMN "sub"."style" IS 'Style of posts: 0=RSStT, 1=flowerss';
COMMENT ON TABLE "sub" IS 'Sub model.';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """
