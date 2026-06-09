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
    row_id                 TEXT PRIMARY KEY,
    run_id                 TEXT NOT NULL,
    timestamp              TEXT,
    event_name             TEXT,
    gen_ai_operation_name  TEXT,           -- OTel: gen_ai.operation.name (invoke_agent)
    gen_ai_agent_id        TEXT,           -- OTel: gen_ai.agent.id
    gen_ai_agent_name      TEXT,           -- OTel: gen_ai.agent.name
    gen_ai_environment_id  TEXT,           -- OTel: gen_ai.environment.id
    session_id             TEXT,
    user_id                TEXT,
    conversation_id        TEXT,
    channel_id             TEXT,
    design_mode            INTEGER,
    topic_name             TEXT,
    text                   TEXT,
    properties             TEXT
);

CREATE TABLE IF NOT EXISTS connector_calls (
    row_id                 TEXT PRIMARY KEY,
    run_id                 TEXT NOT NULL,
    timestamp              TEXT,
    connector_name         TEXT,           -- OTel: gen_ai.tool.name
    gen_ai_operation_name  TEXT,           -- OTel: gen_ai.operation.name (execute_tool)
    gen_ai_agent_id        TEXT,           -- OTel: gen_ai.agent.id
    gen_ai_agent_name      TEXT,           -- OTel: gen_ai.agent.name
    gen_ai_environment_id  TEXT,           -- OTel: gen_ai.environment.id
    action_target          TEXT,
    session_id             TEXT,
    user_id                TEXT,
    conversation_id        TEXT,
    channel_id             TEXT,
    design_mode            INTEGER,
    success                INTEGER,
    result_code            TEXT,
    duration_ms            REAL,
    properties             TEXT
);

CREATE TABLE IF NOT EXISTS pva_agents (
    agent_id        TEXT PRIMARY KEY,
    display_name    TEXT,
    schema_name     TEXT,
    environment_id  TEXT,
    created_at      TEXT,
    modified_at     TEXT,
    published_at    TEXT,
    created_by      TEXT,
    owner_id        TEXT,
    created_in      TEXT,
    ai_model        TEXT,
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

CREATE TABLE IF NOT EXISTS pva_agent_solutions (
    agent_id        TEXT PRIMARY KEY,
    solution_id     TEXT,
    solution_name   TEXT,
    solution_unique TEXT,
    version         TEXT,
    is_managed      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS gen_ai_model_calls (
    row_id                      TEXT PRIMARY KEY,
    run_id                      TEXT NOT NULL,
    timestamp                   TEXT,
    operation_name              TEXT,
    gen_ai_operation_name       TEXT,           -- OTel: gen_ai.operation.name (chat, invoke_agent, …)
    gen_ai_provider_name        TEXT,           -- OTel: gen_ai.provider.name
    gen_ai_request_model        TEXT,           -- OTel: gen_ai.request.model
    gen_ai_response_model       TEXT,           -- OTel: gen_ai.response.model
    gen_ai_usage_input_tokens   INTEGER,        -- OTel: gen_ai.usage.input_tokens
    gen_ai_usage_output_tokens  INTEGER,        -- OTel: gen_ai.usage.output_tokens
    gen_ai_agent_id             TEXT,           -- OTel: gen_ai.agent.id
    gen_ai_agent_name           TEXT,           -- OTel: gen_ai.agent.name
    gen_ai_environment_id       TEXT,           -- OTel: gen_ai.environment.id
    session_id                  TEXT,
    user_id                     TEXT,
    conversation_id             TEXT,
    dependency_type             TEXT,
    target                      TEXT,
    duration_ms                 REAL,
    success                     INTEGER,
    result_code                 TEXT,
    properties                  TEXT
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

CREATE TABLE IF NOT EXISTS aad_users (
    user_id      TEXT PRIMARY KEY,
    display_name TEXT,
    upn          TEXT,
    department   TEXT,
    job_title    TEXT,
    found        INTEGER DEFAULT 1  -- 0 when Graph returned 404 for this ID
);

CREATE TABLE IF NOT EXISTS kpi_snapshots (
    snapshot_id          TEXT PRIMARY KEY,
    snapshot_date        TEXT NOT NULL,
    lookback_days        INTEGER,
    -- M365 Copilot
    total_licenses       INTEGER,
    enabled_users        INTEGER,
    active_users         INTEGER,
    activation_rate      REAL,
    adoption_rate        REAL,
    power_users          INTEGER,
    total_prompts        INTEGER,
    avg_prompts_per_user REAL,
    -- Workload prompt volumes
    prompts_copilot_chat INTEGER,
    prompts_teams        INTEGER,
    prompts_outlook      INTEGER,
    prompts_excel        INTEGER,
    prompts_word         INTEGER,
    prompts_powerpoint   INTEGER,
    prompts_onenote      INTEGER,
    prompts_loop         INTEGER,
    -- Agent adoption (M365 users who used a Studio agent)
    agent_adopters       INTEGER,
    agent_adoption_pct   REAL,
    -- Agent inventory
    total_agents         INTEGER,
    active_agents        INTEGER,
    utilization_rate     REAL,
    production_agents    INTEGER,
    non_prod_agents      INTEGER,
    agents_with_owner    INTEGER,
    ownership_pct        REAL,
    total_conversations  INTEGER,
    -- Environment breakdown (agent counts by env SKU)
    env_default          INTEGER,
    env_developer        INTEGER,
    env_teams            INTEGER,
    env_production       INTEGER,
    env_sandbox          INTEGER,
    env_trial            INTEGER
);

CREATE INDEX IF NOT EXISTS idx_model_calls_conv  ON gen_ai_model_calls(conversation_id);
CREATE INDEX IF NOT EXISTS idx_model_calls_agent ON gen_ai_model_calls(gen_ai_agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_sol         ON pva_agent_solutions(solution_id);
CREATE INDEX IF NOT EXISTS idx_events_conv  ON conversation_events(conversation_id);
CREATE INDEX IF NOT EXISTS idx_events_run   ON conversation_events(run_id);
CREATE INDEX IF NOT EXISTS idx_calls_conv   ON connector_calls(conversation_id);
CREATE INDEX IF NOT EXISTS idx_calls_run    ON connector_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_az_dep_conv  ON az_dependency_failures(conversation_id);
CREATE INDEX IF NOT EXISTS idx_az_exc_conv  ON az_exceptions(conversation_id);

-- ── Viva / Copilot Studio report tables ───────────────────────────────────

CREATE TABLE IF NOT EXISTS viva_cs_session_metrics (
    agent_id               TEXT NOT NULL,
    metric_date            TEXT NOT NULL,
    total_sessions         INTEGER,
    resolved_sessions      INTEGER,
    escalated_sessions     INTEGER,
    abandoned_sessions     INTEGER,
    engaged_sessions       INTEGER,
    unengaged_sessions     INTEGER,
    csat_responses         INTEGER,
    csat_1                 INTEGER,
    csat_2                 INTEGER,
    csat_3                 INTEGER,
    csat_4                 INTEGER,
    csat_5                 INTEGER,
    avg_duration_all       REAL,
    avg_duration_unengaged REAL,
    avg_duration_engaged   REAL,
    avg_duration_resolved  REAL,
    avg_duration_escalated REAL,
    avg_duration_abandoned REAL,
    ks_engaged             INTEGER,
    ks_unengaged           INTEGER,
    ks_resolved            INTEGER,
    ks_escalated           INTEGER,
    ks_abandoned           INTEGER,
    PRIMARY KEY (agent_id, metric_date)
);

CREATE TABLE IF NOT EXISTS viva_cs_topic_metrics (
    agent_id           TEXT NOT NULL,
    topic_id           TEXT NOT NULL,
    topic_name         TEXT,
    metric_date        TEXT NOT NULL,
    total_sessions     INTEGER,
    resolved_sessions  INTEGER,
    escalated_sessions INTEGER,
    abandoned_sessions INTEGER,
    engaged_sessions   INTEGER,
    unengaged_sessions INTEGER,
    csat_responses     INTEGER,
    csat_1             INTEGER,
    csat_2             INTEGER,
    csat_3             INTEGER,
    csat_4             INTEGER,
    csat_5             INTEGER,
    PRIMARY KEY (agent_id, topic_id, metric_date)
);

CREATE TABLE IF NOT EXISTS viva_cs_knowledge_source_metrics (
    agent_id                   TEXT NOT NULL,
    source_type                TEXT NOT NULL,
    metric_date                TEXT NOT NULL,
    count_total                INTEGER,
    count_unengaged            INTEGER,
    count_engaged              INTEGER,
    count_resolved             INTEGER,
    count_escalated            INTEGER,
    count_abandoned            INTEGER,
    count_autonomous           INTEGER,
    count_successful_autonomous INTEGER,
    PRIMARY KEY (agent_id, source_type, metric_date)
);

CREATE TABLE IF NOT EXISTS viva_cs_autonomous_metrics (
    agent_id            TEXT NOT NULL,
    metric_date         TEXT NOT NULL,
    total_runs          INTEGER,
    successful_runs     INTEGER,
    failed_runs         INTEGER,
    total_duration      REAL,
    successful_duration REAL,
    failed_duration     REAL,
    ks_successful       INTEGER,
    ks_failed           INTEGER,
    actions_successful  INTEGER,
    actions_failed      INTEGER,
    no_op_successful    INTEGER,
    no_op_failed        INTEGER,
    PRIMARY KEY (agent_id, metric_date)
);

CREATE TABLE IF NOT EXISTS viva_cs_autonomous_trigger_metrics (
    agent_id            TEXT NOT NULL,
    trigger_schema_name TEXT NOT NULL,
    metric_date         TEXT NOT NULL,
    total_runs          INTEGER,
    successful_runs     INTEGER,
    failed_runs         INTEGER,
    total_duration      REAL,
    successful_duration REAL,
    failed_duration     REAL,
    ks_successful       INTEGER,
    ks_failed           INTEGER,
    actions_successful  INTEGER,
    actions_failed      INTEGER,
    no_op_successful    INTEGER,
    no_op_failed        INTEGER,
    PRIMARY KEY (agent_id, trigger_schema_name, metric_date)
);

CREATE TABLE IF NOT EXISTS viva_cs_action_metrics (
    agent_id                               TEXT NOT NULL,
    action_schema_name                     TEXT NOT NULL,
    metric_date                            TEXT NOT NULL,
    total_runs                             INTEGER,
    successful_actions_in_runs             INTEGER,
    actions_in_successful_runs             INTEGER,
    successful_actions_in_successful_runs  INTEGER,
    PRIMARY KEY (agent_id, action_schema_name, metric_date)
);

CREATE TABLE IF NOT EXISTS viva_cs_copilot_agents (
    agent_id        TEXT PRIMARY KEY,
    agent_name      TEXT,
    description     TEXT,
    surface         TEXT,
    mode            TEXT,
    categories      TEXT,
    agent_type      TEXT,
    is_included     INTEGER DEFAULT 1,
    excluded_reason TEXT,
    icon            TEXT
);

CREATE TABLE IF NOT EXISTS viva_cs_weekly_active_users (
    agent_id          TEXT NOT NULL,
    start_date        TEXT NOT NULL,
    active_user_count INTEGER,
    PRIMARY KEY (agent_id, start_date)
);

CREATE TABLE IF NOT EXISTS viva_cs_extended_metadata (
    agent_id          TEXT PRIMARY KEY,
    aad_tenant_id     TEXT,
    roi_configuration TEXT
);

-- ── Extended Graph Report tables ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS m365_copilot_count_summary (
    report_refresh_date    TEXT PRIMARY KEY,
    report_period          TEXT,
    enabled_users          INTEGER,
    active_users           INTEGER,
    chat_active            INTEGER,
    teams_active           INTEGER,
    teams_meetings_active  INTEGER,
    word_active            INTEGER,
    excel_active           INTEGER,
    powerpoint_active      INTEGER,
    outlook_active         INTEGER,
    onenote_active         INTEGER,
    loop_active            INTEGER,
    windows_active         INTEGER,
    web_active             INTEGER,
    mobile_active          INTEGER
);

CREATE TABLE IF NOT EXISTS m365_copilot_count_trend (
    report_date            TEXT PRIMARY KEY,
    report_refresh_date    TEXT,
    report_period          TEXT,
    active_users           INTEGER,
    chat_active            INTEGER,
    teams_active           INTEGER,
    teams_meetings_active  INTEGER,
    word_active            INTEGER,
    excel_active           INTEGER,
    powerpoint_active      INTEGER,
    outlook_active         INTEGER,
    onenote_active         INTEGER,
    loop_active            INTEGER
);

CREATE TABLE IF NOT EXISTS m365_copilot_packages (
    package_id      TEXT PRIMARY KEY,
    display_name    TEXT,
    description     TEXT,
    type            TEXT,
    state           TEXT,
    publisher_name  TEXT,
    app_id          TEXT,
    properties      TEXT
);

CREATE TABLE IF NOT EXISTS m365_o365_active_users (
    user_principal_name      TEXT PRIMARY KEY,
    display_name             TEXT,
    is_deleted               INTEGER DEFAULT 0,
    exchange_last_activity   TEXT,
    onedrive_last_activity   TEXT,
    sharepoint_last_activity TEXT,
    teams_last_activity      TEXT,
    yammer_last_activity     TEXT,
    has_exchange_license     INTEGER DEFAULT 0,
    has_onedrive_license     INTEGER DEFAULT 0,
    has_sharepoint_license   INTEGER DEFAULT 0,
    has_teams_license        INTEGER DEFAULT 0,
    has_yammer_license       INTEGER DEFAULT 0,
    report_refresh_date      TEXT,
    report_period            TEXT
);

CREATE TABLE IF NOT EXISTS m365_app_users (
    user_principal_name  TEXT PRIMARY KEY,
    last_activation_date TEXT,
    last_activity_date   TEXT,
    report_refresh_date  TEXT,
    report_period        TEXT,
    outlook_active       INTEGER,
    word_active          INTEGER,
    excel_active         INTEGER,
    ppt_active           INTEGER,
    onenote_active       INTEGER,
    teams_active         INTEGER,
    sharepoint_active    INTEGER,
    onedrive_active      INTEGER
);

CREATE TABLE IF NOT EXISTS m365_graph_request_usage (
    snapshot_date    TEXT NOT NULL,
    app_id           TEXT NOT NULL,
    report_period    TEXT,
    request_count    INTEGER,
    fail_count       INTEGER,
    app_display_name TEXT,
    PRIMARY KEY (snapshot_date, app_id)
);

CREATE INDEX IF NOT EXISTS idx_viva_cs_sess_agent  ON viva_cs_session_metrics(agent_id);
CREATE INDEX IF NOT EXISTS idx_viva_cs_topic_agent ON viva_cs_topic_metrics(agent_id);
CREATE INDEX IF NOT EXISTS idx_viva_cs_wau_agent   ON viva_cs_weekly_active_users(agent_id);
CREATE INDEX IF NOT EXISTS idx_viva_cs_auto_agent  ON viva_cs_autonomous_metrics(agent_id);

-- ── Power Platform Analytics API ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS pp_bot_sessions (
    row_id         TEXT PRIMARY KEY,   -- sha1(session_id|bot_id)
    session_id     TEXT NOT NULL,
    bot_id         TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    start_time     TEXT,
    outcome        TEXT,               -- Resolved, Escalated, Abandoned, Unengaged
    duration_sec   REAL,
    channel        TEXT,
    topic_id       TEXT,
    topic_name     TEXT,
    csat_score     INTEGER,
    turn_count     INTEGER
);

CREATE TABLE IF NOT EXISTS pp_bot_topic_analytics (
    bot_id             TEXT NOT NULL,
    environment_id     TEXT NOT NULL,
    topic_id           TEXT NOT NULL,
    topic_name         TEXT,
    fetch_date         TEXT NOT NULL,
    period_from        TEXT,
    period_to          TEXT,
    total_sessions     INTEGER,
    resolved_sessions  INTEGER,
    escalated_sessions INTEGER,
    abandoned_sessions INTEGER,
    trigger_count      INTEGER,
    success_rate       REAL,
    PRIMARY KEY (bot_id, topic_id, fetch_date)
);

CREATE INDEX IF NOT EXISTS idx_pp_sessions_bot ON pp_bot_sessions(bot_id);
CREATE INDEX IF NOT EXISTS idx_pp_topic_bot    ON pp_bot_topic_analytics(bot_id);
"""


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


class SqliteStore:
    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_DDL)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        tables = {
            row[0]
            for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        # Rename legacy tables
        if "pva_bots" in tables and "pva_agents" not in tables:
            self._conn.execute("ALTER TABLE pva_bots RENAME TO pva_agents")
        if "pva_bot_solutions" in tables and "pva_agent_solutions" not in tables:
            self._conn.execute("ALTER TABLE pva_bot_solutions RENAME TO pva_agent_solutions")
        # Rename legacy bot_id column → agent_id
        agent_cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(pva_agents)").fetchall()
        }
        if "bot_id" in agent_cols:
            self._conn.execute("ALTER TABLE pva_agents RENAME COLUMN bot_id TO agent_id")
        sol_cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(pva_agent_solutions)").fetchall()
        }
        if "bot_id" in sol_cols:
            self._conn.execute("ALTER TABLE pva_agent_solutions RENAME COLUMN bot_id TO agent_id")
        # Add new columns added in the inventory-API integration
        agent_cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(pva_agents)").fetchall()
        }
        for col, typedef in [
            ("created_by", "TEXT"),
            ("owner_id",   "TEXT"),
            ("created_in", "TEXT"),
            ("ai_model",   "TEXT"),
        ]:
            if col not in agent_cols:
                self._conn.execute(f"ALTER TABLE pva_agents ADD COLUMN {col} {typedef}")

        # Add OTel GenAI attribute columns to conversation_events and connector_calls
        event_cols = {row[1] for row in self._conn.execute("PRAGMA table_info(conversation_events)").fetchall()}
        for col, typedef in [
            ("gen_ai_operation_name", "TEXT"),
            ("gen_ai_agent_id",       "TEXT"),
            ("gen_ai_agent_name",     "TEXT"),
            ("gen_ai_environment_id", "TEXT"),
        ]:
            if col not in event_cols:
                self._conn.execute(f"ALTER TABLE conversation_events ADD COLUMN {col} {typedef}")

        call_cols = {row[1] for row in self._conn.execute("PRAGMA table_info(connector_calls)").fetchall()}
        for col, typedef in [
            ("gen_ai_operation_name", "TEXT"),
            ("gen_ai_agent_id",       "TEXT"),
            ("gen_ai_agent_name",     "TEXT"),
            ("gen_ai_environment_id", "TEXT"),
        ]:
            if col not in call_cols:
                self._conn.execute(f"ALTER TABLE connector_calls ADD COLUMN {col} {typedef}")

        # Rename viva_* Copilot Studio tables → viva_cs_*
        all_tables = {
            row[0] for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for old, new in [
            ("viva_session_metrics",            "viva_cs_session_metrics"),
            ("viva_topic_metrics",              "viva_cs_topic_metrics"),
            ("viva_knowledge_source_metrics",   "viva_cs_knowledge_source_metrics"),
            ("viva_autonomous_trigger_metrics", "viva_cs_autonomous_trigger_metrics"),
            ("viva_autonomous_metrics",         "viva_cs_autonomous_metrics"),
            ("viva_action_metrics",             "viva_cs_action_metrics"),
            ("viva_copilot_agents",             "viva_cs_copilot_agents"),
            ("viva_weekly_active_users",        "viva_cs_weekly_active_users"),
            ("viva_extended_metadata",          "viva_cs_extended_metadata"),
        ]:
            if old not in all_tables:
                continue
            old_rows = self._conn.execute(f"SELECT COUNT(*) FROM {old}").fetchone()[0]
            if old_rows == 0:
                continue  # old table is empty — nothing to migrate
            # If DDL already created an empty destination, drop it first
            if new in all_tables:
                new_rows = self._conn.execute(f"SELECT COUNT(*) FROM {new}").fetchone()[0]
                if new_rows > 0:
                    continue  # destination already has data — skip
                self._conn.execute(f"DROP TABLE {new}")
            self._conn.execute(f"ALTER TABLE {old} RENAME TO {new}")

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

    def upsert_agents(self, agents: list[dict]) -> int:
        """Insert or replace agent records. Returns count of rows written."""
        _known = {
            "id", "botId", "name", "displayName", "schemaName",
            "environmentId", "createdDateTime", "modifiedDateTime",
            "publishedDateTime", "createdBy", "ownerId", "createdIn",
            "aiModel",
        }
        written = 0
        with self._conn:
            for b in agents:
                cur = self._conn.execute(
                    """
                    INSERT OR REPLACE INTO pva_agents
                    (agent_id, display_name, schema_name, environment_id,
                     created_at, modified_at, published_at,
                     created_by, owner_id, created_in, ai_model, properties)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        b.get("id") or b.get("botId", ""),
                        b.get("name") or b.get("displayName", ""),
                        b.get("schemaName", ""),
                        b.get("environmentId", ""),
                        b.get("createdDateTime", ""),
                        b.get("modifiedDateTime", ""),
                        b.get("publishedDateTime", ""),
                        b.get("createdBy", ""),
                        b.get("ownerId", ""),
                        b.get("createdIn", ""),
                        b.get("aiModel", ""),
                        json.dumps({k: v for k, v in b.items() if k not in _known}),
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
                    (e.get("environment_id", ""), e.get("display_name", ""), e.get("type", ""),
                     e.get("region", ""), e.get("state", ""), e.get("created_at", ""),
                     e.get("modified_at", ""), e.get("sku", ""), e.get("dataverse_url", "")),
                )
                written += cur.rowcount
        return written

    def upsert_publishers(self, publishers: list[dict]) -> int:
        written = 0
        with self._conn:
            for p in publishers:
                cur = self._conn.execute(
                    "INSERT OR REPLACE INTO pva_publishers VALUES (?,?,?,?,?,?,?)",
                    (p.get("publisher_id", ""), p.get("display_name", ""), p.get("unique_name", ""),
                     p.get("email", ""), p.get("phone", ""), p.get("custom_prefix", ""),
                     p.get("solution_count")),
                )
                written += cur.rowcount
        return written

    def upsert_dlp_policies(self, policies: list[dict]) -> int:
        written = 0
        with self._conn:
            for p in policies:
                cur = self._conn.execute(
                    "INSERT OR REPLACE INTO pva_dlp_policies VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (p.get("policy_id", ""), p.get("display_name", ""), p.get("environment_type", ""),
                     p.get("created_by", ""), p.get("created_at", ""), p.get("modified_at", ""),
                     p.get("enforcement_mode", ""), p.get("blocked_connectors", ""),
                     p.get("business_connectors", ""), p.get("non_business_connectors", "")),
                )
                written += cur.rowcount
        return written

    def upsert_agent_solutions(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    "INSERT OR REPLACE INTO pva_agent_solutions VALUES (?,?,?,?,?,?)",
                    (r.get("agent_id", ""), r.get("solution_id", ""), r.get("solution_name", ""),
                     r.get("solution_unique", ""), r.get("version", ""),
                     1 if r.get("is_managed") else 0),
                )
                written += cur.rowcount
        return written

    def fetch_agent_solutions(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM pva_agent_solutions ORDER BY solution_name").fetchall()
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

    def fetch_agents(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT agent_id, display_name, schema_name, environment_id, "
            "created_at, modified_at, published_at, created_by, owner_id, created_in, ai_model "
            "FROM pva_agents ORDER BY display_name"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Azure Monitor tables
    # ------------------------------------------------------------------

    def upsert_az_dependency_failures(self, rows: list[dict]) -> int:
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

    def upsert_gen_ai_model_calls(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
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

    def upsert_aad_users(self, users: list[dict]) -> int:
        written = 0
        with self._conn:
            for u in users:
                cur = self._conn.execute(
                    "INSERT OR REPLACE INTO aad_users VALUES (?,?,?,?,?,?)",
                    (u.get("user_id", ""), u.get("display_name", ""), u.get("upn", ""),
                     u.get("department", ""), u.get("job_title", ""),
                     1 if u.get("found", True) else 0),
                )
                written += cur.rowcount
        return written

    def fetch_aad_users(self) -> dict[str, dict]:
        """Returns {user_id: row_dict} for O(1) lookup in the sheet writers."""
        rows = self._conn.execute("SELECT * FROM aad_users").fetchall()
        return {row["user_id"]: dict(row) for row in rows}

    def fetch_known_user_ids(self) -> list[str]:
        """
        Return distinct Azure AD user object IDs from all available local sources:
          1. Non-design-mode conversation events (OTel)
          2. Already-resolved AAD user cache (agent owner lookups, etc.)
        """
        ids: set[str] = set()
        for sql in [
            "SELECT DISTINCT user_id FROM conversation_events "
            "WHERE user_id IS NOT NULL AND user_id != '' AND design_mode = 0",
            "SELECT DISTINCT user_id FROM aad_users "
            "WHERE user_id IS NOT NULL AND user_id != ''",
        ]:
            try:
                ids.update(row["user_id"] for row in self._conn.execute(sql).fetchall())
            except Exception:
                pass
        return list(ids)

    def compute_kpi_snapshot(self, lookback_days: int, total_licenses: int = 0) -> dict:
        """Compute KPI values from current DB state and return as a dict."""
        from datetime import date, timedelta as td
        cutoff = (date.today() - td(days=lookback_days)).isoformat()

        enabled_users = self._conn.execute(
            "SELECT COUNT(*) FROM m365_copilot_usage"
        ).fetchone()[0] or 0

        active_users = self._conn.execute(
            "SELECT COUNT(*) FROM m365_copilot_usage "
            "WHERE last_activity_date IS NOT NULL AND last_activity_date != ''"
        ).fetchone()[0] or 0

        totals = self._conn.execute("""
            SELECT
                SUM(COALESCE(copilot_chat,0)),
                SUM(COALESCE(teams_chats,0) + COALESCE(teams_meetings,0)),
                SUM(COALESCE(outlook,0)),
                SUM(COALESCE(excel,0)),
                SUM(COALESCE(word,0)),
                SUM(COALESCE(powerpoint,0)),
                SUM(COALESCE(onenote,0)),
                SUM(COALESCE(loop,0)),
                SUM(COALESCE(teams_chats,0) + COALESCE(teams_meetings,0) +
                    COALESCE(word,0) + COALESCE(excel,0) + COALESCE(powerpoint,0) +
                    COALESCE(outlook,0) + COALESCE(onenote,0) + COALESCE(loop,0) +
                    COALESCE(copilot_chat,0))
            FROM m365_copilot_usage
        """).fetchone()
        (p_chat, p_teams, p_outlook, p_excel, p_word,
         p_ppt, p_onenote, p_loop, total_prompts) = [v or 0 for v in totals]

        power_users = self._conn.execute("""
            WITH user_totals AS (
                SELECT COALESCE(teams_chats,0)+COALESCE(teams_meetings,0)+
                       COALESCE(word,0)+COALESCE(excel,0)+COALESCE(powerpoint,0)+
                       COALESCE(outlook,0)+COALESCE(onenote,0)+COALESCE(loop,0)+
                       COALESCE(copilot_chat,0) AS total
                FROM m365_copilot_usage
                WHERE last_activity_date IS NOT NULL AND last_activity_date != ''
            ),
            ranked AS (
                SELECT total,
                       ROW_NUMBER() OVER (ORDER BY total DESC) AS rn,
                       COUNT(*) OVER () AS cnt
                FROM user_totals
            )
            SELECT COUNT(*) FROM ranked WHERE rn * 5 <= cnt
        """).fetchone()[0] or 0

        total_agents = self._conn.execute(
            "SELECT COUNT(*) FROM pva_agents"
        ).fetchone()[0] or 0

        active_agents = self._conn.execute(
            "SELECT COUNT(DISTINCT gen_ai_agent_id) FROM conversation_events "
            "WHERE design_mode=0 AND gen_ai_agent_id IS NOT NULL AND gen_ai_agent_id != '' "
            "AND timestamp >= ?", (cutoff,)
        ).fetchone()[0] or 0

        agents_with_owner = self._conn.execute(
            "SELECT COUNT(*) FROM pva_agents WHERE owner_id IS NOT NULL AND owner_id != ''"
        ).fetchone()[0] or 0

        total_conversations = self._conn.execute(
            "SELECT COUNT(DISTINCT conversation_id) FROM conversation_events "
            "WHERE design_mode=0 AND timestamp >= ?", (cutoff,)
        ).fetchone()[0] or 0

        agent_adopters = self._conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM conversation_events "
            "WHERE design_mode=0 AND user_id IS NOT NULL AND user_id != '' AND timestamp >= ?",
            (cutoff,)
        ).fetchone()[0] or 0

        production_agents = self._conn.execute("""
            SELECT COUNT(a.agent_id) FROM pva_agents a
            JOIN pva_environments e ON a.environment_id = e.environment_id
            WHERE LOWER(COALESCE(e.sku, e.type, '')) = 'production'
        """).fetchone()[0] or 0

        env_counts: dict[str, int] = {}
        for row in self._conn.execute("""
            SELECT LOWER(COALESCE(e.sku, e.type, 'unknown')) AS env_type, COUNT(a.agent_id)
            FROM pva_agents a
            LEFT JOIN pva_environments e ON a.environment_id = e.environment_id
            GROUP BY env_type
        """).fetchall():
            env_counts[row[0]] = row[1]

        return {
            "snapshot_id": str(uuid.uuid4()),
            "snapshot_date": datetime.now(timezone.utc).isoformat(),
            "lookback_days": lookback_days,
            "total_licenses": total_licenses or None,
            "enabled_users": enabled_users,
            "active_users": active_users,
            "activation_rate": round(enabled_users / total_licenses * 100, 1) if total_licenses else None,
            "adoption_rate": round(active_users / enabled_users * 100, 1) if enabled_users else None,
            "power_users": power_users,
            "total_prompts": total_prompts,
            "avg_prompts_per_user": round(total_prompts / active_users, 1) if active_users else None,
            "prompts_copilot_chat": p_chat,
            "prompts_teams": p_teams,
            "prompts_outlook": p_outlook,
            "prompts_excel": p_excel,
            "prompts_word": p_word,
            "prompts_powerpoint": p_ppt,
            "prompts_onenote": p_onenote,
            "prompts_loop": p_loop,
            "agent_adopters": agent_adopters,
            "agent_adoption_pct": round(agent_adopters / enabled_users * 100, 1) if enabled_users else None,
            "total_agents": total_agents,
            "active_agents": active_agents,
            "utilization_rate": round(active_agents / total_agents * 100, 1) if total_agents else None,
            "production_agents": production_agents,
            "non_prod_agents": total_agents - production_agents,
            "agents_with_owner": agents_with_owner,
            "ownership_pct": round(agents_with_owner / total_agents * 100, 1) if total_agents else None,
            "total_conversations": total_conversations,
            "env_default": env_counts.get("default", 0),
            "env_developer": env_counts.get("developer", 0),
            "env_teams": env_counts.get("teams", env_counts.get("microsoftteams", 0)),
            "env_production": env_counts.get("production", 0),
            "env_sandbox": env_counts.get("sandbox", 0),
            "env_trial": env_counts.get("trial", 0),
        }

    def upsert_kpi_snapshot(self, snap: dict) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO kpi_snapshots VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    snap["snapshot_id"], snap["snapshot_date"], snap["lookback_days"],
                    snap.get("total_licenses"), snap.get("enabled_users"), snap.get("active_users"),
                    snap.get("activation_rate"), snap.get("adoption_rate"), snap.get("power_users"),
                    snap.get("total_prompts"), snap.get("avg_prompts_per_user"),
                    snap.get("prompts_copilot_chat"), snap.get("prompts_teams"),
                    snap.get("prompts_outlook"), snap.get("prompts_excel"), snap.get("prompts_word"),
                    snap.get("prompts_powerpoint"), snap.get("prompts_onenote"), snap.get("prompts_loop"),
                    snap.get("agent_adopters"), snap.get("agent_adoption_pct"),
                    snap.get("total_agents"), snap.get("active_agents"), snap.get("utilization_rate"),
                    snap.get("production_agents"), snap.get("non_prod_agents"),
                    snap.get("agents_with_owner"), snap.get("ownership_pct"),
                    snap.get("total_conversations"),
                    snap.get("env_default", 0), snap.get("env_developer", 0),
                    snap.get("env_teams", 0), snap.get("env_production", 0),
                    snap.get("env_sandbox", 0), snap.get("env_trial", 0),
                ),
            )

    def fetch_kpi_snapshots(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM kpi_snapshots ORDER BY snapshot_date DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Viva / Copilot Studio report tables
    # ------------------------------------------------------------------

    def upsert_viva_cs_session_metrics(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_cs_session_metrics VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r['agent_id'], r['metric_date'],
                     r.get('total_sessions'), r.get('resolved_sessions'), r.get('escalated_sessions'),
                     r.get('abandoned_sessions'), r.get('engaged_sessions'), r.get('unengaged_sessions'),
                     r.get('csat_responses'), r.get('csat_1'), r.get('csat_2'), r.get('csat_3'),
                     r.get('csat_4'), r.get('csat_5'),
                     r.get('avg_duration_all'), r.get('avg_duration_unengaged'), r.get('avg_duration_engaged'),
                     r.get('avg_duration_resolved'), r.get('avg_duration_escalated'), r.get('avg_duration_abandoned'),
                     r.get('ks_engaged'), r.get('ks_unengaged'), r.get('ks_resolved'),
                     r.get('ks_escalated'), r.get('ks_abandoned')),
                )
                written += cur.rowcount
        return written

    def fetch_viva_cs_session_metrics(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_cs_session_metrics ORDER BY metric_date DESC, agent_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_cs_topic_metrics(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_cs_topic_metrics VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r['agent_id'], r['topic_id'], r.get('topic_name'), r['metric_date'],
                     r.get('total_sessions'), r.get('resolved_sessions'), r.get('escalated_sessions'),
                     r.get('abandoned_sessions'), r.get('engaged_sessions'), r.get('unengaged_sessions'),
                     r.get('csat_responses'), r.get('csat_1'), r.get('csat_2'), r.get('csat_3'),
                     r.get('csat_4'), r.get('csat_5')),
                )
                written += cur.rowcount
        return written

    def fetch_viva_cs_topic_metrics(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_cs_topic_metrics ORDER BY metric_date DESC, agent_id, topic_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_cs_knowledge_source_metrics(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_cs_knowledge_source_metrics VALUES
                    (?,?,?,?,?,?,?,?,?,?,?)""",
                    (r['agent_id'], r['source_type'], r['metric_date'],
                     r.get('count_total'), r.get('count_unengaged'), r.get('count_engaged'),
                     r.get('count_resolved'), r.get('count_escalated'), r.get('count_abandoned'),
                     r.get('count_autonomous'), r.get('count_successful_autonomous')),
                )
                written += cur.rowcount
        return written

    def fetch_viva_cs_knowledge_source_metrics(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_cs_knowledge_source_metrics ORDER BY metric_date DESC, agent_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_cs_autonomous_metrics(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_cs_autonomous_metrics VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r['agent_id'], r['metric_date'],
                     r.get('total_runs'), r.get('successful_runs'), r.get('failed_runs'),
                     r.get('total_duration'), r.get('successful_duration'), r.get('failed_duration'),
                     r.get('ks_successful'), r.get('ks_failed'),
                     r.get('actions_successful'), r.get('actions_failed'),
                     r.get('no_op_successful'), r.get('no_op_failed')),
                )
                written += cur.rowcount
        return written

    def fetch_viva_cs_autonomous_metrics(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_cs_autonomous_metrics ORDER BY metric_date DESC, agent_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_cs_autonomous_trigger_metrics(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_cs_autonomous_trigger_metrics VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r['agent_id'], r['trigger_schema_name'], r['metric_date'],
                     r.get('total_runs'), r.get('successful_runs'), r.get('failed_runs'),
                     r.get('total_duration'), r.get('successful_duration'), r.get('failed_duration'),
                     r.get('ks_successful'), r.get('ks_failed'),
                     r.get('actions_successful'), r.get('actions_failed'),
                     r.get('no_op_successful'), r.get('no_op_failed')),
                )
                written += cur.rowcount
        return written

    def fetch_viva_cs_autonomous_trigger_metrics(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_cs_autonomous_trigger_metrics ORDER BY metric_date DESC, agent_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_cs_action_metrics(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_cs_action_metrics VALUES (?,?,?,?,?,?,?)""",
                    (r['agent_id'], r['action_schema_name'], r['metric_date'],
                     r.get('total_runs'), r.get('successful_actions_in_runs'),
                     r.get('actions_in_successful_runs'), r.get('successful_actions_in_successful_runs')),
                )
                written += cur.rowcount
        return written

    def fetch_viva_cs_action_metrics(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_cs_action_metrics ORDER BY metric_date DESC, agent_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_cs_copilot_agents(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_cs_copilot_agents VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (r['agent_id'], r.get('agent_name'), r.get('description'), r.get('surface'),
                     r.get('mode'), r.get('categories'), r.get('agent_type'),
                     r.get('is_included', 1), r.get('excluded_reason'), r.get('icon')),
                )
                written += cur.rowcount
        return written

    def fetch_viva_cs_copilot_agents(self) -> dict[str, dict]:
        """Returns {agent_id: row_dict} for O(1) lookup in sheet writers."""
        rows = self._conn.execute(
            "SELECT agent_id, agent_name, description, surface, mode, categories, agent_type, is_included "
            "FROM viva_cs_copilot_agents"
        ).fetchall()
        return {r['agent_id']: dict(r) for r in rows}

    def upsert_viva_cs_weekly_active_users(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_cs_weekly_active_users VALUES (?,?,?)""",
                    (r['agent_id'], r['start_date'], r.get('active_user_count')),
                )
                written += cur.rowcount
        return written

    def fetch_viva_cs_weekly_active_users(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_cs_weekly_active_users ORDER BY start_date DESC, agent_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_cs_extended_metadata(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_cs_extended_metadata VALUES (?,?,?)""",
                    (r['agent_id'], r.get('aad_tenant_id'), r.get('roi_configuration')),
                )
                written += cur.rowcount
        return written

    def fetch_viva_cs_extended_metadata(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM viva_cs_extended_metadata").fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Extended Graph Report tables
    # ------------------------------------------------------------------

    def upsert_copilot_count_summary(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_copilot_count_summary VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r.get("report_refresh_date"), r.get("report_period"),
                     r.get("enabled_users"), r.get("active_users"),
                     r.get("chat_active"), r.get("teams_active"), r.get("teams_meetings_active"),
                     r.get("word_active"), r.get("excel_active"), r.get("powerpoint_active"),
                     r.get("outlook_active"), r.get("onenote_active"), r.get("loop_active"),
                     r.get("windows_active"), r.get("web_active"), r.get("mobile_active")),
                )
                written += cur.rowcount
        return written

    def fetch_copilot_count_summary(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_copilot_count_summary ORDER BY report_refresh_date DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_copilot_count_trend(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_copilot_count_trend VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r.get("report_date"), r.get("report_refresh_date"), r.get("report_period"),
                     r.get("active_users"), r.get("chat_active"), r.get("teams_active"),
                     r.get("teams_meetings_active"), r.get("word_active"), r.get("excel_active"),
                     r.get("powerpoint_active"), r.get("outlook_active"),
                     r.get("onenote_active"), r.get("loop_active")),
                )
                written += cur.rowcount
        return written

    def fetch_copilot_count_trend(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_copilot_count_trend ORDER BY report_date"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_copilot_packages(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_copilot_packages VALUES
                    (?,?,?,?,?,?,?,?)""",
                    (r.get("package_id"), r.get("display_name"), r.get("description"),
                     r.get("type"), r.get("state"), r.get("publisher_name"),
                     r.get("app_id"), r.get("properties")),
                )
                written += cur.rowcount
        return written

    def fetch_copilot_packages(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_copilot_packages ORDER BY display_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_o365_active_users(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_o365_active_users VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r.get("user_principal_name"), r.get("display_name"), r.get("is_deleted", 0),
                     r.get("exchange_last_activity"), r.get("onedrive_last_activity"),
                     r.get("sharepoint_last_activity"), r.get("teams_last_activity"),
                     r.get("yammer_last_activity"),
                     r.get("has_exchange_license", 0), r.get("has_onedrive_license", 0),
                     r.get("has_sharepoint_license", 0), r.get("has_teams_license", 0),
                     r.get("has_yammer_license", 0),
                     r.get("report_refresh_date"), r.get("report_period")),
                )
                written += cur.rowcount
        return written

    def fetch_o365_active_users(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_o365_active_users ORDER BY user_principal_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_app_users(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_app_users VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r.get("user_principal_name"), r.get("last_activation_date"),
                     r.get("last_activity_date"), r.get("report_refresh_date"), r.get("report_period"),
                     r.get("outlook_active"), r.get("word_active"), r.get("excel_active"),
                     r.get("ppt_active"), r.get("onenote_active"), r.get("teams_active"),
                     r.get("sharepoint_active"), r.get("onedrive_active")),
                )
                written += cur.rowcount
        return written

    def fetch_m365_app_users(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_app_users ORDER BY user_principal_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_graph_request_usage(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_graph_request_usage VALUES
                    (?,?,?,?,?,?)""",
                    (r.get("snapshot_date"), r.get("app_id", ""),
                     r.get("report_period"), r.get("request_count"), r.get("fail_count"),
                     r.get("app_display_name")),
                )
                written += cur.rowcount
        return written

    def fetch_graph_request_usage(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_graph_request_usage ORDER BY snapshot_date DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Power Platform Analytics API
    # ------------------------------------------------------------------

    def upsert_pp_bot_sessions(self, sessions: list[dict]) -> int:
        from src.fetchers.pp_analytics import _session_row_id
        written = 0
        with self._conn:
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

    def fetch_pp_bot_sessions(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM pp_bot_sessions ORDER BY start_time DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_pp_bot_topic_analytics(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
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

    def fetch_pp_bot_topic_analytics(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM pp_bot_topic_analytics ORDER BY bot_id, topic_name"
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
