"""Reconstruct prior schemas for migration tests from a fresh current database."""

from app.db.connection import _require_database_pool


async def restore_schema_seven():
    async with _require_database_pool().connection() as connection:
        await connection.execute("""
            DROP TABLE api_commands, search_local_results;
            DROP INDEX search_sessions_owner_latest_idx;
            ALTER TABLE search_sessions
                DROP CONSTRAINT search_sessions_status_check,
                DROP CONSTRAINT search_sessions_lifecycle_check,
                ADD CONSTRAINT search_sessions_status_check
                    CHECK(status IN ('running', 'completed', 'partial', 'error')),
                ADD CONSTRAINT search_sessions_check CHECK(
                    (status = 'running' AND finished_at IS NULL)
                    OR (status <> 'running' AND finished_at IS NOT NULL)),
                DROP COLUMN execution_mode, DROP COLUMN access_mode, DROP COLUMN client_key,
                DROP COLUMN attempt_number, DROP COLUMN attempt_token,
                DROP COLUMN online_quota_attempt, DROP COLUMN warnings, DROP COLUMN retry_at;
            DELETE FROM schema_migrations WHERE version >= 8;
        """)
