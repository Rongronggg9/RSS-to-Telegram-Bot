from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "feed" ADD "last_modified" TIMESTAMP   /* The last modified time of webpage.  */;
ALTER TABLE "sub" ADD "title" VARCHAR(1024)   /* Sub title, overriding feed title if set */;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "feed" DROP COLUMN "last_modified";
ALTER TABLE "sub" DROP COLUMN "title";"""
