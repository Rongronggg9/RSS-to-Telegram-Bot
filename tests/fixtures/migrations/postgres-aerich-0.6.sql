CREATE TABLE IF NOT EXISTS "aerich" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "version" VARCHAR(255) NOT NULL,
    "app" VARCHAR(20) NOT NULL,
    "content" JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS "feed" (
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "id" SERIAL NOT NULL PRIMARY KEY,
    "state" SMALLINT NOT NULL DEFAULT 1,
    "link" VARCHAR(4096) NOT NULL UNIQUE,
    "title" VARCHAR(1024) NOT NULL,
    "interval" SMALLINT,
    "entry_hashes" TEXT,
    "etag" VARCHAR(128),
    "error_count" SMALLINT NOT NULL DEFAULT 0,
    "next_check_time" TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS "option" (
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "id" SERIAL NOT NULL PRIMARY KEY,
    "key" VARCHAR(255) NOT NULL UNIQUE,
    "value" TEXT
);
CREATE TABLE IF NOT EXISTS "user" (
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "id" BIGSERIAL NOT NULL PRIMARY KEY,
    "state" SMALLINT NOT NULL DEFAULT 0,
    "lang" VARCHAR(16) NOT NULL DEFAULT 'zh-Hans',
    "admin" BIGINT
);
CREATE TABLE IF NOT EXISTS "sub" (
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "id" SERIAL NOT NULL PRIMARY KEY,
    "state" SMALLINT NOT NULL DEFAULT 1,
    "tags" VARCHAR(255),
    "interval" SMALLINT,
    "notify" SMALLINT NOT NULL DEFAULT 1,
    "send_mode" SMALLINT NOT NULL DEFAULT 0,
    "length_limit" SMALLINT NOT NULL DEFAULT 0,
    "link_preview" SMALLINT NOT NULL DEFAULT 0,
    "display_author" SMALLINT NOT NULL DEFAULT 0,
    "display_via" SMALLINT NOT NULL DEFAULT 0,
    "display_title" SMALLINT NOT NULL DEFAULT 0,
    "style" SMALLINT NOT NULL DEFAULT 0,
    "feed_id" INT NOT NULL REFERENCES "feed" ("id") ON DELETE CASCADE,
    "user_id" BIGINT NOT NULL REFERENCES "user" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_sub_user_id_029239" UNIQUE ("user_id", "feed_id")
);
ALTER TABLE "feed" ADD "last_modified" TIMESTAMPTZ;
ALTER TABLE "sub" ADD "title" VARCHAR(1024);
ALTER TABLE "user" ADD "sub_limit" SMALLINT;
ALTER TABLE "sub" ADD "display_media" SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE "user" ADD "send_mode" SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE "user" ADD "display_author" SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE "user" ADD "display_media" SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE "user" ADD "display_title" SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE "user" ADD "notify" SMALLINT NOT NULL DEFAULT 1;
ALTER TABLE "user" ADD "link_preview" SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE "user" ADD "style" SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE "user" ADD "length_limit" SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE "user" ADD "interval" SMALLINT;
ALTER TABLE "user" ADD "display_via" SMALLINT NOT NULL DEFAULT 0;
INSERT INTO "aerich" ("id", "version", "app", "content") VALUES
    (1, '0_20211117110249_init.sql', 'models', '{}'::jsonb),
    (2, '1_20211130051128_update.sql', 'models', '{}'::jsonb),
    (3, '2_20220306045951_update.sql', 'models', '{}'::jsonb),
    (4, '3_20220415030554_update.sql', 'models', '{}'::jsonb);
INSERT INTO "user" (
    "id", "created_at", "updated_at", "state", "lang", "admin", "sub_limit",
    "interval", "notify", "send_mode", "length_limit", "link_preview",
    "display_author", "display_via", "display_title", "style", "display_media"
) VALUES (
    101, '2024-04-25 02:08:49+00', '2024-04-25 03:08:49+00', 1, 'en', 9101, 42,
    11, 0, 2, 777, 1, 1, -1, 1, 1, -1
);
INSERT INTO "feed" (
    "id", "created_at", "updated_at", "state", "link", "title", "interval",
    "entry_hashes", "etag", "last_modified", "error_count", "next_check_time"
) VALUES (
    201, '2024-04-25 02:08:49+00', '2024-04-25 03:08:49+00', 1,
    'https://legacy-user:legacy-pass@legacy.example.test/feed?token=legacy-token',
    'Legacy Fixture Feed', 17, '[111, 222]', 'legacy-etag',
    '2024-04-24 02:08:49+00', 7, '2024-04-26 02:08:49+00'
);
INSERT INTO "sub" (
    "id", "created_at", "updated_at", "state", "user_id", "feed_id", "title",
    "tags", "interval", "notify", "send_mode", "length_limit", "link_preview",
    "display_author", "display_via", "display_title", "style", "display_media"
) VALUES (
    301, '2024-04-25 02:08:49+00', '2024-04-25 03:08:49+00', 1, 101, 201,
    'Legacy Subscription', 'legacy,fixture', 23, 0, 2, 511, 1, 1, -1, 1, 1, -1
);
INSERT INTO "option" ("id", "created_at", "updated_at", "key", "value") VALUES
    (401, '2024-04-25 02:08:49+00', '2024-04-25 03:08:49+00', 'default_interval', '29');
SELECT setval(pg_get_serial_sequence('"aerich"', 'id'), 4, true);
SELECT setval(pg_get_serial_sequence('"user"', 'id'), 101, true);
SELECT setval(pg_get_serial_sequence('"feed"', 'id'), 201, true);
SELECT setval(pg_get_serial_sequence('"sub"', 'id'), 301, true);
SELECT setval(pg_get_serial_sequence('"option"', 'id'), 401, true);
