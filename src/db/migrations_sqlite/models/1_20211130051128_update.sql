-- upgrade --
ALTER TABLE "feed" ADD "last_modified" TIMESTAMP   /* The last modified time of webpage.  */;
ALTER TABLE "sub" ADD "title" VARCHAR(1024)   /* Sub title, overriding feed title if set */;
-- downgrade --
ALTER TABLE "feed" DROP COLUMN "last_modified";
ALTER TABLE "sub" DROP COLUMN "title";
