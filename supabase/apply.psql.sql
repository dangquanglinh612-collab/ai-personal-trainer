-- Reviewed empty TEST project only. psql wrapper; not SQL Editor syntax.
\set ON_ERROR_STOP on
BEGIN;
\ir schema.sql
\ir indexes.sql
\ir rls.sql
\ir rpc.sql
\ir storage.sql
COMMIT;
