#!/bin/sh
set -eu
APP_DB_PASSWORD="$(cat /run/secrets/db_password)" psql \
    --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 <<'SQL'
\getenv app_password APP_DB_PASSWORD
CREATE ROLE wattwise LOGIN PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER DATABASE wattwise OWNER TO wattwise;
ALTER SCHEMA public OWNER TO wattwise;
SQL
