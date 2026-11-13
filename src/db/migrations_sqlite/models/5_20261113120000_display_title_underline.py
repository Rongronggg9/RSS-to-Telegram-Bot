from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "sub" ADD "display_title_underline" SMALLINT NOT NULL  DEFAULT -100;
        ALTER TABLE "user" ADD "display_title_underline" SMALLINT NOT NULL  DEFAULT 1;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "sub" DROP COLUMN "display_title_underline";
        ALTER TABLE "user" DROP COLUMN "display_title_underline";"""
