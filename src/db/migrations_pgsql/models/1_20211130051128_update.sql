-- upgrade --
ALTER TABLE "feed" ADD "last_modified" TIMESTAMPTZ;
ALTER TABLE "sub" ADD "title" VARCHAR(1024);
-- downgrade --
ALTER TABLE "sub" DROP COLUMN "title";
ALTER TABLE "feed" DROP COLUMN "last_modified";
