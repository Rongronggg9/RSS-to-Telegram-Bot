#  RSS to Telegram Bot
#  Copyright (C) 2022-2024  Rongrong <i@rong.moe>
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
        ALTER TABLE "sub" ADD "display_media" SMALLINT NOT NULL  DEFAULT 0;
ALTER TABLE "user" ADD "send_mode" SMALLINT NOT NULL  DEFAULT 0;
ALTER TABLE "user" ADD "display_author" SMALLINT NOT NULL  DEFAULT 0;
ALTER TABLE "user" ADD "display_media" SMALLINT NOT NULL  DEFAULT 0;
ALTER TABLE "user" ADD "display_title" SMALLINT NOT NULL  DEFAULT 0;
ALTER TABLE "user" ADD "notify" SMALLINT NOT NULL  DEFAULT 1;
ALTER TABLE "user" ADD "link_preview" SMALLINT NOT NULL  DEFAULT 0;
ALTER TABLE "user" ADD "style" SMALLINT NOT NULL  DEFAULT 0;
ALTER TABLE "user" ADD "length_limit" SMALLINT NOT NULL  DEFAULT 0;
ALTER TABLE "user" ADD "interval" SMALLINT;
ALTER TABLE "user" ADD "display_via" SMALLINT NOT NULL  DEFAULT 0;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "sub" DROP COLUMN "display_media";
ALTER TABLE "user" DROP COLUMN "send_mode";
ALTER TABLE "user" DROP COLUMN "display_author";
ALTER TABLE "user" DROP COLUMN "display_media";
ALTER TABLE "user" DROP COLUMN "display_title";
ALTER TABLE "user" DROP COLUMN "notify";
ALTER TABLE "user" DROP COLUMN "link_preview";
ALTER TABLE "user" DROP COLUMN "style";
ALTER TABLE "user" DROP COLUMN "length_limit";
ALTER TABLE "user" DROP COLUMN "interval";
ALTER TABLE "user" DROP COLUMN "display_via";"""
