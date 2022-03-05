-- upgrade --
ALTER TABLE "sub" ADD "display_media" SMALLINT NOT NULL  DEFAULT 0 /* Display media or not?-1=disable, 0=enable */;
ALTER TABLE "user" ADD "style" SMALLINT NOT NULL  DEFAULT 0;
ALTER TABLE "user" ADD "display_via" SMALLINT NOT NULL  DEFAULT 0;
ALTER TABLE "user" ADD "length_limit" SMALLINT NOT NULL  DEFAULT 0;
ALTER TABLE "user" ADD "interval" SMALLINT;
ALTER TABLE "user" ADD "link_preview" SMALLINT NOT NULL  DEFAULT 0;
ALTER TABLE "user" ADD "display_title" SMALLINT NOT NULL  DEFAULT 0;
ALTER TABLE "user" ADD "send_mode" SMALLINT NOT NULL  DEFAULT 0;
ALTER TABLE "user" ADD "display_media" SMALLINT NOT NULL  DEFAULT 0;
ALTER TABLE "user" ADD "display_author" SMALLINT NOT NULL  DEFAULT 0;
ALTER TABLE "user" ADD "notify" SMALLINT NOT NULL  DEFAULT 1;
-- downgrade --
ALTER TABLE "sub" DROP COLUMN "display_media";
ALTER TABLE "user" DROP COLUMN "style";
ALTER TABLE "user" DROP COLUMN "display_via";
ALTER TABLE "user" DROP COLUMN "length_limit";
ALTER TABLE "user" DROP COLUMN "interval";
ALTER TABLE "user" DROP COLUMN "link_preview";
ALTER TABLE "user" DROP COLUMN "display_title";
ALTER TABLE "user" DROP COLUMN "send_mode";
ALTER TABLE "user" DROP COLUMN "display_media";
ALTER TABLE "user" DROP COLUMN "display_author";
ALTER TABLE "user" DROP COLUMN "notify";
