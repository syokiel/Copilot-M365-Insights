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

CREATE INDEX IF NOT EXISTS idx_events_conv  ON conversation_events(conversation_id);
CREATE INDEX IF NOT EXISTS idx_events_run   ON conversation_events(run_id);
CREATE INDEX IF NOT EXISTS idx_calls_conv   ON connector_calls(conversation_id);
CREATE INDEX IF NOT EXISTS idx_calls_run    ON connector_calls(run_id);
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
