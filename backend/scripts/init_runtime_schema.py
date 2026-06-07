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
    """
    CREATE TABLE IF NOT EXISTS memory_user_profiles (
      user_id VARCHAR(128) PRIMARY KEY,
      profile_payload LONGTEXT NOT NULL,
      summary TEXT NULL,
      version INT NOT NULL DEFAULT 1,
      updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_preferences (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id VARCHAR(128) NOT NULL,
      preference_key VARCHAR(128) NOT NULL,
      preference_value VARCHAR(255) NOT NULL DEFAULT '',
      category VARCHAR(128) NOT NULL DEFAULT '',
      polarity VARCHAR(32) NOT NULL DEFAULT 'positive',
      confidence DECIMAL(5,3) NOT NULL DEFAULT 0.000,
      weight DECIMAL(8,3) NOT NULL DEFAULT 0.000,
      source_stage VARCHAR(64) NOT NULL DEFAULT '',
      source_event_id VARCHAR(128) NOT NULL DEFAULT '',
      status VARCHAR(32) NOT NULL DEFAULT 'active',
      created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      UNIQUE KEY uk_memory_preference (user_id, preference_key, preference_value),
      INDEX idx_memory_preferences_user (user_id, status, confidence),
      INDEX idx_memory_preferences_category (category, polarity)
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_evidence (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id VARCHAR(128) NOT NULL,
      preference_id BIGINT NULL,
      session_id VARCHAR(128) NOT NULL DEFAULT '',
      plan_id VARCHAR(128) NOT NULL DEFAULT '',
      event_stage VARCHAR(64) NOT NULL DEFAULT '',
      evidence_type VARCHAR(64) NOT NULL DEFAULT '',
      confidence_delta DECIMAL(5,3) NOT NULL DEFAULT 0.000,
      weight DECIMAL(8,3) NOT NULL DEFAULT 0.000,
      payload LONGTEXT NOT NULL,
      created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
      INDEX idx_memory_evidence_user (user_id, created_at),
      INDEX idx_memory_evidence_preference (preference_id),
      INDEX idx_memory_evidence_plan (plan_id, event_stage)
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_events (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      event_id VARCHAR(128) NOT NULL,
      user_id VARCHAR(128) NOT NULL DEFAULT '',
      session_id VARCHAR(128) NOT NULL DEFAULT '',
      event_type VARCHAR(128) NOT NULL DEFAULT '',
      stage VARCHAR(64) NOT NULL DEFAULT '',
      status VARCHAR(32) NOT NULL DEFAULT 'pending',
      payload LONGTEXT NOT NULL,
      created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
      processed_at TIMESTAMP NULL,
      UNIQUE KEY uk_memory_events_event_id (event_id),
      INDEX idx_memory_events_status (status, created_at),
      INDEX idx_memory_events_user (user_id, created_at)
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_plan_feedback (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id VARCHAR(128) NOT NULL,
      session_id VARCHAR(128) NOT NULL DEFAULT '',
      plan_id VARCHAR(128) NOT NULL DEFAULT '',
      stage VARCHAR(64) NOT NULL DEFAULT '',
      feedback_type VARCHAR(64) NOT NULL DEFAULT '',
      reason TEXT NULL,
      weight DECIMAL(8,3) NOT NULL DEFAULT 0.000,
      payload LONGTEXT NOT NULL,
      created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
      INDEX idx_memory_plan_feedback_user (user_id, created_at),
      INDEX idx_memory_plan_feedback_plan (plan_id, stage)
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_session_turns (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      session_id VARCHAR(128) NOT NULL,
      user_id VARCHAR(128) NOT NULL DEFAULT '',
      turn_index INT NOT NULL DEFAULT 0,
      query_summary TEXT NULL,
      session_profile LONGTEXT NULL,
      payload LONGTEXT NOT NULL,
      expires_at DATETIME NULL,
      created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
      INDEX idx_memory_session_turns_session (session_id, turn_index),
      INDEX idx_memory_session_turns_expires (expires_at)
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_rejected_plans (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id VARCHAR(128) NOT NULL,
      session_id VARCHAR(128) NOT NULL DEFAULT '',
      plan_id VARCHAR(128) NOT NULL DEFAULT '',
      reason TEXT NULL,
      payload LONGTEXT NOT NULL,
      created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
      INDEX idx_memory_rejected_plans_session (session_id, created_at),
      INDEX idx_memory_rejected_plans_user (user_id, created_at)
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
