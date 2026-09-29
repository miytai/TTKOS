-- ForumOS: расширения и начальная настройка БД (TECHSPEC §5.1, §15.6).
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS btree_gin;

-- Разрешённые роли БД (используются в контейнерах приложений).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'forumos_readonly') THEN
    CREATE ROLE forumos_readonly NOLOGIN;
    GRANT CONNECT ON DATABASE forumos TO forumos_readonly;
  END IF;
END
$$;
