SET client_min_messages = warning;

DO $$
DECLARE
  table_record record;
BEGIN
  DROP SCHEMA IF EXISTS public CASCADE;
  CREATE SCHEMA public AUTHORIZATION pg_database_owner;
  COMMENT ON SCHEMA public IS 'standard public schema';

  FOR table_record IN
    SELECT schemaname, tablename
    FROM pg_tables
    WHERE schemaname IN ('auth', 'storage')
      AND tablename NOT IN ('schema_migrations', 'migrations')
  LOOP
    EXECUTE format('TRUNCATE TABLE %I.%I CASCADE', table_record.schemaname, table_record.tablename);
  END LOOP;
END
$$;
