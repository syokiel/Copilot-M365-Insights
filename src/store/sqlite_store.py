import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


_DDL = """
CREATE TABLE IF NOT EXISTS sync_runs (
    run_id      TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    events_new  INTEGER DEFAULT 0,
    calls_new   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS conversation_events (
    row_id          TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    timestamp       TEXT,
    event_name      TEXT,
    session_id      TEXT,
    user_id         TEXT,
    conversation_id TEXT,
    channel_id      TEXT,
    design_mode     INTEGER,
    topic_name      TEXT,
    text            TEXT,
    properties      TEXT
);

CREATE TABLE IF NOT EXISTS connector_calls (
    row_id          TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    timestamp       TEXT,
    connector_name  TEXT,
    action_target   TEXT,
    session_id      TEXT,
    user_id         TEXT,
    conversation_id TEXT,
    channel_id      TEXT,
    design_mode     INTEGER,
    success         INTEGER,
    result_code     TEXT,
    duration_ms     REAL,
    properties      TEXT
);

CREATE TABLE IF NOT EXISTS pva_bots (
    bot_id          TEXT PRIMARY KEY,
    display_name    TEXT,
    schema_name     TEXT,
    environment_id  TEXT,
    created_at      TEXT,
    modified_at     TEXT,
    published_at    TEXT,
    properties      TEXT
);

CREATE TABLE IF NOT EXISTS pva_environments (
    environment_id  TEXT PRIMARY KEY,
    display_name    TEXT,
    type            TEXT,
    region          TEXT,
    state           TEXT,
    created_at      TEXT,
    modified_at     TEXT,
    sku             TEXT,
    dataverse_url   TEXT
);

CREATE TABLE IF NOT EXISTS pva_publishers (
    publisher_id    TEXT PRIMARY KEY,
    display_name    TEXT,
    unique_name     TEXT,
    email           TEXT,
    phone           TEXT,
    custom_prefix   TEXT,
    solution_count  INTEGER
);

CREATE TABLE IF NOT EXISTS pva_dlp_policies (
    policy_id               TEXT PRIMARY KEY,
    display_name            TEXT,
    environment_type        TEXT,
    created_by              TEXT,
    created_at              TEXT,
    modified_at             TEXT,
    enforcement_mode        TEXT,
    blocked_connectors      TEXT,
    business_connectors     TEXT,
    non_business_connectors TEXT
);

CREATE TABLE IF NOT EXISTS pva_bot_solutions (
    bot_id          TEXT PRIMARY KEY,
    solution_id     TEXT,
    solution_name   TEXT,
    solution_unique TEXT,
    version         TEXT,
    is_managed      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS az_dependency_failures (
    row_id          TEXT PRIMARY KEY,
    operation_id    TEXT,
    agent_id        TEXT,
    agent_name      TEXT,
    env_id          TEXT,
    conversation_id TEXT,
    dependency_name TEXT,
    result_code     TEXT,
    success         INTEGER,
    duration_ms     REAL,
    timestamp       TEXT
);

CREATE TABLE IF NOT EXISTS az_exceptions (
    row_id           TEXT PRIMARY KEY,
    operation_id     TEXT,
    agent_id         TEXT,
    conversation_id  TEXT,
    exception_type   TEXT,
    exception_message TEXT,
    timestamp        TEXT
);

CREATE TABLE IF NOT EXISTS az_alerts (
    alert_id    TEXT PRIMARY KEY,
    agent_id    TEXT,
    alert_name  TEXT,
    severity    TEXT,
    fired_time  TEXT,
    resource_id TEXT
);

CREATE TABLE IF NOT EXISTS m365_copilot_usage (
    user_principal_name TEXT PRIMARY KEY,
    display_name        TEXT,
    last_activity_date  TEXT,
    teams_chats         INTEGER,
    teams_meetings      INTEGER,
    word                INTEGER,
    excel               INTEGER,
    powerpoint          INTEGER,
    outlook             INTEGER,
    onenote             INTEGER,
    loop                INTEGER,
    copilot_chat        INTEGER,
    report_refresh_date TEXT,
    report_period       TEXT
);

CREATE TABLE IF NOT EXISTS teams_usage (
    user_principal_name   TEXT PRIMARY KEY,
    last_activity_date    TEXT,
    team_chat_messages    INTEGER,
    private_chat_messages INTEGER,
    calls                 INTEGER,
    meetings              INTEGER,
    meetings_organized    INTEGER,
    meetings_attended     INTEGER,
    report_refresh_date   TEXT,
    report_period         TEXT
);

-- ── Viva Insights ──────────────────────────────────────────────────────────

-- Personal analytics: one row per (user, week).
-- Hours are decimal (1.5 = 1h30m).  Populated from Graph Analytics API.
CREATE TABLE IF NOT EXISTS viva_person_insights (
    row_id          TEXT PRIMARY KEY,   -- sha1(user_id|week_start)
    user_id         TEXT NOT NULL,      -- Azure AD object ID
    week_start      TEXT NOT NULL,      -- ISO date of Monday
    week_end        TEXT,               -- ISO date of Sunday
    focus_hours     REAL DEFAULT 0,     -- uninterrupted focus blocks
    meeting_hours   REAL DEFAULT 0,     -- scheduled meetings
    email_hours     REAL DEFAULT 0,     -- time in email / Outlook
    chat_hours      REAL DEFAULT 0,     -- Teams chat
    after_hours     REAL DEFAULT 0,     -- collaboration outside working hours
    fetched_at      TEXT
);

-- Org-level aggregates: populated by Viva Insights Management API (stubbed).
CREATE TABLE IF NOT EXISTS viva_org_insights (
    row_id              TEXT PRIMARY KEY,   -- sha1(metric_date|period)
    metric_date         TEXT NOT NULL,
    period              TEXT,               -- e.g. "Week"
    avg_focus_hours     REAL,
    avg_meeting_hours   REAL,
    avg_email_hours     REAL,
    avg_chat_hours      REAL,
    avg_after_hours     REAL,
    population_size     INTEGER,
    fetched_at          TEXT
);

CREATE INDEX IF NOT EXISTS idx_bot_sol      ON pva_bot_solutions(solution_id);
CREATE INDEX IF NOT EXISTS idx_events_conv  ON conversation_events(conversation_id);
CREATE INDEX IF NOT EXISTS idx_events_run   ON conversation_events(run_id);
CREATE INDEX IF NOT EXISTS idx_calls_conv   ON connector_calls(conversation_id);
CREATE INDEX IF NOT EXISTS idx_calls_run    ON connector_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_az_dep_conv  ON az_dependency_failures(conversation_id);
CREATE INDEX IF NOT EXISTS idx_az_exc_conv  ON az_exceptions(conversation_id);
"""


def _event_row_id(e: dict) -> str:
    key = f"{e.get('Timestamp')}|{e.get('ConversationId')}|{e.get('EventName')}|{e.get('SessionId')}"
    return hashlib.sha1(key.encode()).hexdigest()


def _call_row_id(c: dict) -> str:
    key = f"{c.get('Timestamp')}|{c.get('ConversationId')}|{c.get('ConnectorName')}|{c.get('ActionTarget')}"
    return hashlib.sha1(key.encode()).hexdigest()


class SqliteStore:
    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_DDL)
        self._conn.commit()

    def upsert(self, events: list[dict], connector_calls: list[dict]) -> tuple[int, int]:
        """Insert new records, skip duplicates. Returns (new_events, new_calls)."""
        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()

        events_new = 0
        calls_new = 0

        with self._conn:
            for e in events:
                row_id = _event_row_id(e)
                cur = self._conn.execute(
                    """
                    INSERT OR IGNORE INTO conversation_events
                    (row_id, run_id, timestamp, event_name, session_id, user_id,
                     conversation_id, channel_id, design_mode, topic_name, text, properties)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        row_id, run_id,
                        str(e.get("Timestamp", "")),
                        e.get("EventName", ""),
                        e.get("SessionId", ""),
                        e.get("UserId", ""),
                        e.get("ConversationId", ""),
                        e.get("ChannelId", ""),
                        1 if e.get("DesignMode") else 0,
                        e.get("TopicName", ""),
                        e.get("Text", ""),
                        e.get("Properties", ""),
                    ),
                )
                events_new += cur.rowcount

            for c in connector_calls:
                row_id = _call_row_id(c)
                cur = self._conn.execute(
                    """
                    INSERT OR IGNORE INTO connector_calls
                    (row_id, run_id, timestamp, connector_name, action_target, session_id,
                     user_id, conversation_id, channel_id, design_mode, success,
                     result_code, duration_ms, properties)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        row_id, run_id,
                        str(c.get("Timestamp", "")),
                        c.get("ConnectorName", ""),
                        c.get("ActionTarget", ""),
                        c.get("SessionId", ""),
                        c.get("UserId", ""),
                        c.get("ConversationId", ""),
                        c.get("ChannelId", ""),
                        1 if c.get("DesignMode") else 0,
                        1 if c.get("Success") else 0,
                        c.get("ResultCode", ""),
                        c.get("DurationMs"),
                        c.get("Properties", ""),
                    ),
                )
                calls_new += cur.rowcount

            self._conn.execute(
                "INSERT INTO sync_runs (run_id, started_at, events_new, calls_new) VALUES (?,?,?,?)",
                (run_id, started_at, events_new, calls_new),
            )

        return events_new, calls_new

    def get_last_run_id(self) -> str | None:
        row = self._conn.execute(
            "SELECT run_id FROM sync_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return row["run_id"] if row else None

    def fetch_events_for_run(self, run_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM conversation_events WHERE run_id = ? ORDER BY timestamp DESC",
            (run_id,),
        ).fetchall()
        return [_to_event_dict(r) for r in rows]

    def fetch_calls_for_run(self, run_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM connector_calls WHERE run_id = ? ORDER BY timestamp DESC",
            (run_id,),
        ).fetchall()
        return [_to_call_dict(r) for r in rows]

    def fetch_events_since(self, lookback: timedelta) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - lookback).isoformat()
        rows = self._conn.execute(
            "SELECT * FROM conversation_events WHERE timestamp >= ? ORDER BY timestamp DESC",
            (cutoff,),
        ).fetchall()
        return [_to_event_dict(r) for r in rows]

    def fetch_calls_since(self, lookback: timedelta) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - lookback).isoformat()
        rows = self._conn.execute(
            "SELECT * FROM connector_calls WHERE timestamp >= ? ORDER BY timestamp DESC",
            (cutoff,),
        ).fetchall()
        return [_to_call_dict(r) for r in rows]

    def upsert_bots(self, bots: list[dict]) -> int:
        """Insert or replace bot records. Returns count of rows written."""
        written = 0
        with self._conn:
            for b in bots:
                cur = self._conn.execute(
                    """
                    INSERT OR REPLACE INTO pva_bots
                    (bot_id, display_name, schema_name, environment_id,
                     created_at, modified_at, published_at, properties)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        b.get("id") or b.get("botId", ""),
                        b.get("name") or b.get("displayName", ""),
                        b.get("schemaName", ""),
                        b.get("environmentId", ""),
                        b.get("createdDateTime", ""),
                        b.get("modifiedDateTime", ""),
                        b.get("publishedDateTime", ""),
                        json.dumps({k: v for k, v in b.items() if k not in (
                            "id", "botId", "name", "displayName", "schemaName",
                            "environmentId", "createdDateTime", "modifiedDateTime",
                            "publishedDateTime",
                        )}),
                    ),
                )
                written += cur.rowcount
        return written

    def upsert_environments(self, envs: list[dict]) -> int:
        written = 0
        with self._conn:
            for e in envs:
                cur = self._conn.execute(
                    "INSERT OR REPLACE INTO pva_environments VALUES (?,?,?,?,?,?,?,?,?)",
                    (e["environment_id"], e["display_name"], e["type"], e["region"],
                     e["state"], e["created_at"], e["modified_at"], e["sku"], e["dataverse_url"]),
                )
                written += cur.rowcount
        return written

    def upsert_publishers(self, publishers: list[dict]) -> int:
        written = 0
        with self._conn:
            for p in publishers:
                cur = self._conn.execute(
                    "INSERT OR REPLACE INTO pva_publishers VALUES (?,?,?,?,?,?,?)",
                    (p["publisher_id"], p["display_name"], p["unique_name"],
                     p["email"], p["phone"], p["custom_prefix"], p.get("solution_count")),
                )
                written += cur.rowcount
        return written

    def upsert_dlp_policies(self, policies: list[dict]) -> int:
        written = 0
        with self._conn:
            for p in policies:
                cur = self._conn.execute(
                    "INSERT OR REPLACE INTO pva_dlp_policies VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (p["policy_id"], p["display_name"], p["environment_type"],
                     p["created_by"], p["created_at"], p["modified_at"],
                     p["enforcement_mode"], p["blocked_connectors"],
                     p["business_connectors"], p["non_business_connectors"]),
                )
                written += cur.rowcount
        return written

    def upsert_bot_solutions(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    "INSERT OR REPLACE INTO pva_bot_solutions VALUES (?,?,?,?,?,?)",
                    (r["bot_id"], r["solution_id"], r["solution_name"],
                     r["solution_unique"], r["version"], 1 if r.get("is_managed") else 0),
                )
                written += cur.rowcount
        return written

    def fetch_bot_solutions(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM pva_bot_solutions ORDER BY solution_name").fetchall()
        return [dict(r) for r in rows]

    def fetch_environments(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM pva_environments ORDER BY display_name").fetchall()
        return [dict(r) for r in rows]

    def fetch_publishers(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM pva_publishers ORDER BY display_name").fetchall()
        return [dict(r) for r in rows]

    def fetch_dlp_policies(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM pva_dlp_policies ORDER BY display_name").fetchall()
        return [dict(r) for r in rows]

    def fetch_bots(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT bot_id, display_name, schema_name, environment_id, created_at, modified_at, published_at FROM pva_bots ORDER BY display_name"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Azure Monitor tables
    # ------------------------------------------------------------------

    def upsert_az_dependency_failures(self, rows: list[dict]) -> int:
        from src.fetchers.azure_monitor_fetcher import dep_row_id
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO az_dependency_failures VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (dep_row_id(r), r.get("OperationId", ""), r.get("AgentId", ""),
                     r.get("AgentName", ""), r.get("EnvId", ""), r.get("ConversationId", ""),
                     r.get("DependencyName", ""), r.get("ResultCode", ""),
                     0,  # success = false (we only store failures)
                     r.get("DurationMs"), str(r.get("Timestamp", ""))),
                )
                written += cur.rowcount
        return written

    def upsert_az_exceptions(self, rows: list[dict]) -> int:
        from src.fetchers.azure_monitor_fetcher import exc_row_id
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO az_exceptions VALUES (?,?,?,?,?,?,?)",
                    (exc_row_id(r), r.get("OperationId", ""), r.get("AgentId", ""),
                     r.get("ConversationId", ""), r.get("ExceptionType", ""),
                     r.get("ExceptionMessage", ""), str(r.get("Timestamp", ""))),
                )
                written += cur.rowcount
        return written

    def upsert_az_alerts(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    "INSERT OR REPLACE INTO az_alerts VALUES (?,?,?,?,?,?)",
                    (r.get("alert_id", ""), r.get("agent_id", ""), r.get("alert_name", ""),
                     r.get("severity", ""), r.get("fired_time", ""), r.get("resource_id", "")),
                )
                written += cur.rowcount
        return written

    def fetch_az_dependency_failures(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM az_dependency_failures ORDER BY timestamp DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def fetch_az_exceptions(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM az_exceptions ORDER BY timestamp DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def fetch_az_alerts(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM az_alerts ORDER BY fired_time DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # M365 Copilot + Teams usage tables
    # ------------------------------------------------------------------

    def upsert_copilot_usage(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_copilot_usage VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r["user_principal_name"], r.get("display_name", ""),
                     r.get("last_activity_date", ""), r.get("teams_chats"),
                     r.get("teams_meetings"), r.get("word"), r.get("excel"),
                     r.get("powerpoint"), r.get("outlook"), r.get("onenote"),
                     r.get("loop"), r.get("copilot_chat"),
                     r.get("report_refresh_date", ""), r.get("report_period", "")),
                )
                written += cur.rowcount
        return written

    def upsert_teams_usage(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO teams_usage VALUES
                    (?,?,?,?,?,?,?,?,?,?)""",
                    (r["user_principal_name"], r.get("last_activity_date", ""),
                     r.get("team_chat_messages"), r.get("private_chat_messages"),
                     r.get("calls"), r.get("meetings"),
                     r.get("meetings_organized"), r.get("meetings_attended"),
                     r.get("report_refresh_date", ""), r.get("report_period", "")),
                )
                written += cur.rowcount
        return written

    def fetch_copilot_usage(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_copilot_usage ORDER BY user_principal_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def fetch_teams_usage(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM teams_usage ORDER BY user_principal_name"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Viva Insights tables
    # ------------------------------------------------------------------

    def upsert_viva_person_insights(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_person_insights
                    (row_id, user_id, week_start, week_end,
                     focus_hours, meeting_hours, email_hours, chat_hours, after_hours,
                     fetched_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (r["row_id"], r["user_id"], r["week_start"], r.get("week_end"),
                     r.get("focus_hours", 0), r.get("meeting_hours", 0),
                     r.get("email_hours", 0), r.get("chat_hours", 0),
                     r.get("after_hours", 0), r.get("fetched_at")),
                )
                written += cur.rowcount
        return written

    def upsert_viva_org_insights(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_org_insights
                    (row_id, metric_date, period,
                     avg_focus_hours, avg_meeting_hours, avg_email_hours,
                     avg_chat_hours, avg_after_hours, population_size, fetched_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (r["row_id"], r["metric_date"], r.get("period"),
                     r.get("avg_focus_hours"), r.get("avg_meeting_hours"),
                     r.get("avg_email_hours"), r.get("avg_chat_hours"),
                     r.get("avg_after_hours"), r.get("population_size"),
                     r.get("fetched_at")),
                )
                written += cur.rowcount
        return written

    def fetch_viva_person_insights(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_person_insights ORDER BY week_start DESC, user_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def fetch_viva_org_insights(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_org_insights ORDER BY metric_date DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._conn.close()


def _parse_ts(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return value


def _to_event_dict(row: sqlite3.Row) -> dict:
    return {
        "Timestamp": _parse_ts(row["timestamp"]),
        "EventName": row["event_name"],
        "SessionId": row["session_id"],
        "UserId": row["user_id"],
        "ConversationId": row["conversation_id"],
        "ChannelId": row["channel_id"],
        "DesignMode": bool(row["design_mode"]),
        "TopicName": row["topic_name"],
        "Text": row["text"],
        "Properties": row["properties"],
    }


def _to_call_dict(row: sqlite3.Row) -> dict:
    return {
        "Timestamp": _parse_ts(row["timestamp"]),
        "ConnectorName": row["connector_name"],
        "ActionTarget": row["action_target"],
        "SessionId": row["session_id"],
        "UserId": row["user_id"],
        "ConversationId": row["conversation_id"],
        "ChannelId": row["channel_id"],
        "DesignMode": bool(row["design_mode"]),
        "Success": bool(row["success"]),
        "ResultCode": row["result_code"],
        "DurationMs": row["duration_ms"],
        "Properties": row["properties"],
    }
