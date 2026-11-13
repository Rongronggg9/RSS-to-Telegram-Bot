from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "sub" ADD "title_underline" SMALLINT NOT NULL  DEFAULT -100;
        ALTER TABLE "user" ADD "title_underline" SMALLINT NOT NULL  DEFAULT 1;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "sub" DROP COLUMN "title_underline";
        ALTER TABLE "user" DROP COLUMN "title_underline";"""
