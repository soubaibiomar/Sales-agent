-- Migration: 000_extensions.sql
-- Extensions the versioned migrations depend on (inspection finding F-26).
-- infra/init-db.sql always created these, but the numbered migrations did not, so a
-- database built only from migrations failed at 014 (digest() comes from pgcrypto).
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
