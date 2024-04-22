from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "feed" ADD "last_modified" TIMESTAMPTZ;
ALTER TABLE "sub" ADD "title" VARCHAR(1024);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "sub" DROP COLUMN "title";
ALTER TABLE "feed" DROP COLUMN "last_modified";"""
