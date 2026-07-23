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

-- pva_agents is now a compatibility VIEW over dim_agent (see Cluster A DDL
-- further down + _migrate()), not a physical table.

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
    -- display_name moved to dim_user; fetch_copilot_usage() joins it back in
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

CREATE TABLE IF NOT EXISTS viva_reports_cs_session_metrics (
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

CREATE TABLE IF NOT EXISTS viva_reports_cs_topic_metrics (
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

CREATE TABLE IF NOT EXISTS viva_reports_cs_knowledge_source_metrics (
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

CREATE TABLE IF NOT EXISTS viva_reports_cs_autonomous_metrics (
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

CREATE TABLE IF NOT EXISTS viva_reports_cs_autonomous_trigger_metrics (
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

CREATE TABLE IF NOT EXISTS viva_reports_cs_action_metrics (
    agent_id                               TEXT NOT NULL,
    action_schema_name                     TEXT NOT NULL,
    metric_date                            TEXT NOT NULL,
    total_runs                             INTEGER,
    successful_actions_in_runs             INTEGER,
    actions_in_successful_runs             INTEGER,
    successful_actions_in_successful_runs  INTEGER,
    PRIMARY KEY (agent_id, action_schema_name, metric_date)
);

-- viva_reports_cs_copilot_agents' data now lives in dim_agent (see Cluster A
-- DDL further down). fetch_viva_reports_cs_copilot_agents() reads from
-- dim_agent directly; a compatibility VIEW named viva_reports_cs_copilot_agents
-- is also created in _migrate() so example SQL in the LLM prompt docs
-- (src/agent/instructions.py) keeps working unchanged.

CREATE TABLE IF NOT EXISTS viva_reports_cs_weekly_active_users (
    agent_id          TEXT NOT NULL,
    start_date        TEXT NOT NULL,
    active_user_count INTEGER,
    PRIMARY KEY (agent_id, start_date)
);

CREATE TABLE IF NOT EXISTS viva_reports_cs_extended_metadata (
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
    -- display_name moved to dim_user; fetch_o365_active_users() joins it back in
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
    -- outlook/word/excel/ppt/onenote/teams _active flags moved to
    -- fact_user_app_activity (overlap with m365_usage_proplus_detail);
    -- fetch_m365_app_users() joins them back in. sharepoint/onedrive stay
    -- here (no overlapping source for those two apps).
    sharepoint_active    INTEGER,
    onedrive_active      INTEGER
);

CREATE INDEX IF NOT EXISTS idx_viva_reports_cs_sess_agent  ON viva_reports_cs_session_metrics(agent_id);
CREATE INDEX IF NOT EXISTS idx_viva_reports_cs_topic_agent ON viva_reports_cs_topic_metrics(agent_id);
CREATE INDEX IF NOT EXISTS idx_viva_reports_cs_wau_agent   ON viva_reports_cs_weekly_active_users(agent_id);
CREATE INDEX IF NOT EXISTS idx_viva_reports_cs_auto_agent  ON viva_reports_cs_autonomous_metrics(agent_id);

-- ── Viva Reports — Copilot Adoption (per-user weekly prompt activity) ─────

CREATE TABLE IF NOT EXISTS viva_reports_copilot_adoption (
    person_id                          TEXT NOT NULL,
    metric_date                        TEXT NOT NULL,
    organization                       TEXT,
    -- Chat prompts
    chat_work_outlook                  INTEGER,
    chat_work_teams                    INTEGER,
    chat_web_teams                     INTEGER,
    chat_web_outlook                   INTEGER,
    chat_web_prompts                   INTEGER,
    chat_work_prompts                  INTEGER,
    -- App-specific prompts
    word_work_prompts                  INTEGER,
    word_web_prompts                   INTEGER,
    excel_work_prompts                 INTEGER,
    excel_web_prompts                  INTEGER,
    ppt_work_prompts                   INTEGER,
    ppt_web_prompts                    INTEGER,
    word_chat_prompts                  INTEGER,
    ppt_chat_prompts                   INTEGER,
    excel_chat_prompts                 INTEGER,
    -- Actions
    intelligent_recap_actions          INTEGER,
    visualize_table_word               INTEGER,
    add_content_ppt                    INTEGER,
    draft_word_doc                     INTEGER,
    summarize_word_doc                 INTEGER,
    email_coaching                     INTEGER,
    generate_email_draft               INTEGER,
    summarize_email_thread             INTEGER,
    excel_analysis                     INTEGER,
    excel_formatting                   INTEGER,
    create_excel_formula               INTEGER,
    summarize_meeting_teams            INTEGER,
    summarize_ppt                      INTEGER,
    create_ppt                         INTEGER,
    rewrite_text_word                  INTEGER,
    summarize_chat_teams               INTEGER,
    compose_chat_teams                 INTEGER,
    -- Totals
    total_copilot_actions              INTEGER,
    total_copilot_active_days          INTEGER,
    total_copilot_enabled_days         INTEGER,
    meeting_hours_summarized           REAL,
    actions_copilot_chat               INTEGER,
    actions_excel                      INTEGER,
    actions_outlook                    INTEGER,
    actions_powerpoint                 INTEGER,
    actions_teams                      INTEGER,
    actions_word                       INTEGER,
    PRIMARY KEY (person_id, metric_date)
);

-- ── Viva Reports — Copilot Impact (per-user weekly work patterns + Copilot) ─

CREATE TABLE IF NOT EXISTS viva_reports_copilot_impact (
    person_id                          TEXT NOT NULL,
    metric_date                        TEXT NOT NULL,
    organization                       TEXT,
    is_active                          INTEGER,
    weekend_days                       TEXT,
    -- Copilot actions (same columns as adoption)
    total_copilot_actions              INTEGER,
    total_copilot_active_days          INTEGER,
    total_copilot_enabled_days         INTEGER,
    intelligent_recap_actions          INTEGER,
    chat_web_prompts                   INTEGER,
    meeting_hours_summarized           REAL,
    meetings_summarized                INTEGER,
    summarize_meeting_teams            INTEGER,
    summarize_chat_teams               INTEGER,
    compose_chat_teams                 INTEGER,
    chat_conversations_summarized      INTEGER,
    word_work_prompts                  INTEGER,
    word_web_prompts                   INTEGER,
    excel_work_prompts                 INTEGER,
    excel_web_prompts                  INTEGER,
    ppt_work_prompts                   INTEGER,
    ppt_web_prompts                    INTEGER,
    visualize_table_word               INTEGER,
    add_content_ppt                    INTEGER,
    organize_ppt                       INTEGER,
    chat_work_prompts                  INTEGER,
    summarize_email_thread             INTEGER,
    email_coaching                     INTEGER,
    generate_email_draft               INTEGER,
    summarize_word_doc                 INTEGER,
    summarize_ppt                      INTEGER,
    create_ppt                         INTEGER,
    rewrite_text_word                  INTEGER,
    draft_word_doc                     INTEGER,
    excel_analysis                     INTEGER,
    create_excel_formula               INTEGER,
    excel_formatting                   INTEGER,
    emails_sent_with_copilot           INTEGER,
    -- Work pattern signals
    attended_meetings                  REAL,
    meetings                           REAL,
    meeting_hours                      REAL,
    uninterrupted_hours                REAL,
    small_meeting_hours                REAL,
    multitasking_hours                 REAL,
    conflicting_meeting_hours          REAL,
    chats_sent                         INTEGER,
    emails_sent                        INTEGER,
    PRIMARY KEY (person_id, metric_date)
);

-- viva_reports_copilot_adoption / _impact are now compatibility views over
-- fact_copilot_actions_per_person / fact_copilot_work_patterns (views can't
-- be indexed) — indexed further down where those tables are declared.

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

-- ── M365 Admin — Agent Inventory ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS m365_admin_agent_inventory (
    title_id                 TEXT PRIMARY KEY,  -- T_xxx identifier; links to m365_usage_* tables
    name                     TEXT,
    status                   TEXT,
    channel                  TEXT,
    date_created             TEXT,
    last_modified            TEXT,
    publisher                TEXT,
    publisher_type           TEXT,
    version                  TEXT,
    owner                    TEXT,
    description              TEXT,
    platform                 TEXT,
    creator_id               TEXT,             -- AAD user GUID
    environment_id           TEXT,
    bot_id                   TEXT,             -- Copilot Studio GUID (links to pva_agents.agent_id)
    custom_actions           INTEGER,
    custom_action_list       TEXT,
    sensitivity              TEXT,
    can_read_od_sp           INTEGER,          -- Can read OneDrive & SharePoint items
    od_sp_items              TEXT,
    can_read_od_files        INTEGER,
    od_files                 TEXT,
    od_sites                 TEXT,
    can_read_sp_sites        INTEGER,
    sp_files                 TEXT,
    sp_sites                 TEXT,
    can_extend_graph         INTEGER,
    graph_connector_details  TEXT,
    can_generate_images      INTEGER,
    can_use_code_interpreter INTEGER,
    contains_uploaded_files  INTEGER,
    uploaded_files           TEXT,
    instructions             TEXT,
    groups_shared            TEXT,
    users_shared             TEXT
);

-- ── M365 Usage — Agent Activity (30-day rolling snapshot) ────────────────

CREATE TABLE IF NOT EXISTS m365_usage_agents (
    agent_id                TEXT PRIMARY KEY,
    agent_name              TEXT,
    creator_type            TEXT,
    active_users_licensed   INTEGER,
    active_users_unlicensed INTEGER,
    responses_sent          INTEGER,
    last_activity_date      TEXT
);

-- ── M365 Usage — Per-User Agent Activity ─────────────────────────────────

CREATE TABLE IF NOT EXISTS m365_usage_agent_users (
    agent_id           TEXT NOT NULL,
    username           TEXT NOT NULL,
    agent_name         TEXT,
    creator_type       TEXT,
    responses_sent     INTEGER,
    last_activity_date TEXT,
    PRIMARY KEY (agent_id, username)
);

CREATE INDEX IF NOT EXISTS idx_m365_admin_inv_bot    ON m365_admin_agent_inventory(bot_id);
CREATE INDEX IF NOT EXISTS idx_m365_usage_users_user ON m365_usage_agent_users(username);

-- ── Experience Model — Agent → Journey → Persona dimension ─────────────

CREATE TABLE IF NOT EXISTS dim_agent_journey_persona (
    agent_id     TEXT    NOT NULL,
    journey_name TEXT    NOT NULL,
    persona_type TEXT    NOT NULL,
    agent_name   TEXT,
    PRIMARY KEY (agent_id, journey_name, persona_type)
);

CREATE INDEX IF NOT EXISTS idx_dim_ajp_journey ON dim_agent_journey_persona(journey_name);
CREATE INDEX IF NOT EXISTS idx_dim_ajp_persona ON dim_agent_journey_persona(persona_type);

-- ── M365 Usage — Per-User Agent Activity Rollup ──────────────────────────

CREATE TABLE IF NOT EXISTS m365_usage_users (
    username                 TEXT PRIMARY KEY,
    -- display_name moved to dim_user (keyed by username); fetch_m365_usage_users() joins it back in
    agents_used              INTEGER,
    agent_responses_received INTEGER,
    last_activity_date       TEXT
);

-- ── Tokenomics — Copilot Credit Consumption (Power Platform Admin) ───────

CREATE TABLE IF NOT EXISTS tokenomics_capacity_consumption (
    row_id            TEXT PRIMARY KEY,  -- synthetic hash; natural key isn't unique (see fetcher)
    tenant_id         TEXT,
    environment_id    TEXT,
    environment_name  TEXT,
    environment_type  TEXT,
    resource_id       TEXT,
    resource_name     TEXT,
    resource_type     TEXT,
    product_name      TEXT,
    feature_name      TEXT,
    channel_id        TEXT,
    is_billable       INTEGER,
    unit              TEXT,
    consumption_date  TEXT,
    consumed_quantity REAL
);

CREATE TABLE IF NOT EXISTS tokenomics_entitlement_consumption (
    billing_plan_id           TEXT NOT NULL,
    billing_plan_name         TEXT,
    environment_id            TEXT NOT NULL,
    environment_name          TEXT,
    capacity_type             TEXT NOT NULL,
    entitled_quantity         REAL,
    prepaid_consumed_quantity REAL,
    payg_consumed_quantity    REAL,
    usage_date                TEXT NOT NULL,
    PRIMARY KEY (billing_plan_id, environment_id, capacity_type, usage_date)
);

CREATE INDEX IF NOT EXISTS idx_tokenomics_capacity_env    ON tokenomics_capacity_consumption(environment_id);
CREATE INDEX IF NOT EXISTS idx_tokenomics_capacity_date   ON tokenomics_capacity_consumption(consumption_date);
CREATE INDEX IF NOT EXISTS idx_tokenomics_entitlement_env ON tokenomics_entitlement_consumption(environment_id);

CREATE TABLE IF NOT EXISTS tokenomics_entitlement_per_agent (
    row_id           TEXT PRIMARY KEY,  -- synthetic hash: agent_id|ai_feature|channel|tool_used|scenario_name|environment_id
    agent_name       TEXT,
    agent_id         TEXT,
    product          TEXT,
    ai_feature       TEXT,
    billed_credit    REAL,
    non_billed_credit REAL,
    channel          TEXT,
    knowledge_sources TEXT,
    tool_used        TEXT,
    llm_model        TEXT,
    scenario_name    TEXT,
    environment_id   TEXT,
    environment_name TEXT
);

CREATE TABLE IF NOT EXISTS tokenomics_entitlement_per_user (
    user_id               TEXT NOT NULL,
    agent_id              TEXT NOT NULL,
    user_email            TEXT,
    agent_name            TEXT,
    billable_credit_used  REAL,
    credits_used          REAL,
    m365_copilot_licensed INTEGER,
    PRIMARY KEY (user_id, agent_id)
);

CREATE INDEX IF NOT EXISTS idx_tokenomics_per_agent_agent ON tokenomics_entitlement_per_agent(agent_id);
CREATE INDEX IF NOT EXISTS idx_tokenomics_per_agent_env   ON tokenomics_entitlement_per_agent(environment_id);
CREATE INDEX IF NOT EXISTS idx_tokenomics_per_user_user   ON tokenomics_entitlement_per_user(user_id);

-- ── M365 Admin Center — Office 365 / M365 Apps Usage Reports (CSV import) ─

CREATE TABLE IF NOT EXISTS m365_usage_activations_users (
    user_principal_name TEXT NOT NULL,
    product_type        TEXT NOT NULL,
    report_refresh_date TEXT,
    display_name        TEXT,
    last_activated_date TEXT,
    windows             INTEGER DEFAULT 0,
    mac                 INTEGER DEFAULT 0,
    windows_10_mobile   INTEGER DEFAULT 0,
    ios                 INTEGER DEFAULT 0,
    android             INTEGER DEFAULT 0,
    shared_computer     INTEGER DEFAULT 0,
    PRIMARY KEY (user_principal_name, product_type)
);

-- m365_usage_active_users_services / _activity, and m365_usage_active_user_counts
-- are now compatibility VIEWs pivoting fact_service_usage back to their
-- original wide shape (see Cluster C DDL further down + _migrate()).

CREATE TABLE IF NOT EXISTS m365_usage_active_users_detail (
    user_principal_name      TEXT PRIMARY KEY,
    report_refresh_date      TEXT,
    -- display_name moved to dim_user; fetch_m365_usage_active_users_detail() joins it back in
    is_deleted               INTEGER DEFAULT 0,
    deleted_date             TEXT,
    has_exchange             INTEGER DEFAULT 0,
    has_onedrive             INTEGER DEFAULT 0,
    has_sharepoint           INTEGER DEFAULT 0,
    has_skype                INTEGER DEFAULT 0,
    has_yammer               INTEGER DEFAULT 0,
    has_teams                INTEGER DEFAULT 0,
    exchange_last_activity   TEXT,
    onedrive_last_activity   TEXT,
    sharepoint_last_activity TEXT,
    skype_last_activity      TEXT,
    yammer_last_activity     TEXT,
    teams_last_activity      TEXT,
    exchange_license_date    TEXT,
    onedrive_license_date    TEXT,
    sharepoint_license_date  TEXT,
    skype_license_date       TEXT,
    yammer_license_date      TEXT,
    teams_license_date       TEXT,
    assigned_products        TEXT
);

CREATE TABLE IF NOT EXISTS m365_usage_proplus_platforms (
    report_date         TEXT NOT NULL,
    report_period       TEXT NOT NULL,
    report_refresh_date TEXT,
    windows             INTEGER,
    mac                 INTEGER,
    mobile              INTEGER,
    web                 INTEGER,
    PRIMARY KEY (report_date, report_period)
);

CREATE TABLE IF NOT EXISTS m365_usage_proplus_counts (
    report_date         TEXT NOT NULL,
    report_period       TEXT NOT NULL,
    report_refresh_date TEXT,
    outlook             INTEGER,
    word                INTEGER,
    excel               INTEGER,
    powerpoint          INTEGER,
    onenote             INTEGER,
    teams               INTEGER,
    PRIMARY KEY (report_date, report_period)
);

CREATE TABLE IF NOT EXISTS m365_usage_proplus_detail (
    user_principal_name  TEXT PRIMARY KEY,
    report_refresh_date  TEXT,
    last_activation_date TEXT,
    last_activity_date   TEXT,
    report_period        TEXT,
    windows              INTEGER DEFAULT 0,
    mac                  INTEGER DEFAULT 0,
    mobile               INTEGER DEFAULT 0,
    web                  INTEGER DEFAULT 0
    -- outlook/word/excel/powerpoint/onenote/teams flags moved to
    -- fact_user_app_activity (overlap with m365_app_users);
    -- fetch_m365_usage_proplus_detail() joins them back in.
);

CREATE TABLE IF NOT EXISTS billing_licences (
    product_title      TEXT PRIMARY KEY,
    total_licenses     INTEGER,
    expired_licenses   INTEGER,
    assigned_licenses  INTEGER,
    status_message     TEXT
);

CREATE INDEX IF NOT EXISTS idx_m365_activations_upn ON m365_usage_activations_users(user_principal_name);

-- ── Schema consolidation bookkeeping ───────────────────────────────────────
-- Gates the one-time table-consolidation migrations in _migrate(). A
-- migration is only marked applied after its data copy is row-count
-- verified — "destination has some rows" is not treated as "done", since a
-- killed process mid-copy on a large DB must not be mistaken for success.

CREATE TABLE IF NOT EXISTS _schema_migrations (
    id          TEXT PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

-- ── Cluster A: unified agent identity (Dataverse + Viva Copilot agents) ───
-- pva_agents.agent_id and viva_reports_cs_copilot_agents.agent_id are the
-- same Copilot Studio / Dataverse agent GUID space, so both sources are
-- COALESCE-merged into one row here. pva_agents becomes a compatibility
-- view over this table (see _migrate()); viva_reports_cs_copilot_agents is
-- retired in favour of fetch_viva_reports_cs_copilot_agents() reading
-- straight from dim_agent. m365_admin_agent_inventory / m365_usage_agents
-- are a DIFFERENT ID space (M365 Admin "Title ID") and are NOT part of
-- this table — they keep referencing dim_agent via their existing
-- bot_id/title_id crosswalk columns.

CREATE TABLE IF NOT EXISTS dim_agent (
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
    properties      TEXT,
    -- Viva Copilot-agents-report columns (only set when in_viva_report=1)
    description     TEXT,
    surface         TEXT,
    mode            TEXT,
    categories      TEXT,
    agent_type      TEXT,
    is_included     INTEGER DEFAULT 1,
    excluded_reason TEXT,
    icon            TEXT,
    in_viva_report  INTEGER DEFAULT 0
);

-- ── Cluster B: per-person weekly Copilot actions (Adoption + Impact) ──────
-- ~30 of the ~44 Adoption/Impact columns are the same metric reported by
-- both CSV exports; the rest are exclusive to one or the other. Shared and
-- adoption/impact-exclusive *action* columns live in the first table
-- (COALESCE-merged); Impact's work-pattern-only columns live in the second.
-- viva_reports_copilot_adoption / _impact become compatibility views.

CREATE TABLE IF NOT EXISTS fact_copilot_actions_per_person (
    person_id                          TEXT NOT NULL,
    metric_date                        TEXT NOT NULL,
    organization                       TEXT,
    chat_work_outlook                  INTEGER,
    chat_work_teams                    INTEGER,
    chat_web_teams                     INTEGER,
    chat_web_outlook                   INTEGER,
    chat_web_prompts                   INTEGER,
    chat_work_prompts                  INTEGER,
    word_work_prompts                  INTEGER,
    word_web_prompts                   INTEGER,
    excel_work_prompts                 INTEGER,
    excel_web_prompts                  INTEGER,
    ppt_work_prompts                   INTEGER,
    ppt_web_prompts                    INTEGER,
    word_chat_prompts                  INTEGER,
    ppt_chat_prompts                   INTEGER,
    excel_chat_prompts                 INTEGER,
    intelligent_recap_actions          INTEGER,
    visualize_table_word               INTEGER,
    add_content_ppt                    INTEGER,
    draft_word_doc                     INTEGER,
    summarize_word_doc                 INTEGER,
    email_coaching                     INTEGER,
    generate_email_draft               INTEGER,
    summarize_email_thread             INTEGER,
    excel_analysis                     INTEGER,
    excel_formatting                   INTEGER,
    create_excel_formula               INTEGER,
    summarize_meeting_teams            INTEGER,
    summarize_ppt                      INTEGER,
    create_ppt                         INTEGER,
    rewrite_text_word                  INTEGER,
    summarize_chat_teams               INTEGER,
    compose_chat_teams                 INTEGER,
    total_copilot_actions              INTEGER,
    total_copilot_active_days          INTEGER,
    total_copilot_enabled_days         INTEGER,
    meeting_hours_summarized           REAL,
    actions_copilot_chat               INTEGER,
    actions_excel                      INTEGER,
    actions_outlook                    INTEGER,
    actions_powerpoint                 INTEGER,
    actions_teams                      INTEGER,
    actions_word                       INTEGER,
    chat_conversations_summarized      INTEGER,
    meetings_summarized                INTEGER,
    organize_ppt                       INTEGER,
    in_adoption_report                 INTEGER DEFAULT 0,
    in_impact_report                   INTEGER DEFAULT 0,
    PRIMARY KEY (person_id, metric_date)
);

CREATE TABLE IF NOT EXISTS fact_copilot_work_patterns (
    person_id                   TEXT NOT NULL,
    metric_date                 TEXT NOT NULL,
    is_active                   INTEGER,
    weekend_days                TEXT,
    attended_meetings           REAL,
    meetings                    REAL,
    meeting_hours               REAL,
    uninterrupted_hours         REAL,
    small_meeting_hours         REAL,
    multitasking_hours          REAL,
    conflicting_meeting_hours   REAL,
    chats_sent                  INTEGER,
    emails_sent                 INTEGER,
    emails_sent_with_copilot    INTEGER,
    PRIMARY KEY (person_id, metric_date)
);

CREATE INDEX IF NOT EXISTS idx_copilot_actions_person ON fact_copilot_actions_per_person(person_id);
CREATE INDEX IF NOT EXISTS idx_copilot_actions_date   ON fact_copilot_actions_per_person(metric_date);

-- ── Cluster C: per-service usage counts (long format) ─────────────────────
-- m365_usage_active_users_services / _activity / m365_usage_active_user_counts
-- were three near-identical wide tables (same service list, same shape) fed
-- by three separate CSV exports. metric_source disambiguates the origin, so
-- each source only ever writes its own partition (no cross-source COALESCE
-- needed). Compatibility views pivot this back to each original wide shape.

CREATE TABLE IF NOT EXISTS fact_service_usage (
    metric_date         TEXT NOT NULL,   -- report_date (activity/counts) or report_refresh_date (services)
    report_period       TEXT NOT NULL,
    service_name        TEXT NOT NULL,   -- exchange | onedrive | sharepoint | skype | yammer | teams | office365
    metric_source       TEXT NOT NULL,   -- 'services' | 'activity' | 'counts'
    active_count        INTEGER,
    inactive_count       INTEGER,
    report_refresh_date  TEXT,
    PRIMARY KEY (metric_date, report_period, service_name, metric_source)
);

-- ── Cluster D: user display-name dimension ─────────────────────────────────
-- display_name was duplicated across m365_copilot_usage, m365_o365_active_users,
-- m365_usage_active_users_detail, and m365_usage_users (all keyed on the same
-- UPN space, though m365_usage_users names its key column "username"). Those
-- four tables' own display_name column is dropped; their fetch_* methods
-- LEFT JOIN this table back in so their returned dict shape is unchanged.

CREATE TABLE IF NOT EXISTS dim_user (
    user_principal_name TEXT PRIMARY KEY,
    display_name         TEXT
);

-- ── Cluster E: per-app activation flags (long format) ──────────────────────
-- m365_app_users and m365_usage_proplus_detail both carry boolean "is this
-- M365 app active" flags for the overlapping app set (outlook/word/excel/
-- powerpoint/onenote/teams). Each table keeps its own unique columns
-- (m365_app_users: sharepoint/onedrive flags; proplus_detail: platform
-- flags) — only the overlapping per-app flags move here.

CREATE TABLE IF NOT EXISTS fact_user_app_activity (
    user_principal_name  TEXT NOT NULL,
    app_name             TEXT NOT NULL,
    source                TEXT NOT NULL,   -- 'm365_app_users' | 'm365_usage_proplus_detail'
    is_active              INTEGER,
    report_period           TEXT,
    report_refresh_date      TEXT,
    PRIMARY KEY (user_principal_name, app_name, source)
);
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


def _capacity_consumption_row_id(r: dict) -> str:
    # Natural key (environment/resource/feature/channel/billable/date) isn't fully
    # unique — the same resource can appear twice on one date under a renamed
    # ResourceName, so fold that in too.
    key = (
        f"{r.get('environment_id')}|{r.get('resource_id')}|{r.get('resource_name')}|"
        f"{r.get('feature_name')}|{r.get('channel_id')}|{r.get('is_billable')}|{r.get('consumption_date')}"
    )
    return hashlib.sha1(key.encode()).hexdigest()


def _entitlement_per_agent_row_id(r: dict) -> str:
    key = (
        f"{r.get('agent_id')}|{r.get('ai_feature')}|{r.get('channel')}|"
        f"{r.get('tool_used')}|{r.get('scenario_name')}|{r.get('environment_id')}"
    )
    return hashlib.sha1(key.encode()).hexdigest()


# Columns shared by fact_copilot_actions_per_person, written by both the
# Copilot Adoption and Copilot Impact CSV importers. Defined once so the
# upsert SQL (ON CONFLICT column list) and the compatibility-view column
# lists can't drift apart from each other.
_COPILOT_ACTION_COLUMNS = (
    "organization",
    "chat_work_outlook", "chat_work_teams", "chat_web_teams", "chat_web_outlook",
    "chat_web_prompts", "chat_work_prompts",
    "word_work_prompts", "word_web_prompts",
    "excel_work_prompts", "excel_web_prompts",
    "ppt_work_prompts", "ppt_web_prompts",
    "word_chat_prompts", "ppt_chat_prompts", "excel_chat_prompts",
    "intelligent_recap_actions", "visualize_table_word", "add_content_ppt",
    "draft_word_doc", "summarize_word_doc", "email_coaching",
    "generate_email_draft", "summarize_email_thread",
    "excel_analysis", "excel_formatting", "create_excel_formula",
    "summarize_meeting_teams", "summarize_ppt", "create_ppt", "rewrite_text_word",
    "summarize_chat_teams", "compose_chat_teams",
    "total_copilot_actions", "total_copilot_active_days", "total_copilot_enabled_days",
    "meeting_hours_summarized",
    "actions_copilot_chat", "actions_excel", "actions_outlook",
    "actions_powerpoint", "actions_teams", "actions_word",
    "chat_conversations_summarized", "meetings_summarized", "organize_ppt",
)

# Columns present on the original viva_reports_copilot_adoption table
# (a subset of _COPILOT_ACTION_COLUMNS — excludes Impact-only action columns).
_ADOPTION_ACTION_COLUMNS = tuple(
    c for c in _COPILOT_ACTION_COLUMNS
    if c not in ("chat_conversations_summarized", "meetings_summarized", "organize_ppt")
)

# Columns present on the original viva_reports_copilot_impact table
# (a subset of _COPILOT_ACTION_COLUMNS — excludes Adoption-only action columns).
_IMPACT_ACTION_COLUMNS = tuple(
    c for c in _COPILOT_ACTION_COLUMNS
    if c not in (
        "chat_work_outlook", "chat_work_teams", "chat_web_teams", "chat_web_outlook",
        "word_chat_prompts", "ppt_chat_prompts", "excel_chat_prompts",
        "actions_copilot_chat", "actions_excel", "actions_outlook",
        "actions_powerpoint", "actions_teams", "actions_word",
    )
)

# fact_copilot_work_patterns columns — exclusive to the Copilot Impact CSV.
_COPILOT_WORK_PATTERN_COLUMNS = (
    "is_active", "weekend_days",
    "attended_meetings", "meetings", "meeting_hours", "uninterrupted_hours",
    "small_meeting_hours", "multitasking_hours", "conflicting_meeting_hours",
    "chats_sent", "emails_sent", "emails_sent_with_copilot",
)

# Service names fanned out into fact_service_usage rows. 'office365' is a
# tenant-wide rollup present on the 'services' and 'counts' sources but not
# 'activity'.
_SERVICE_NAMES = ("exchange", "onedrive", "sharepoint", "skype", "yammer", "teams")

# app_name -> source column name, per table (the two sources name PowerPoint
# differently: m365_app_users uses "ppt_active", proplus_detail uses
# "powerpoint" — fact_user_app_activity normalizes both to app_name="powerpoint").
_APP_USERS_COLUMNS = {
    "outlook": "outlook_active", "word": "word_active", "excel": "excel_active",
    "powerpoint": "ppt_active", "onenote": "onenote_active", "teams": "teams_active",
}
_PROPLUS_APP_COLUMNS = {
    "outlook": "outlook", "word": "word", "excel": "excel",
    "powerpoint": "powerpoint", "onenote": "onenote", "teams": "teams",
}


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
        # Rename legacy bot_id column → agent_id. Guarded on pva_agents still
        # being a real table — once dim_agent migration has run, pva_agents
        # is a VIEW and none of this applies (ALTER TABLE on a view errors).
        if "pva_agents" in tables:
            agent_cols = {
                row[1]
                for row in self._conn.execute("PRAGMA table_info(pva_agents)").fetchall()
            }
            if "bot_id" in agent_cols:
                self._conn.execute("ALTER TABLE pva_agents RENAME COLUMN bot_id TO agent_id")
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
        sol_cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(pva_agent_solutions)").fetchall()
        }
        if "bot_id" in sol_cols:
            self._conn.execute("ALTER TABLE pva_agent_solutions RENAME COLUMN bot_id TO agent_id")

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

        # Rename viva_* / viva_cs_* Copilot Studio tables → viva_reports_cs_*
        all_tables = {
            row[0] for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for old, new in [
            ("viva_session_metrics",            "viva_reports_cs_session_metrics"),
            ("viva_topic_metrics",              "viva_reports_cs_topic_metrics"),
            ("viva_knowledge_source_metrics",   "viva_reports_cs_knowledge_source_metrics"),
            ("viva_autonomous_trigger_metrics", "viva_reports_cs_autonomous_trigger_metrics"),
            ("viva_autonomous_metrics",         "viva_reports_cs_autonomous_metrics"),
            ("viva_action_metrics",             "viva_reports_cs_action_metrics"),
            ("viva_copilot_agents",             "viva_reports_cs_copilot_agents"),
            ("viva_weekly_active_users",        "viva_reports_cs_weekly_active_users"),
            ("viva_extended_metadata",          "viva_reports_cs_extended_metadata"),
            # viva_cs_* → viva_reports_cs_* (previous naming)
            ("viva_cs_session_metrics",            "viva_reports_cs_session_metrics"),
            ("viva_cs_topic_metrics",              "viva_reports_cs_topic_metrics"),
            ("viva_cs_knowledge_source_metrics",   "viva_reports_cs_knowledge_source_metrics"),
            ("viva_cs_autonomous_trigger_metrics", "viva_reports_cs_autonomous_trigger_metrics"),
            ("viva_cs_autonomous_metrics",         "viva_reports_cs_autonomous_metrics"),
            ("viva_cs_action_metrics",             "viva_reports_cs_action_metrics"),
            ("viva_cs_copilot_agents",             "viva_reports_cs_copilot_agents"),
            ("viva_cs_weekly_active_users",        "viva_reports_cs_weekly_active_users"),
            ("viva_cs_extended_metadata",          "viva_reports_cs_extended_metadata"),
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

        # Table-consolidation migrations (dim_agent, fact_* tables). Each is
        # idempotent and gated on _schema_migrations so a killed process
        # mid-copy retries on next startup instead of being treated as done.
        self._migrate_dim_agent()
        self._migrate_copilot_actions()
        self._migrate_service_usage()
        self._migrate_dim_user()
        self._migrate_app_activity()

    # ------------------------------------------------------------------
    # Migration sentinel helpers
    # ------------------------------------------------------------------

    def _migration_applied(self, migration_id: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM _schema_migrations WHERE id = ?", (migration_id,)
        ).fetchone() is not None

    def _mark_migration_applied(self, migration_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO _schema_migrations (id, applied_at) VALUES (?, ?)",
            (migration_id, datetime.now(timezone.utc).isoformat()),
        )

    def _upsert_copilot_actions(self, r: dict, source_col: str) -> int:
        """Shared by upsert_viva_reports_copilot_adoption/_impact: COALESCE-
        upsert the columns both CSV exports can supply into
        fact_copilot_actions_per_person, and flag which source wrote it via
        source_col ('in_adoption_report' or 'in_impact_report')."""
        cols = _COPILOT_ACTION_COLUMNS
        col_list = ", ".join(("person_id", "metric_date") + cols + (source_col,))
        placeholders = ", ".join(["?"] * (2 + len(cols) + 1))
        set_clause = ",\n                        ".join(
            f"{c} = COALESCE(excluded.{c}, fact_copilot_actions_per_person.{c})" for c in cols
        )
        cur = self._conn.execute(
            f"""
            INSERT INTO fact_copilot_actions_per_person ({col_list})
            VALUES ({placeholders})
            ON CONFLICT(person_id, metric_date) DO UPDATE SET
                {set_clause},
                {source_col} = 1
            """,
            (r['person_id'], r['metric_date'], *(r.get(c) for c in cols), 1),
        )
        return cur.rowcount

    def _migrate_dim_agent(self) -> None:
        """Cluster A: fold pva_agents + viva_reports_cs_copilot_agents into
        dim_agent, then replace both old table names with compatibility
        views. Safe to call on every startup — no-ops once applied."""
        if self._migration_applied("dim_agent_v1"):
            return

        tables = {
            row[0] for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        pva_count = 0
        if "pva_agents" in tables:
            rows = self._conn.execute(
                "SELECT agent_id, display_name, schema_name, environment_id, created_at, "
                "modified_at, published_at, created_by, owner_id, created_in, ai_model, properties "
                "FROM pva_agents"
            ).fetchall()
            for r in rows:
                self._conn.execute(
                    """
                    INSERT INTO dim_agent
                    (agent_id, display_name, schema_name, environment_id, created_at,
                     modified_at, published_at, created_by, owner_id, created_in, ai_model, properties)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(agent_id) DO UPDATE SET
                        display_name   = COALESCE(excluded.display_name,   dim_agent.display_name),
                        schema_name    = COALESCE(excluded.schema_name,    dim_agent.schema_name),
                        environment_id = COALESCE(excluded.environment_id, dim_agent.environment_id),
                        created_at     = COALESCE(excluded.created_at,     dim_agent.created_at),
                        modified_at    = COALESCE(excluded.modified_at,    dim_agent.modified_at),
                        published_at   = COALESCE(excluded.published_at,   dim_agent.published_at),
                        created_by     = COALESCE(excluded.created_by,     dim_agent.created_by),
                        owner_id       = COALESCE(excluded.owner_id,       dim_agent.owner_id),
                        created_in     = COALESCE(excluded.created_in,     dim_agent.created_in),
                        ai_model       = COALESCE(excluded.ai_model,       dim_agent.ai_model),
                        properties     = COALESCE(excluded.properties,     dim_agent.properties)
                    """,
                    tuple(r),
                )
            pva_count = len(rows)

        viva_count = 0
        if "viva_reports_cs_copilot_agents" in tables:
            rows = self._conn.execute(
                "SELECT agent_id, agent_name, description, surface, mode, categories, "
                "agent_type, is_included, excluded_reason, icon FROM viva_reports_cs_copilot_agents"
            ).fetchall()
            for r in rows:
                self._conn.execute(
                    """
                    INSERT INTO dim_agent
                    (agent_id, display_name, description, surface, mode, categories,
                     agent_type, is_included, excluded_reason, icon, in_viva_report)
                    VALUES (?,?,?,?,?,?,?,?,?,?,1)
                    ON CONFLICT(agent_id) DO UPDATE SET
                        display_name    = COALESCE(excluded.display_name,    dim_agent.display_name),
                        description     = COALESCE(excluded.description,     dim_agent.description),
                        surface         = COALESCE(excluded.surface,         dim_agent.surface),
                        mode            = COALESCE(excluded.mode,            dim_agent.mode),
                        categories      = COALESCE(excluded.categories,      dim_agent.categories),
                        agent_type      = COALESCE(excluded.agent_type,      dim_agent.agent_type),
                        is_included     = COALESCE(excluded.is_included,     dim_agent.is_included),
                        excluded_reason = COALESCE(excluded.excluded_reason, dim_agent.excluded_reason),
                        icon            = COALESCE(excluded.icon,            dim_agent.icon),
                        in_viva_report  = 1
                    """,
                    (r["agent_id"], r["agent_name"], r["description"], r["surface"], r["mode"],
                     r["categories"], r["agent_type"], r["is_included"], r["excluded_reason"], r["icon"]),
                )
            viva_count = len(rows)

        dim_agent_count = self._conn.execute("SELECT COUNT(*) FROM dim_agent").fetchone()[0]
        if dim_agent_count < max(pva_count, viva_count):
            return  # copy didn't fully land — retry on next startup, don't mark applied

        if "pva_agents" in tables:
            self._conn.execute("DROP TABLE pva_agents")
        if "viva_reports_cs_copilot_agents" in tables:
            self._conn.execute("DROP TABLE viva_reports_cs_copilot_agents")

        self._conn.execute("""
            CREATE VIEW IF NOT EXISTS pva_agents AS
            SELECT agent_id, display_name, schema_name, environment_id, created_at,
                   modified_at, published_at, created_by, owner_id, created_in, ai_model, properties
            FROM dim_agent
        """)
        self._conn.execute("""
            CREATE VIEW IF NOT EXISTS viva_reports_cs_copilot_agents AS
            SELECT agent_id, display_name AS agent_name, description, surface, mode,
                   categories, agent_type, is_included, excluded_reason, icon
            FROM dim_agent WHERE in_viva_report = 1
        """)
        self._mark_migration_applied("dim_agent_v1")

    def _migrate_copilot_actions(self) -> None:
        """Cluster B: fold viva_reports_copilot_adoption + _impact into
        fact_copilot_actions_per_person / fact_copilot_work_patterns, then
        replace both old table names with compatibility views."""
        if self._migration_applied("copilot_actions_v1"):
            return

        tables = {
            row[0] for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        adoption_count = 0
        if "viva_reports_copilot_adoption" in tables:
            rows = self._conn.execute("SELECT * FROM viva_reports_copilot_adoption").fetchall()
            for row in rows:
                self._upsert_copilot_actions(dict(row), "in_adoption_report")
            adoption_count = len(rows)

        impact_count = 0
        if "viva_reports_copilot_impact" in tables:
            rows = self._conn.execute("SELECT * FROM viva_reports_copilot_impact").fetchall()
            for row in rows:
                r = dict(row)
                self._upsert_copilot_actions(r, "in_impact_report")
                self._upsert_copilot_work_patterns(r)
            impact_count = len(rows)

        actions_count = self._conn.execute(
            "SELECT COUNT(*) FROM fact_copilot_actions_per_person"
        ).fetchone()[0]
        patterns_count = self._conn.execute(
            "SELECT COUNT(*) FROM fact_copilot_work_patterns"
        ).fetchone()[0]
        if actions_count < max(adoption_count, impact_count) or patterns_count < impact_count:
            return  # copy didn't fully land — retry on next startup, don't mark applied

        if "viva_reports_copilot_adoption" in tables:
            self._conn.execute("DROP TABLE viva_reports_copilot_adoption")
        if "viva_reports_copilot_impact" in tables:
            self._conn.execute("DROP TABLE viva_reports_copilot_impact")

        adoption_cols = ", ".join(_ADOPTION_ACTION_COLUMNS)
        self._conn.execute(f"""
            CREATE VIEW IF NOT EXISTS viva_reports_copilot_adoption AS
            SELECT person_id, metric_date, {adoption_cols}
            FROM fact_copilot_actions_per_person
            WHERE in_adoption_report = 1
        """)
        impact_act_cols = ", ".join(f"a.{c}" for c in _IMPACT_ACTION_COLUMNS)
        impact_pat_cols = ", ".join(f"p.{c}" for c in _COPILOT_WORK_PATTERN_COLUMNS)
        self._conn.execute(f"""
            CREATE VIEW IF NOT EXISTS viva_reports_copilot_impact AS
            SELECT a.person_id, a.metric_date, {impact_act_cols}, {impact_pat_cols}
            FROM fact_copilot_actions_per_person a
            LEFT JOIN fact_copilot_work_patterns p
                ON p.person_id = a.person_id AND p.metric_date = a.metric_date
            WHERE a.in_impact_report = 1
        """)
        self._mark_migration_applied("copilot_actions_v1")

    def _migrate_service_usage(self) -> None:
        """Cluster C: fold m365_usage_active_users_services / _activity /
        m365_usage_active_user_counts into fact_service_usage (long format),
        then replace all three old table names with compatibility views."""
        if self._migration_applied("service_usage_v1"):
            return

        tables = {
            row[0] for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        expected = 0
        if "m365_usage_active_users_services" in tables:
            rows = self._conn.execute("SELECT * FROM m365_usage_active_users_services").fetchall()
            for row in rows:
                r = dict(row)
                for svc in _SERVICE_NAMES + ("office365",):
                    self._upsert_service_usage_row(
                        r.get('report_refresh_date'), r.get('report_period'), svc, 'services',
                        r.get(f'{svc}_active'), r.get(f'{svc}_inactive'), r.get('report_refresh_date'),
                    )
            expected += len(rows) * 7

        if "m365_usage_active_users_activity" in tables:
            rows = self._conn.execute("SELECT * FROM m365_usage_active_users_activity").fetchall()
            for row in rows:
                r = dict(row)
                for svc in _SERVICE_NAMES:
                    self._upsert_service_usage_row(
                        r.get('report_date'), r.get('report_period'), svc, 'activity',
                        r.get(svc), None, r.get('report_refresh_date'),
                    )
            expected += len(rows) * len(_SERVICE_NAMES)

        if "m365_usage_active_user_counts" in tables:
            rows = self._conn.execute("SELECT * FROM m365_usage_active_user_counts").fetchall()
            for row in rows:
                r = dict(row)
                for svc in _SERVICE_NAMES + ("office365",):
                    self._upsert_service_usage_row(
                        r.get('report_date'), r.get('report_period'), svc, 'counts',
                        r.get(svc), None, r.get('report_refresh_date'),
                    )
            expected += len(rows) * 7

        actual = self._conn.execute("SELECT COUNT(*) FROM fact_service_usage").fetchone()[0]
        if actual < expected:
            return  # copy didn't fully land — retry on next startup, don't mark applied

        for t in ("m365_usage_active_users_services", "m365_usage_active_users_activity",
                  "m365_usage_active_user_counts"):
            if t in tables:
                self._conn.execute(f"DROP TABLE {t}")

        services_cols = ", ".join(
            f"MAX(CASE WHEN service_name='{s}' THEN active_count END) AS {s}_active, "
            f"MAX(CASE WHEN service_name='{s}' THEN inactive_count END) AS {s}_inactive"
            for s in _SERVICE_NAMES + ("office365",)
        )
        self._conn.execute(f"""
            CREATE VIEW IF NOT EXISTS m365_usage_active_users_services AS
            SELECT metric_date AS report_refresh_date, report_period, {services_cols}
            FROM fact_service_usage WHERE metric_source = 'services'
            GROUP BY metric_date, report_period
        """)
        activity_cols = ", ".join(
            f"MAX(CASE WHEN service_name='{s}' THEN active_count END) AS {s}" for s in _SERVICE_NAMES
        )
        self._conn.execute(f"""
            CREATE VIEW IF NOT EXISTS m365_usage_active_users_activity AS
            SELECT metric_date AS report_date, report_period,
                   MAX(report_refresh_date) AS report_refresh_date, {activity_cols}
            FROM fact_service_usage WHERE metric_source = 'activity'
            GROUP BY metric_date, report_period
        """)
        counts_cols = ", ".join(
            f"MAX(CASE WHEN service_name='{s}' THEN active_count END) AS {s}"
            for s in _SERVICE_NAMES + ("office365",)
        )
        self._conn.execute(f"""
            CREATE VIEW IF NOT EXISTS m365_usage_active_user_counts AS
            SELECT metric_date AS report_date, report_period,
                   MAX(report_refresh_date) AS report_refresh_date, {counts_cols}
            FROM fact_service_usage WHERE metric_source = 'counts'
            GROUP BY metric_date, report_period
        """)
        self._mark_migration_applied("service_usage_v1")

    def _migrate_dim_user(self) -> None:
        """Cluster D: fold the display_name column out of m365_copilot_usage,
        m365_o365_active_users, m365_usage_active_users_detail, and
        m365_usage_users into dim_user, then DROP that column from each
        (their fetch_* methods JOIN it back in). Unlike Clusters A-C these
        tables aren't being renamed/replaced with views — only their
        display_name column moves — so CREATE TABLE IF NOT EXISTS in _DDL
        won't touch an already-existing table's columns; this explicit
        ALTER TABLE ... DROP COLUMN is what actually removes it.
        Each source table is verified and dropped independently, so a
        partial failure only blocks that table's column drop and retries
        it (only it) on the next startup."""
        if self._migration_applied("dim_user_v1"):
            return

        sources = [
            ("m365_copilot_usage", "user_principal_name"),
            ("m365_o365_active_users", "user_principal_name"),
            ("m365_usage_active_users_detail", "user_principal_name"),
            ("m365_usage_users", "username"),
        ]
        tables = {
            row[0] for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        all_done = True
        for table, key_col in sources:
            if table not in tables:
                continue
            cols = {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if "display_name" not in cols:
                continue  # already migrated

            rows = self._conn.execute(f"SELECT {key_col}, display_name FROM {table}").fetchall()
            for upn, display_name in rows:
                self._upsert_dim_user(upn, display_name)

            missing = self._conn.execute(
                f"""
                SELECT COUNT(*) FROM {table} t
                LEFT JOIN dim_user u ON u.user_principal_name = t.{key_col}
                WHERE t.{key_col} IS NOT NULL AND t.{key_col} != '' AND u.user_principal_name IS NULL
                """
            ).fetchone()[0]
            if missing > 0:
                all_done = False
                continue  # copy didn't fully land — retry this table on next startup

            self._conn.execute(f"ALTER TABLE {table} DROP COLUMN display_name")

        if all_done:
            self._mark_migration_applied("dim_user_v1")

    def _migrate_app_activity(self) -> None:
        """Cluster E: fold the overlapping per-app active flags out of
        m365_app_users and m365_usage_proplus_detail into
        fact_user_app_activity, then DROP those columns from each source
        table (their fetch_* methods JOIN/pivot it back in). Same
        per-table independent verify-then-drop pattern as _migrate_dim_user."""
        if self._migration_applied("app_activity_v1"):
            return

        sources = [
            ("m365_app_users", _APP_USERS_COLUMNS, "m365_app_users"),
            ("m365_usage_proplus_detail", _PROPLUS_APP_COLUMNS, "m365_usage_proplus_detail"),
        ]
        tables = {
            row[0] for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        all_done = True
        for table, app_cols, source_tag in sources:
            if table not in tables:
                continue
            existing_cols = {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()}
            cols_to_drop = [c for c in app_cols.values() if c in existing_cols]
            if not cols_to_drop:
                continue  # already migrated

            select_cols = ", ".join(("user_principal_name", "report_period", "report_refresh_date")
                                     + tuple(cols_to_drop))
            rows = self._conn.execute(f"SELECT {select_cols} FROM {table}").fetchall()
            for row in rows:
                r = dict(row)
                for app, col in app_cols.items():
                    if col not in r:
                        continue
                    self._upsert_app_activity_row(
                        r["user_principal_name"], app, source_tag, r[col],
                        r.get("report_period"), r.get("report_refresh_date"),
                    )

            missing = self._conn.execute(
                f"""
                SELECT COUNT(*) FROM {table} t
                LEFT JOIN fact_user_app_activity f
                    ON f.user_principal_name = t.user_principal_name AND f.source = '{source_tag}'
                WHERE t.user_principal_name IS NOT NULL AND t.user_principal_name != ''
                  AND f.user_principal_name IS NULL
                """
            ).fetchone()[0]
            if missing > 0:
                all_done = False
                continue  # copy didn't fully land — retry this table on next startup

            for col in cols_to_drop:
                self._conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")

        if all_done:
            self._mark_migration_applied("app_activity_v1")

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
        """Insert or update dim_agent from Dataverse/PP-Admin agent records
        (pva_agents is a compatibility view over dim_agent). Multiple callers
        of this method supply different column subsets (dataverse.py vs.
        powerplatform_admin.py) — COALESCE preserves whichever source already
        populated a column instead of the previous full-row REPLACE, which
        would null out one source's columns when the other ran afterward.
        Returns count of rows written."""
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
                    INSERT INTO dim_agent
                    (agent_id, display_name, schema_name, environment_id,
                     created_at, modified_at, published_at,
                     created_by, owner_id, created_in, ai_model, properties)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(agent_id) DO UPDATE SET
                        display_name   = COALESCE(excluded.display_name,   dim_agent.display_name),
                        schema_name    = COALESCE(excluded.schema_name,    dim_agent.schema_name),
                        environment_id = COALESCE(excluded.environment_id, dim_agent.environment_id),
                        created_at     = COALESCE(excluded.created_at,     dim_agent.created_at),
                        modified_at    = COALESCE(excluded.modified_at,    dim_agent.modified_at),
                        published_at   = COALESCE(excluded.published_at,   dim_agent.published_at),
                        created_by     = COALESCE(excluded.created_by,     dim_agent.created_by),
                        owner_id       = COALESCE(excluded.owner_id,       dim_agent.owner_id),
                        created_in     = COALESCE(excluded.created_in,     dim_agent.created_in),
                        ai_model       = COALESCE(excluded.ai_model,       dim_agent.ai_model),
                        properties     = COALESCE(excluded.properties,     dim_agent.properties)
                    """,
                    (
                        b.get("id") or b.get("botId") or None,
                        b.get("name") or b.get("displayName") or None,
                        b.get("schemaName") or None,
                        b.get("environmentId") or None,
                        b.get("createdDateTime") or None,
                        b.get("modifiedDateTime") or None,
                        b.get("publishedDateTime") or None,
                        b.get("createdBy") or None,
                        b.get("ownerId") or None,
                        b.get("createdIn") or None,
                        b.get("aiModel") or None,
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
            "FROM dim_agent ORDER BY display_name"
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

    def _upsert_dim_user(self, upn: str, display_name: str | None) -> None:
        """COALESCE-upsert a user's display_name into dim_user. Called from
        every fetch source that observes a user, so whichever source runs
        first doesn't get overwritten with a blank name by one that doesn't
        carry it."""
        if not upn:
            return
        self._conn.execute(
            """
            INSERT INTO dim_user (user_principal_name, display_name)
            VALUES (?, ?)
            ON CONFLICT(user_principal_name) DO UPDATE SET
                display_name = COALESCE(excluded.display_name, dim_user.display_name)
            """,
            (upn, display_name or None),
        )

    def upsert_copilot_usage(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                self._upsert_dim_user(r["user_principal_name"], r.get("display_name"))
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_copilot_usage VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r["user_principal_name"],
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
            """
            SELECT m.*, u.display_name
            FROM m365_copilot_usage m
            LEFT JOIN dim_user u ON u.user_principal_name = m.user_principal_name
            ORDER BY m.user_principal_name
            """
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

    def upsert_viva_reports_cs_session_metrics(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_reports_cs_session_metrics VALUES
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

    def fetch_viva_reports_cs_session_metrics(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_reports_cs_session_metrics ORDER BY metric_date DESC, agent_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_reports_cs_topic_metrics(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_reports_cs_topic_metrics VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r['agent_id'], r['topic_id'], r.get('topic_name'), r['metric_date'],
                     r.get('total_sessions'), r.get('resolved_sessions'), r.get('escalated_sessions'),
                     r.get('abandoned_sessions'), r.get('engaged_sessions'), r.get('unengaged_sessions'),
                     r.get('csat_responses'), r.get('csat_1'), r.get('csat_2'), r.get('csat_3'),
                     r.get('csat_4'), r.get('csat_5')),
                )
                written += cur.rowcount
        return written

    def fetch_viva_reports_cs_topic_metrics(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_reports_cs_topic_metrics ORDER BY metric_date DESC, agent_id, topic_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_reports_cs_knowledge_source_metrics(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_reports_cs_knowledge_source_metrics VALUES
                    (?,?,?,?,?,?,?,?,?,?,?)""",
                    (r['agent_id'], r['source_type'], r['metric_date'],
                     r.get('count_total'), r.get('count_unengaged'), r.get('count_engaged'),
                     r.get('count_resolved'), r.get('count_escalated'), r.get('count_abandoned'),
                     r.get('count_autonomous'), r.get('count_successful_autonomous')),
                )
                written += cur.rowcount
        return written

    def fetch_viva_reports_cs_knowledge_source_metrics(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_reports_cs_knowledge_source_metrics ORDER BY metric_date DESC, agent_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_reports_cs_autonomous_metrics(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_reports_cs_autonomous_metrics VALUES
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

    def fetch_viva_reports_cs_autonomous_metrics(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_reports_cs_autonomous_metrics ORDER BY metric_date DESC, agent_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_reports_cs_autonomous_trigger_metrics(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_reports_cs_autonomous_trigger_metrics VALUES
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

    def fetch_viva_reports_cs_autonomous_trigger_metrics(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_reports_cs_autonomous_trigger_metrics ORDER BY metric_date DESC, agent_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_reports_cs_action_metrics(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_reports_cs_action_metrics VALUES (?,?,?,?,?,?,?)""",
                    (r['agent_id'], r['action_schema_name'], r['metric_date'],
                     r.get('total_runs'), r.get('successful_actions_in_runs'),
                     r.get('actions_in_successful_runs'), r.get('successful_actions_in_successful_runs')),
                )
                written += cur.rowcount
        return written

    def fetch_viva_reports_cs_action_metrics(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_reports_cs_action_metrics ORDER BY metric_date DESC, agent_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_reports_cs_copilot_agents(self, rows: list[dict]) -> int:
        """Insert or update dim_agent's Viva-report-derived columns
        (viva_reports_cs_copilot_agents is a compatibility view over
        dim_agent, filtered to in_viva_report=1). Returns rows written."""
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """
                    INSERT INTO dim_agent
                    (agent_id, display_name, description, surface, mode,
                     categories, agent_type, is_included, excluded_reason, icon, in_viva_report)
                    VALUES (?,?,?,?,?,?,?,?,?,?,1)
                    ON CONFLICT(agent_id) DO UPDATE SET
                        display_name    = COALESCE(excluded.display_name,    dim_agent.display_name),
                        description     = COALESCE(excluded.description,     dim_agent.description),
                        surface         = COALESCE(excluded.surface,         dim_agent.surface),
                        mode            = COALESCE(excluded.mode,            dim_agent.mode),
                        categories      = COALESCE(excluded.categories,      dim_agent.categories),
                        agent_type      = COALESCE(excluded.agent_type,      dim_agent.agent_type),
                        is_included     = COALESCE(excluded.is_included,     dim_agent.is_included),
                        excluded_reason = COALESCE(excluded.excluded_reason, dim_agent.excluded_reason),
                        icon            = COALESCE(excluded.icon,            dim_agent.icon),
                        in_viva_report  = 1
                    """,
                    (r['agent_id'], r.get('agent_name') or None, r.get('description') or None,
                     r.get('surface') or None, r.get('mode') or None, r.get('categories') or None,
                     r.get('agent_type') or None, r.get('is_included', 1), r.get('excluded_reason') or None,
                     r.get('icon') or None),
                )
                written += cur.rowcount
        return written

    def fetch_viva_reports_cs_copilot_agents(self) -> dict[str, dict]:
        """Returns {agent_id: row_dict} for O(1) lookup in sheet writers."""
        rows = self._conn.execute(
            "SELECT agent_id, display_name AS agent_name, description, surface, mode, "
            "categories, agent_type, is_included FROM dim_agent WHERE in_viva_report = 1"
        ).fetchall()
        return {r['agent_id']: dict(r) for r in rows}

    def upsert_viva_reports_cs_weekly_active_users(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_reports_cs_weekly_active_users VALUES (?,?,?)""",
                    (r['agent_id'], r['start_date'], r.get('active_user_count')),
                )
                written += cur.rowcount
        return written

    def fetch_viva_reports_cs_weekly_active_users(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_reports_cs_weekly_active_users ORDER BY start_date DESC, agent_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_reports_cs_extended_metadata(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_reports_cs_extended_metadata VALUES (?,?,?)""",
                    (r['agent_id'], r.get('aad_tenant_id'), r.get('roi_configuration')),
                )
                written += cur.rowcount
        return written

    def fetch_viva_reports_cs_extended_metadata(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM viva_reports_cs_extended_metadata").fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Viva Reports — Copilot Adoption & Impact
    # ------------------------------------------------------------------

    def upsert_viva_reports_copilot_adoption(self, rows: list[dict]) -> int:
        """viva_reports_copilot_adoption is now a compatibility view over
        fact_copilot_actions_per_person (see _migrate())."""
        written = 0
        with self._conn:
            for r in rows:
                written += self._upsert_copilot_actions(r, "in_adoption_report")
        return written

    def fetch_viva_reports_copilot_adoption(self) -> list[dict]:
        cols = ", ".join(_ADOPTION_ACTION_COLUMNS)
        rows = self._conn.execute(
            f"SELECT person_id, metric_date, {cols} FROM fact_copilot_actions_per_person "
            "WHERE in_adoption_report = 1 ORDER BY metric_date DESC, person_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def _upsert_copilot_work_patterns(self, r: dict) -> None:
        pat_cols = _COPILOT_WORK_PATTERN_COLUMNS
        col_list = ", ".join(("person_id", "metric_date") + pat_cols)
        set_clause = ",\n                    ".join(f"{c} = excluded.{c}" for c in pat_cols)
        self._conn.execute(
            f"""
            INSERT INTO fact_copilot_work_patterns ({col_list})
            VALUES ({", ".join(["?"] * (2 + len(pat_cols)))})
            ON CONFLICT(person_id, metric_date) DO UPDATE SET
                {set_clause}
            """,
            (r['person_id'], r['metric_date'], *(r.get(c) for c in pat_cols)),
        )

    def upsert_viva_reports_copilot_impact(self, rows: list[dict]) -> int:
        """viva_reports_copilot_impact is now a compatibility view joining
        fact_copilot_actions_per_person (shared action columns) and
        fact_copilot_work_patterns (Impact-only work-pattern columns) —
        see _migrate()."""
        written = 0
        with self._conn:
            for r in rows:
                written += self._upsert_copilot_actions(r, "in_impact_report")
                self._upsert_copilot_work_patterns(r)
        return written

    def fetch_viva_reports_copilot_impact(self) -> list[dict]:
        act_cols = ", ".join(f"a.{c}" for c in _IMPACT_ACTION_COLUMNS)
        pat_cols = ", ".join(f"p.{c}" for c in _COPILOT_WORK_PATTERN_COLUMNS)
        rows = self._conn.execute(
            f"""
            SELECT a.person_id, a.metric_date, {act_cols}, {pat_cols}
            FROM fact_copilot_actions_per_person a
            LEFT JOIN fact_copilot_work_patterns p
                ON p.person_id = a.person_id AND p.metric_date = a.metric_date
            WHERE a.in_impact_report = 1
            ORDER BY a.metric_date DESC, a.person_id
            """
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # M365 Admin — Agent Inventory
    # ------------------------------------------------------------------

    def upsert_m365_admin_agent_inventory(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_admin_agent_inventory VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        r.get('title_id'), r.get('name'), r.get('status'), r.get('channel'),
                        r.get('date_created'), r.get('last_modified'), r.get('publisher'),
                        r.get('publisher_type'), r.get('version'), r.get('owner'),
                        r.get('description'), r.get('platform'), r.get('creator_id'),
                        r.get('environment_id'), r.get('bot_id'), r.get('custom_actions'),
                        r.get('custom_action_list'), r.get('sensitivity'),
                        r.get('can_read_od_sp'), r.get('od_sp_items'),
                        r.get('can_read_od_files'), r.get('od_files'), r.get('od_sites'),
                        r.get('can_read_sp_sites'), r.get('sp_files'), r.get('sp_sites'),
                        r.get('can_extend_graph'), r.get('graph_connector_details'),
                        r.get('can_generate_images'), r.get('can_use_code_interpreter'),
                        r.get('contains_uploaded_files'), r.get('uploaded_files'),
                        r.get('instructions'), r.get('groups_shared'), r.get('users_shared'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_m365_admin_agent_inventory(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_admin_agent_inventory ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # M365 Usage — Agent Activity + Per-User Activity
    # ------------------------------------------------------------------

    def upsert_m365_usage_agents(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_usage_agents VALUES (?,?,?,?,?,?,?)""",
                    (
                        r.get('agent_id'), r.get('agent_name'), r.get('creator_type'),
                        r.get('active_users_licensed'), r.get('active_users_unlicensed'),
                        r.get('responses_sent'), r.get('last_activity_date'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_m365_usage_agents(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_usage_agents ORDER BY responses_sent DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_usage_agent_users(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_usage_agent_users VALUES (?,?,?,?,?,?)""",
                    (
                        r.get('agent_id'), r.get('username'), r.get('agent_name'),
                        r.get('creator_type'), r.get('responses_sent'),
                        r.get('last_activity_date'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_m365_usage_agent_users(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_usage_agent_users ORDER BY agent_id, responses_sent DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Tokenomics — Copilot Credit Consumption (Power Platform Admin)
    # ------------------------------------------------------------------

    def upsert_tokenomics_capacity_consumption(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO tokenomics_capacity_consumption VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        _capacity_consumption_row_id(r), r.get('tenant_id'), r.get('environment_id'),
                        r.get('environment_name'), r.get('environment_type'), r.get('resource_id'),
                        r.get('resource_name'), r.get('resource_type'), r.get('product_name'),
                        r.get('feature_name'), r.get('channel_id'), r.get('is_billable'),
                        r.get('unit'), r.get('consumption_date'), r.get('consumed_quantity'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_tokenomics_capacity_consumption(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM tokenomics_capacity_consumption ORDER BY consumption_date DESC, environment_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_tokenomics_entitlement_consumption(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO tokenomics_entitlement_consumption VALUES
                    (?,?,?,?,?,?,?,?,?)""",
                    (
                        r.get('billing_plan_id'), r.get('billing_plan_name'), r.get('environment_id'),
                        r.get('environment_name'), r.get('capacity_type'), r.get('entitled_quantity'),
                        r.get('prepaid_consumed_quantity'), r.get('payg_consumed_quantity'),
                        r.get('usage_date'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_tokenomics_entitlement_consumption(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM tokenomics_entitlement_consumption ORDER BY usage_date DESC, environment_name"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Experience Model — dim_agent_journey_persona + XLA scoring
    # ------------------------------------------------------------------

    def upsert_dim_agent_journey_persona(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO dim_agent_journey_persona VALUES (?,?,?,?)""",
                    (
                        r.get('agent_id'), r.get('journey_name'),
                        r.get('persona_type'), r.get('agent_name'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_dim_agent_journey_persona(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM dim_agent_journey_persona ORDER BY persona_type, journey_name, agent_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def fetch_xla_by_persona_journey(self) -> list[dict]:
        """Aggregate session metrics grouped by persona + journey via the mapping dimension."""
        rows = self._conn.execute("""
            SELECT
                m.persona_type,
                m.journey_name,
                COUNT(DISTINCT s.agent_id)                                           AS agent_count,
                SUM(s.total_sessions)                                                AS total_sessions,
                SUM(s.resolved_sessions)                                             AS resolved_sessions,
                SUM(s.escalated_sessions)                                            AS escalated_sessions,
                SUM(s.abandoned_sessions)                                            AS abandoned_sessions,
                SUM(s.engaged_sessions)                                              AS engaged_sessions,
                ROUND(SUM(s.resolved_sessions)  * 100.0 / NULLIF(SUM(s.total_sessions), 0), 1) AS completion_rate_pct,
                ROUND(SUM(s.escalated_sessions) * 100.0 / NULLIF(SUM(s.total_sessions), 0), 1) AS escalation_rate_pct,
                ROUND(SUM(s.abandoned_sessions) * 100.0 / NULLIF(SUM(s.total_sessions), 0), 1) AS abandonment_rate_pct,
                ROUND(
                    (
                        COALESCE(SUM(s.resolved_sessions) * 100.0 / NULLIF(SUM(s.total_sessions), 0), 0) * 0.6 +
                        (100.0 - COALESCE(SUM(s.escalated_sessions) * 100.0 / NULLIF(SUM(s.total_sessions), 0), 0)) * 0.2 +
                        (100.0 - COALESCE(SUM(s.abandoned_sessions) * 100.0 / NULLIF(SUM(s.total_sessions), 0), 0)) * 0.2
                    ), 1
                )                                                                    AS xla_score
            FROM viva_reports_cs_session_metrics s
            JOIN dim_agent_journey_persona m ON m.agent_id = s.agent_id
            GROUP BY m.persona_type, m.journey_name
            ORDER BY m.persona_type, m.journey_name
        """).fetchall()
        return [dict(r) for r in rows]

    def fetch_agent_contribution_by_persona_journey(self) -> list[dict]:
        """Per-agent breakdown: which personas/journeys each agent serves and its session outcomes."""
        rows = self._conn.execute("""
            SELECT
                COALESCE(a.agent_name, m.agent_name, s.agent_id)  AS agent_name,
                m.persona_type,
                m.journey_name,
                SUM(s.total_sessions)                              AS total_sessions,
                ROUND(SUM(s.resolved_sessions)  * 100.0 / NULLIF(SUM(s.total_sessions), 0), 1) AS completion_rate_pct,
                ROUND(SUM(s.escalated_sessions) * 100.0 / NULLIF(SUM(s.total_sessions), 0), 1) AS escalation_rate_pct,
                ROUND(SUM(s.abandoned_sessions) * 100.0 / NULLIF(SUM(s.total_sessions), 0), 1) AS abandonment_rate_pct
            FROM viva_reports_cs_session_metrics s
            JOIN dim_agent_journey_persona m ON m.agent_id = s.agent_id
            LEFT JOIN viva_reports_cs_copilot_agents a ON a.agent_id = s.agent_id
            GROUP BY s.agent_id, m.persona_type, m.journey_name
            ORDER BY total_sessions DESC
        """).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_usage_users(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                self._upsert_dim_user(r.get('username'), r.get('display_name'))
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_usage_users VALUES (?,?,?,?)""",
                    (
                        r.get('username'), r.get('agents_used'),
                        r.get('agent_responses_received'), r.get('last_activity_date'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_m365_usage_users(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT m.*, u.display_name
            FROM m365_usage_users m
            LEFT JOIN dim_user u ON u.user_principal_name = m.username
            ORDER BY m.agent_responses_received DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_tokenomics_entitlement_per_agent(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO tokenomics_entitlement_per_agent VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        _entitlement_per_agent_row_id(r),
                        r.get('agent_name'), r.get('agent_id'), r.get('product'),
                        r.get('ai_feature'), r.get('billed_credit'), r.get('non_billed_credit'),
                        r.get('channel'), r.get('knowledge_sources'), r.get('tool_used'),
                        r.get('llm_model'), r.get('scenario_name'),
                        r.get('environment_id'), r.get('environment_name'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_tokenomics_entitlement_per_agent(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM tokenomics_entitlement_per_agent ORDER BY billed_credit DESC, agent_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_tokenomics_entitlement_per_user(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO tokenomics_entitlement_per_user VALUES
                    (?,?,?,?,?,?,?)""",
                    (
                        r.get('user_id'), r.get('agent_id'), r.get('user_email'),
                        r.get('agent_name'), r.get('billable_credit_used'),
                        r.get('credits_used'), r.get('m365_copilot_licensed'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_tokenomics_entitlement_per_user(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM tokenomics_entitlement_per_user ORDER BY credits_used DESC"
        ).fetchall()
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
                self._upsert_dim_user(r.get("user_principal_name"), r.get("display_name"))
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_o365_active_users VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r.get("user_principal_name"), r.get("is_deleted", 0),
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
            """
            SELECT m.*, u.display_name
            FROM m365_o365_active_users m
            LEFT JOIN dim_user u ON u.user_principal_name = m.user_principal_name
            ORDER BY m.user_principal_name
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def _upsert_app_activity_row(self, upn, app_name, source, is_active, report_period, report_refresh_date) -> int:
        cur = self._conn.execute(
            """INSERT OR REPLACE INTO fact_user_app_activity
               (user_principal_name, app_name, source, is_active, report_period, report_refresh_date)
               VALUES (?,?,?,?,?,?)""",
            (upn, app_name, source, is_active, report_period, report_refresh_date),
        )
        return cur.rowcount

    def upsert_m365_app_users(self, rows: list[dict]) -> int:
        """outlook/word/excel/ppt/onenote/teams _active flags now live in
        fact_user_app_activity (overlap with m365_usage_proplus_detail);
        m365_app_users keeps only its own sharepoint/onedrive flags."""
        written = 0
        with self._conn:
            for r in rows:
                upn = r.get("user_principal_name")
                for app, col in _APP_USERS_COLUMNS.items():
                    written += self._upsert_app_activity_row(
                        upn, app, "m365_app_users", r.get(col),
                        r.get("report_period"), r.get("report_refresh_date"),
                    )
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_app_users VALUES
                    (?,?,?,?,?,?,?)""",
                    (upn, r.get("last_activation_date"),
                     r.get("last_activity_date"), r.get("report_refresh_date"), r.get("report_period"),
                     r.get("sharepoint_active"), r.get("onedrive_active")),
                )
                written += cur.rowcount
        return written

    def fetch_m365_app_users(self) -> list[dict]:
        app_cols = ", ".join(
            f"MAX(CASE WHEN f.app_name='{app}' THEN f.is_active END) AS {col}"
            for app, col in _APP_USERS_COLUMNS.items()
        )
        rows = self._conn.execute(
            f"""
            SELECT m.user_principal_name, m.last_activation_date, m.last_activity_date,
                   m.report_refresh_date, m.report_period, m.sharepoint_active, m.onedrive_active,
                   {app_cols}
            FROM m365_app_users m
            LEFT JOIN fact_user_app_activity f
                ON f.user_principal_name = m.user_principal_name AND f.source = 'm365_app_users'
            GROUP BY m.user_principal_name
            ORDER BY m.user_principal_name
            """
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

    # ------------------------------------------------------------------
    # M365 Admin Center — Office 365 / M365 Apps usage CSV imports
    # ------------------------------------------------------------------

    def upsert_m365_usage_activations_users(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_usage_activations_users VALUES
                    (?,?,?,?,?,?,?,?,?,?,?)""",
                    (r.get('user_principal_name'), r.get('product_type'),
                     r.get('report_refresh_date'), r.get('display_name'),
                     r.get('last_activated_date'), r.get('windows'), r.get('mac'),
                     r.get('windows_10_mobile'), r.get('ios'), r.get('android'),
                     r.get('shared_computer')),
                )
                written += cur.rowcount
        return written

    def fetch_m365_usage_activations_users(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_usage_activations_users ORDER BY user_principal_name, product_type"
        ).fetchall()
        return [dict(r) for r in rows]

    def _upsert_service_usage_row(
        self, metric_date, report_period, service_name, metric_source,
        active_count, inactive_count, report_refresh_date,
    ) -> int:
        cur = self._conn.execute(
            """INSERT OR REPLACE INTO fact_service_usage
               (metric_date, report_period, service_name, metric_source,
                active_count, inactive_count, report_refresh_date)
               VALUES (?,?,?,?,?,?,?)""",
            (metric_date, report_period, service_name, metric_source,
             active_count, inactive_count, report_refresh_date),
        )
        return cur.rowcount

    def upsert_m365_usage_active_users_services(self, rows: list[dict]) -> int:
        """m365_usage_active_users_services is now a compatibility view
        pivoting fact_service_usage back to its original wide shape."""
        written = 0
        with self._conn:
            for r in rows:
                for svc in _SERVICE_NAMES + ("office365",):
                    written += self._upsert_service_usage_row(
                        r.get('report_refresh_date'), r.get('report_period'), svc, 'services',
                        r.get(f'{svc}_active'), r.get(f'{svc}_inactive'), r.get('report_refresh_date'),
                    )
        return written

    def fetch_m365_usage_active_users_services(self) -> list[dict]:
        case_cols = ", ".join(
            f"MAX(CASE WHEN service_name='{s}' THEN active_count END) AS {s}_active, "
            f"MAX(CASE WHEN service_name='{s}' THEN inactive_count END) AS {s}_inactive"
            for s in _SERVICE_NAMES + ("office365",)
        )
        rows = self._conn.execute(
            f"""
            SELECT metric_date AS report_refresh_date, report_period, {case_cols}
            FROM fact_service_usage
            WHERE metric_source = 'services'
            GROUP BY metric_date, report_period
            ORDER BY metric_date DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_usage_active_users_activity(self, rows: list[dict]) -> int:
        """m365_usage_active_users_activity is now a compatibility view
        pivoting fact_service_usage back to its original wide shape."""
        written = 0
        with self._conn:
            for r in rows:
                for svc in _SERVICE_NAMES:
                    written += self._upsert_service_usage_row(
                        r.get('report_date'), r.get('report_period'), svc, 'activity',
                        r.get(svc), None, r.get('report_refresh_date'),
                    )
        return written

    def fetch_m365_usage_active_users_activity(self) -> list[dict]:
        case_cols = ", ".join(
            f"MAX(CASE WHEN service_name='{s}' THEN active_count END) AS {s}" for s in _SERVICE_NAMES
        )
        rows = self._conn.execute(
            f"""
            SELECT metric_date AS report_date, report_period,
                   MAX(report_refresh_date) AS report_refresh_date, {case_cols}
            FROM fact_service_usage
            WHERE metric_source = 'activity'
            GROUP BY metric_date, report_period
            ORDER BY metric_date DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_usage_active_user_counts(self, rows: list[dict]) -> int:
        """m365_usage_active_user_counts is now a compatibility view
        pivoting fact_service_usage back to its original wide shape."""
        written = 0
        with self._conn:
            for r in rows:
                for svc in _SERVICE_NAMES + ("office365",):
                    written += self._upsert_service_usage_row(
                        r.get('report_date'), r.get('report_period'), svc, 'counts',
                        r.get(svc), None, r.get('report_refresh_date'),
                    )
        return written

    def fetch_m365_usage_active_user_counts(self) -> list[dict]:
        case_cols = ", ".join(
            f"MAX(CASE WHEN service_name='{s}' THEN active_count END) AS {s}"
            for s in _SERVICE_NAMES + ("office365",)
        )
        rows = self._conn.execute(
            f"""
            SELECT metric_date AS report_date, report_period,
                   MAX(report_refresh_date) AS report_refresh_date, {case_cols}
            FROM fact_service_usage
            WHERE metric_source = 'counts'
            GROUP BY metric_date, report_period
            ORDER BY metric_date DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_usage_active_users_detail(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                self._upsert_dim_user(r.get('user_principal_name'), r.get('display_name'))
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_usage_active_users_detail VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r.get('user_principal_name'), r.get('report_refresh_date'),
                     r.get('is_deleted'), r.get('deleted_date'),
                     r.get('has_exchange'), r.get('has_onedrive'), r.get('has_sharepoint'),
                     r.get('has_skype'), r.get('has_yammer'), r.get('has_teams'),
                     r.get('exchange_last_activity'), r.get('onedrive_last_activity'),
                     r.get('sharepoint_last_activity'), r.get('skype_last_activity'),
                     r.get('yammer_last_activity'), r.get('teams_last_activity'),
                     r.get('exchange_license_date'), r.get('onedrive_license_date'),
                     r.get('sharepoint_license_date'), r.get('skype_license_date'),
                     r.get('yammer_license_date'), r.get('teams_license_date'),
                     r.get('assigned_products')),
                )
                written += cur.rowcount
        return written

    def fetch_m365_usage_active_users_detail(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT m.*, u.display_name
            FROM m365_usage_active_users_detail m
            LEFT JOIN dim_user u ON u.user_principal_name = m.user_principal_name
            ORDER BY m.user_principal_name
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_usage_proplus_platforms(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_usage_proplus_platforms VALUES
                    (?,?,?,?,?,?,?)""",
                    (r.get('report_date'), r.get('report_period'),
                     r.get('report_refresh_date'), r.get('windows'),
                     r.get('mac'), r.get('mobile'), r.get('web')),
                )
                written += cur.rowcount
        return written

    def fetch_m365_usage_proplus_platforms(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_usage_proplus_platforms ORDER BY report_date DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_usage_proplus_counts(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_usage_proplus_counts VALUES
                    (?,?,?,?,?,?,?,?,?)""",
                    (r.get('report_date'), r.get('report_period'),
                     r.get('report_refresh_date'), r.get('outlook'),
                     r.get('word'), r.get('excel'), r.get('powerpoint'),
                     r.get('onenote'), r.get('teams')),
                )
                written += cur.rowcount
        return written

    def fetch_m365_usage_proplus_counts(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_usage_proplus_counts ORDER BY report_date DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_usage_proplus_detail(self, rows: list[dict]) -> int:
        """outlook/word/excel/powerpoint/onenote/teams flags now live in
        fact_user_app_activity (overlap with m365_app_users);
        m365_usage_proplus_detail keeps only its own platform flags."""
        written = 0
        with self._conn:
            for r in rows:
                upn = r.get('user_principal_name')
                for app, col in _PROPLUS_APP_COLUMNS.items():
                    written += self._upsert_app_activity_row(
                        upn, app, "m365_usage_proplus_detail", r.get(col),
                        r.get('report_period'), r.get('report_refresh_date'),
                    )
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_usage_proplus_detail VALUES
                    (?,?,?,?,?,?,?,?,?)""",
                    (upn, r.get('report_refresh_date'),
                     r.get('last_activation_date'), r.get('last_activity_date'),
                     r.get('report_period'), r.get('windows'), r.get('mac'),
                     r.get('mobile'), r.get('web')),
                )
                written += cur.rowcount
        return written

    def fetch_m365_usage_proplus_detail(self) -> list[dict]:
        app_cols = ", ".join(
            f"MAX(CASE WHEN f.app_name='{app}' THEN f.is_active END) AS {col}"
            for app, col in _PROPLUS_APP_COLUMNS.items()
        )
        rows = self._conn.execute(
            f"""
            SELECT m.user_principal_name, m.report_refresh_date, m.last_activation_date,
                   m.last_activity_date, m.report_period, m.windows, m.mac, m.mobile, m.web,
                   {app_cols}
            FROM m365_usage_proplus_detail m
            LEFT JOIN fact_user_app_activity f
                ON f.user_principal_name = m.user_principal_name AND f.source = 'm365_usage_proplus_detail'
            GROUP BY m.user_principal_name
            ORDER BY m.user_principal_name
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_billing_licences(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO billing_licences VALUES (?,?,?,?,?)""",
                    (r.get('product_title'), r.get('total_licenses'),
                     r.get('expired_licenses'), r.get('assigned_licenses'),
                     r.get('status_message')),
                )
                written += cur.rowcount
        return written

    def fetch_billing_licences(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM billing_licences ORDER BY product_title"
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
