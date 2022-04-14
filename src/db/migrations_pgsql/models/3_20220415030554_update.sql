-- upgrade --
ALTER TABLE "user" ADD "sub_limit" SMALLINT;
-- downgrade --
ALTER TABLE "user" DROP COLUMN "sub_limit";
