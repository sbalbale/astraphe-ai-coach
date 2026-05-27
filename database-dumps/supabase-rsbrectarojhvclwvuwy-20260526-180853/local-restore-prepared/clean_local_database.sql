SET client_min_messages = warning;

DO $$
DECLARE
  extension_name text;
  publication_name text;
  schema_name text;
BEGIN
  FOR publication_name IN
    SELECT pubname
    FROM pg_publication
  LOOP
    EXECUTE format('DROP PUBLICATION IF EXISTS %I', publication_name);
  END LOOP;

  FOR extension_name IN
    SELECT extname
    FROM pg_extension
    WHERE extname <> 'plpgsql'
  LOOP
    EXECUTE format('DROP EXTENSION IF EXISTS %I CASCADE', extension_name);
  END LOOP;

  FOR schema_name IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname <> 'information_schema'
      AND nspname NOT LIKE 'pg\_%' ESCAPE '\'
  LOOP
    EXECUTE format('DROP SCHEMA IF EXISTS %I CASCADE', schema_name);
  END LOOP;
END
$$;

CREATE SCHEMA public AUTHORIZATION pg_database_owner;
COMMENT ON SCHEMA public IS 'standard public schema';
