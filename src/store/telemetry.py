"""OTel conversation telemetry (Log Analytics), Azure Monitor health and Power Platform bot analytics."""
import hashlib
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone


def _event_row_id(e: dict) -> str:
    key = f"{e.get('Timestamp')}|{e.get('ConversationId')}|{e.get('EventName')}|{e.get('SessionId')}"
    return hashlib.sha1(key.encode()).hexdigest()


def _call_row_id(c: dict) -> str:
    key = f"{c.get('Timestamp')}|{c.get('ConversationId')}|{c.get('ConnectorName')}|{c.get('ActionTarget')}"
    return hashlib.sha1(key.encode()).hexdigest()


def _model_call_row_id(r: dict) -> str:
    key = f"{r.get('Timestamp')}|{r.get('ConversationId')}|{r.get('OperationName')}|{r.get('GenAiRequestModel')}"
    return hashlib.sha1(key.encode()).hexdigest()


def dep_row_id(r: dict) -> str:
    key = f"{r.get('OperationId')}|{r.get('ConversationId')}|{r.get('DependencyName')}|{r.get('Timestamp')}"
    return hashlib.sha1(key.encode()).hexdigest()


def exc_row_id(r: dict) -> str:
    key = f"{r.get('OperationId')}|{r.get('ConversationId')}|{r.get('ExceptionType')}|{r.get('Timestamp')}"
    return hashlib.sha1(key.encode()).hexdigest()


class TelemetryMixin:
    def upsert(self, events: list[dict], connector_calls: list[dict]) -> tuple[int, int]:
        """Insert new records, skip duplicates. Returns (new_events, new_calls).
        Rows are stamped with the current sync run (begin_run()); callers that
        didn't open one get a run created here, as before."""
        run_id = self._run_id
        new_run = run_id is None
        if new_run:
            run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()

        events_new = 0
        calls_new = 0

        with self._conn:
            self._begin_import('conversation_events', events, snapshot=False)
            self._begin_import('connector_calls', connector_calls, snapshot=False)
            for e in events:
                row_id = _event_row_id(e)
                cur = self._conn.execute(
                    """
                    INSERT OR IGNORE INTO conversation_events
                    (row_id, run_id, timestamp, event_name,
                     gen_ai_operation_name, gen_ai_agent_id, gen_ai_agent_name, gen_ai_environment_id,
                     session_id, user_id, conversation_id, channel_id,
                     design_mode, topic_name, text, properties)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        row_id, run_id,
                        str(e.get("Timestamp", "")),
                        e.get("EventName", ""),
                        e.get("GenAiOperationName", ""),
                        e.get("GenAiAgentId", ""),
                        e.get("GenAiAgentName", ""),
                        e.get("GenAiEnvironmentId", ""),
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
                    (row_id, run_id, timestamp, connector_name,
                     gen_ai_operation_name, gen_ai_agent_id, gen_ai_agent_name, gen_ai_environment_id,
                     action_target, session_id, user_id, conversation_id, channel_id,
                     design_mode, success, result_code, duration_ms, properties)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        row_id, run_id,
                        str(c.get("Timestamp", "")),
                        c.get("ConnectorName", ""),
                        c.get("GenAiOperationName", ""),
                        c.get("GenAiAgentId", ""),
                        c.get("GenAiAgentName", ""),
                        c.get("GenAiEnvironmentId", ""),
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

            if new_run:
                self._conn.execute(
                    "INSERT INTO sync_runs (run_id, started_at, events_new, calls_new) VALUES (?,?,?,?)",
                    (run_id, started_at, events_new, calls_new),
                )
            else:
                self._conn.execute(
                    "UPDATE sync_runs SET events_new = events_new + ?, calls_new = calls_new + ? WHERE run_id = ?",
                    (events_new, calls_new, run_id),
                )

        return events_new, calls_new

    def get_last_run_id(self) -> str | None:
        row = self._conn.execute(
            "SELECT run_id FROM sync_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return row["run_id"] if row else None

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

    def upsert_gen_ai_model_calls(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('gen_ai_model_calls', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """
                    INSERT OR IGNORE INTO gen_ai_model_calls
                    (row_id, run_id, timestamp, operation_name,
                     gen_ai_operation_name, gen_ai_provider_name,
                     gen_ai_request_model, gen_ai_response_model,
                     gen_ai_usage_input_tokens, gen_ai_usage_output_tokens,
                     gen_ai_agent_id, gen_ai_agent_name, gen_ai_environment_id,
                     session_id, user_id, conversation_id,
                     dependency_type, target, duration_ms, success, result_code, properties)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        _model_call_row_id(r),
                        r.get("_run_id", ""),
                        str(r.get("Timestamp", "")),
                        r.get("OperationName", ""),
                        r.get("GenAiOperationName", ""),
                        r.get("GenAiProviderName", ""),
                        r.get("GenAiRequestModel", ""),
                        r.get("GenAiResponseModel", ""),
                        r.get("GenAiUsageInputTokens"),
                        r.get("GenAiUsageOutputTokens"),
                        r.get("GenAiAgentId", ""),
                        r.get("GenAiAgentName", ""),
                        r.get("GenAiEnvironmentId", ""),
                        r.get("SessionId", ""),
                        r.get("UserId", ""),
                        r.get("ConversationId", ""),
                        r.get("DependencyType", ""),
                        r.get("Target", ""),
                        r.get("DurationMs"),
                        1 if r.get("Success") else 0,
                        r.get("ResultCode", ""),
                        r.get("Properties", ""),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_gen_ai_model_calls(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM gen_ai_model_calls ORDER BY timestamp DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_az_dependency_failures(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('az_dependency_failures', rows, snapshot=False)
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
        written = 0
        with self._conn:
            self._begin_import('az_exceptions', rows, snapshot=False)
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
            self._begin_import('az_alerts', rows, snapshot=False)
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

    def upsert_pp_bot_sessions(self, sessions: list[dict]) -> int:
        from src.fetchers.pp_analytics import _session_row_id
        written = 0
        with self._conn:
            self._begin_import('pp_bot_sessions', sessions, snapshot=False)
            for s in sessions:
                row_id = _session_row_id(
                    s.get("session_id", ""), s.get("bot_id", "")
                )
                cur = self._conn.execute(
                    """INSERT OR IGNORE INTO pp_bot_sessions
                    (row_id, session_id, bot_id, environment_id, start_time,
                     outcome, duration_sec, channel, topic_id, topic_name,
                     csat_score, turn_count)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        row_id,
                        s.get("session_id", ""),
                        s.get("bot_id", ""),
                        s.get("environment_id", ""),
                        s.get("start_time", ""),
                        s.get("outcome", ""),
                        s.get("duration_sec"),
                        s.get("channel", ""),
                        s.get("topic_id", ""),
                        s.get("topic_name", ""),
                        s.get("csat_score"),
                        s.get("turn_count"),
                    ),
                )
                written += cur.rowcount
        return written

    def upsert_pp_bot_topic_analytics(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('pp_bot_topic_analytics', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO pp_bot_topic_analytics
                    (bot_id, environment_id, topic_id, topic_name, fetch_date,
                     period_from, period_to, total_sessions, resolved_sessions,
                     escalated_sessions, abandoned_sessions, trigger_count, success_rate)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        r.get("bot_id", ""),
                        r.get("environment_id", ""),
                        r.get("topic_id", ""),
                        r.get("topic_name", ""),
                        r.get("fetch_date", ""),
                        r.get("period_from", ""),
                        r.get("period_to", ""),
                        r.get("total_sessions"),
                        r.get("resolved_sessions"),
                        r.get("escalated_sessions"),
                        r.get("abandoned_sessions"),
                        r.get("trigger_count"),
                        r.get("success_rate"),
                    ),
                )
                written += cur.rowcount
        return written



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
        "GenAiOperationName": row["gen_ai_operation_name"],
        "GenAiAgentId": row["gen_ai_agent_id"],
        "GenAiAgentName": row["gen_ai_agent_name"],
        "GenAiEnvironmentId": row["gen_ai_environment_id"],
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
        "GenAiOperationName": row["gen_ai_operation_name"],
        "GenAiAgentId": row["gen_ai_agent_id"],
        "GenAiAgentName": row["gen_ai_agent_name"],
        "GenAiEnvironmentId": row["gen_ai_environment_id"],
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
