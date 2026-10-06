#!/bin/bash
# Runs once, on an empty data volume. Creates the databases, the least-privilege roles and the
# append-only audit table. Table schema for the main database comes from Alembic, not here.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
  CREATE ROLE jamii LOGIN PASSWORD '${JAMII_DB_PASSWORD}';
  CREATE DATABASE jamii OWNER jamii;
  REVOKE CONNECT ON DATABASE jamii FROM PUBLIC;

  -- Audit trail: a separate database the app can add to and read, but never change.
  CREATE ROLE jamii_audit LOGIN PASSWORD '${JAMII_AUDIT_DB_PASSWORD}';
  CREATE DATABASE jamii_audit OWNER postgres;
  REVOKE CONNECT ON DATABASE jamii_audit FROM PUBLIC;
  GRANT CONNECT ON DATABASE jamii_audit TO jamii_audit;

  -- Metabase: its own metadata database, and a reader that sees only the dashboards schema.
  CREATE ROLE metabase LOGIN PASSWORD '${METABASE_DB_PASSWORD}';
  CREATE DATABASE metabase OWNER metabase;
  CREATE ROLE metabase_reader LOGIN PASSWORD '${METABASE_READER_PASSWORD}';
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname jamii <<-EOSQL
  CREATE EXTENSION IF NOT EXISTS postgis;
  GRANT CONNECT ON DATABASE jamii TO metabase_reader;
  REVOKE ALL ON SCHEMA public FROM metabase_reader;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname jamii_audit <<-EOSQL
  REVOKE CREATE ON SCHEMA public FROM PUBLIC;
  CREATE TABLE audit_log (
    id          SERIAL PRIMARY KEY,
    at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_type  VARCHAR(10) NOT NULL,
    actor_id    INTEGER,
    action      VARCHAR(60) NOT NULL,
    object_type VARCHAR(40),
    object_id   VARCHAR(40),
    ip          VARCHAR(64),
    details     JSON NOT NULL DEFAULT '{}'
  );
  CREATE INDEX ix_audit_log_at ON audit_log (at);
  CREATE INDEX ix_audit_log_action ON audit_log (action);
  GRANT SELECT, INSERT ON audit_log TO jamii_audit;
  GRANT USAGE ON SEQUENCE audit_log_id_seq TO jamii_audit;
EOSQL
