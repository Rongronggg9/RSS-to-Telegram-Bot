-- upgrade --
ALTER TABLE "user" ADD "sub_limit" SMALLINT   /* Subscription number limit */;
-- downgrade --
ALTER TABLE "user" DROP COLUMN "sub_limit";
