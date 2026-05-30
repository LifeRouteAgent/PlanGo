from __future__ import annotations

from pathlib import Path
import sys

import pymysql

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402


DDL = [
    """
    CREATE TABLE IF NOT EXISTS runtime_sessions (
      session_id VARCHAR(128) PRIMARY KEY,
      payload LONGTEXT NOT NULL,
      updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS runtime_tasks (
      task_id VARCHAR(128) PRIMARY KEY,
      session_id VARCHAR(128) NOT NULL DEFAULT '',
      status VARCHAR(64) NOT NULL DEFAULT '',
      version INT NOT NULL DEFAULT 1,
      state_revision INT NOT NULL DEFAULT 0,
      payload LONGTEXT NOT NULL,
      updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      INDEX idx_runtime_tasks_session (session_id),
      INDEX idx_runtime_tasks_status (status)
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS runtime_tool_cache (
      cache_key VARCHAR(160) PRIMARY KEY,
      tool_name VARCHAR(160) NOT NULL DEFAULT '',
      request_hash VARCHAR(128) NOT NULL DEFAULT '',
      payload LONGTEXT NOT NULL,
      expires_at DATETIME NULL,
      updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      INDEX idx_runtime_tool_name (tool_name),
      INDEX idx_runtime_tool_expires (expires_at)
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS runtime_trace_events (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      trace_id VARCHAR(128) NOT NULL,
      run_id VARCHAR(128) NOT NULL DEFAULT '',
      session_id VARCHAR(128) NOT NULL DEFAULT '',
      event_type VARCHAR(128) NOT NULL DEFAULT '',
      payload LONGTEXT NOT NULL,
      created_at DATETIME NOT NULL,
      INDEX idx_runtime_trace (trace_id, id),
      INDEX idx_runtime_trace_session (session_id)
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS runtime_node_metrics (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      trace_id VARCHAR(128) NOT NULL,
      run_id VARCHAR(128) NOT NULL DEFAULT '',
      session_id VARCHAR(128) NOT NULL DEFAULT '',
      node_name VARCHAR(160) NOT NULL DEFAULT '',
      started_at DATETIME NOT NULL,
      ended_at DATETIME NOT NULL,
      duration_ms INT NOT NULL DEFAULT 0,
      status VARCHAR(32) NOT NULL DEFAULT 'success',
      error TEXT NULL,
      output_summary LONGTEXT NULL,
      created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
      INDEX idx_runtime_node_trace (trace_id, duration_ms),
      INDEX idx_runtime_node_name (node_name)
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """,
]


def main() -> None:
    conn = pymysql.connect(
        host=settings.database_host,
        port=settings.database_port,
        user=settings.database_user,
        password=settings.database_password,
        database=settings.database_name,
        charset="utf8mb4",
        autocommit=True,
    )
    with conn:
        with conn.cursor() as cursor:
            for statement in DDL:
                cursor.execute(statement)
    print("runtime schema initialized")


if __name__ == "__main__":
    main()
