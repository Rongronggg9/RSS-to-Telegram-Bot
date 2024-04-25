from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "sub" ADD "display_entry_tags" SMALLINT NOT NULL  DEFAULT -100;
        ALTER TABLE "user" ADD "display_entry_tags" SMALLINT NOT NULL  DEFAULT -1;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "sub" DROP COLUMN "display_entry_tags";
        ALTER TABLE "user" DROP COLUMN "display_entry_tags";"""
