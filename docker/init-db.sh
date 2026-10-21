#!/bin/sh
set -eu
# Invoked once by the official PostgreSQL entrypoint for a fresh data volume.
# psql variables quote passwords as SQL literals; do not interpolate them into SQL.
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 --set=db="$POSTGRES_DB" \
  --set=api_password="$DB_APP_PASSWORD" --set=migration_password="$DB_MIGRATION_PASSWORD" <<'SQL'
CREATE ROLE blog_migrator LOGIN PASSWORD :'migration_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE blog_api LOGIN PASSWORD :'api_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
ALTER DATABASE :"db" OWNER TO blog_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO blog_migrator;
GRANT CONNECT ON DATABASE :"db" TO blog_api;
GRANT USAGE ON SCHEMA public TO blog_api;
ALTER DEFAULT PRIVILEGES FOR ROLE blog_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO blog_api;
SQL
