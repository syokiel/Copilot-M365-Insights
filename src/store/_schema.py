"""Base DDL and shared column/partition constants for the SQLite store."""

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
-- further down + _POST), not a physical table.

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

-- m365_copilot_usage is a VIEW (see _POST) that recombines two independently
-- refreshed snapshots of the same Copilot usage report: the Graph API pull
-- and the M365 Admin CSV export. Keeping them in separate tables lets each
-- source replace its own snapshot without wiping the other's columns.

CREATE TABLE IF NOT EXISTS m365_copilot_usage_graph (
    user_principal_name TEXT PRIMARY KEY,
    -- display_name lives in dim_user; the m365_copilot_usage view joins it in via fetch_copilot_usage()
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

-- M365ADMIN_USAGE_COPILOT export (FastCopilotActivityUserDetail*.csv)
CREATE TABLE IF NOT EXISTS m365_copilot_usage_csv (
    user_principal_name                TEXT PRIMARY KEY,
    last_activity_date                 TEXT,
    report_refresh_date                TEXT,
    report_period                      TEXT,
    prompts_all_apps                   INTEGER,
    prompts_copilot_chat_work          INTEGER,
    prompts_copilot_chat_web           INTEGER,
    active_usage_days_all_apps         INTEGER,
    last_activity_copilot_chat_work    TEXT,
    last_activity_copilot_chat_web     TEXT,
    last_activity_teams_copilot        TEXT,
    last_activity_word_copilot         TEXT,
    last_activity_excel_copilot        TEXT,
    last_activity_powerpoint_copilot   TEXT,
    last_activity_outlook_copilot      TEXT,
    last_activity_onenote_copilot      TEXT,
    last_activity_loop_copilot         TEXT,
    last_activity_m365_copilot_app     TEXT,
    last_activity_edge                 TEXT
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
    env_trial            INTEGER,
    -- ── schema_v3: period-keyed snapshots + CSV-sourced metrics ──
    -- Metrics are NULL when their source wasn't loaded in that period's run.
    period               TEXT,   -- data period (YYYY-MM) the snapshot describes — one row per period
    period_end           TEXT,   -- latest report date among the exports loaded for this period
    sources_loaded       TEXT,   -- tables loaded in the run that produced this snapshot
    chat_users           INTEGER,
    chat_active_users    INTEGER,
    chat_prompts         INTEGER,
    connector_users      INTEGER,
    connector_responses  INTEGER,
    m365_agent_users     INTEGER,
    m365_active_agents   INTEGER,
    m365_agent_responses INTEGER,
    viva_enabled_users   INTEGER,
    viva_active_users    INTEGER,
    viva_total_actions   INTEGER,
    cs_sessions          INTEGER,
    cs_resolution_rate   REAL,
    cs_escalation_rate   REAL,
    cs_abandon_rate      REAL,
    cs_csat_avg          REAL,
    cs_peak_wau          INTEGER,
    cowork_users         INTEGER,
    cowork_tasks         INTEGER,
    credits_entitled     REAL,
    credits_prepaid      REAL,
    credits_payg         REAL,
    credits_pct_used     REAL,
    capacity_total       REAL,
    capacity_avg_daily   REAL,
    consumption_credits  REAL
);

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
-- is also created in _POST so example SQL in the LLM prompt docs
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
    agent_id                TEXT PRIMARY KEY,  -- M365 Admin usage-report ID; NOT the Copilot Studio bot GUID
    agent_name              TEXT,
    creator_type            TEXT,
    active_users_licensed   INTEGER,
    active_users_unlicensed INTEGER,
    responses_sent          INTEGER,
    last_activity_date      TEXT,
    resolved_agent_id       TEXT                -- Copilot Studio bot GUID (matches dim_agent.agent_id /
                                                 -- tokenomics_entitlement_per_agent.agent_id); populated at
                                                 -- import time when agent_name resolves unambiguously via
                                                 -- m365_admin_agent_inventory.bot_id or usage_agent_id_overrides
);

-- ── Usage Agent ID Overrides — manual crosswalk for ambiguous agent names ──
-- m365_usage_agents.agent_id uses a different ID scheme than the Copilot
-- Studio bot GUID used by dim_agent/tokenomics, so it can't be joined
-- directly. Auto-resolution (see SqliteStore._resolve_usage_agent_ids) skips
-- any agent_name that maps to more than one bot_id in
-- m365_admin_agent_inventory (common when the same agent name is cloned
-- across dev/test/prod environments). Add a row here to force the mapping —
-- see imports/usage_agent_id_overrides.csv.
CREATE TABLE IF NOT EXISTS usage_agent_id_overrides (
    agent_name TEXT PRIMARY KEY,
    bot_id     TEXT NOT NULL
);

-- ── M365 Usage — Per-User Agent Activity ─────────────────────────────────

CREATE TABLE IF NOT EXISTS m365_usage_agent_users (
    agent_id            TEXT NOT NULL,
    user_principal_name TEXT NOT NULL,
    agent_name          TEXT,
    creator_type        TEXT,
    responses_sent      INTEGER,
    last_activity_date  TEXT,
    PRIMARY KEY (agent_id, user_principal_name)
);

-- ── Experience Model — Agent → Journey → Persona dimension ─────────────

CREATE TABLE IF NOT EXISTS dim_agent_journey_persona (
    agent_id     TEXT    NOT NULL,
    journey_name TEXT    NOT NULL,
    persona_type TEXT    NOT NULL,
    agent_name   TEXT,
    PRIMARY KEY (agent_id, journey_name, persona_type)
);

-- ── M365 Usage — Per-User Agent Activity Rollup ──────────────────────────

CREATE TABLE IF NOT EXISTS m365_usage_users (
    user_principal_name      TEXT PRIMARY KEY,
    -- display_name lives in dim_user; fetch_m365_usage_users() joins it back in
    agents_used              INTEGER,
    agent_responses_received INTEGER,
    last_activity_date       TEXT
);

-- ── M365 Admin Center — Cowork Usage (CSV import) ────────────────────────

CREATE TABLE IF NOT EXISTS m365_cowork_usage (
    user_principal_name  TEXT PRIMARY KEY,
    -- display_name moved to dim_user; fetch_m365_cowork_usage() joins it back in
    total_tasks           INTEGER,
    scheduled_tasks       INTEGER,
    user_initiated_tasks  INTEGER,
    active_days           INTEGER,
    last_activity_date    TEXT
);

-- ── M365 Admin Center — Copilot Chat Usage Details (CSV import) ──────────

CREATE TABLE IF NOT EXISTS m365_copilot_chat_usage (
    user_principal_name            TEXT PRIMARY KEY,
    -- display_name lives in dim_user; fetch_m365_copilot_chat_usage() joins it back in
    user_guid                      TEXT,
    last_activity_date             TEXT,
    report_period                  TEXT,
    report_refresh_date            TEXT,
    prompts_submitted              INTEGER,
    active_usage_days              INTEGER,
    last_activity_m365_copilot_app TEXT,
    last_activity_word             TEXT,
    last_activity_excel            TEXT,
    last_activity_powerpoint       TEXT,
    last_activity_onenote          TEXT,
    last_activity_edge             TEXT,
    last_activity_teams            TEXT,
    last_activity_outlook          TEXT,
    last_activity_copilot_cloud    TEXT
);

-- ── M365 Admin Center — Copilot Connectors Usage (CSV import) ────────────

CREATE TABLE IF NOT EXISTS m365_connectors_usage (
    connection_id       TEXT PRIMARY KEY,
    active_users        INTEGER,
    responses_provided  INTEGER,
    last_activity_date  TEXT
);

CREATE TABLE IF NOT EXISTS m365_connectors_users (
    user_principal_name TEXT PRIMARY KEY,
    -- display_name lives in dim_user; fetch_m365_connectors_users() joins it back in
    connections_used    INTEGER,
    responses_received  INTEGER,
    last_activity_date  TEXT
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

-- ── Viva Insights — Consumption Dashboard (per-person credit use by service) ─
-- Enhances the Tokenomics_* sheets with a service-level (Cowork, Copilot
-- Studio, etc.) breakdown that the PP Admin entitlement/capacity reports
-- above don't carry.

CREATE TABLE IF NOT EXISTS viva_consumption_people (
    people_historical_id TEXT PRIMARY KEY,
    organization          TEXT,
    function_type         TEXT,
    is_copilot_licensed   INTEGER
);

CREATE TABLE IF NOT EXISTS viva_consumption_person_service_credits (
    person_id             TEXT NOT NULL,
    service_id            TEXT NOT NULL,
    service_name          TEXT,
    spending_policy_id    TEXT,
    metric_date           TEXT NOT NULL,
    session_count         INTEGER,
    spending_policy_limit REAL,
    total_credits_used    REAL,
    user_limit            REAL,
    people_historical_id  TEXT,
    PRIMARY KEY (person_id, service_id, metric_date)
);

CREATE TABLE IF NOT EXISTS viva_consumption_spending_policy (
    spending_policy_id TEXT PRIMARY KEY,
    name                TEXT,
    plan_limit          REAL,
    user_limit          REAL,
    included_services   TEXT
);

-- ── M365 Admin Center — Office 365 / M365 Apps Usage Reports (CSV import) ─

CREATE TABLE IF NOT EXISTS m365_usage_activations_users (
    user_principal_name TEXT NOT NULL,
    product_type        TEXT NOT NULL,
    report_refresh_date TEXT,
    -- display_name lives in dim_user; fetch_m365_usage_activations_users() joins it back in
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
-- original wide shape (see Cluster C DDL further down + _POST).

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

-- ── Schema migration bookkeeping ──────────────────────────────────────────
-- One row per applied migration (see _base.StoreBase._migrate).

CREATE TABLE IF NOT EXISTS _schema_migrations (
    id          TEXT PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

-- ── Cluster A: unified agent identity (Dataverse + Viva Copilot agents) ───
-- pva_agents.agent_id and viva_reports_cs_copilot_agents.agent_id are the
-- same Copilot Studio / Dataverse agent GUID space, so both sources are
-- COALESCE-merged into one row here. pva_agents and
-- viva_reports_cs_copilot_agents are compatibility views over this table.
-- m365_admin_agent_inventory / m365_usage_agents are a DIFFERENT ID space
-- (M365 Admin "Title ID") — dim_agent_xref maps them onto bot GUIDs.

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
-- One display_name per user, fed by every source that observes one. UPN-keyed
-- tables don't store display_name themselves; their fetch_* methods LEFT JOIN
-- it back in. All UPNs are stored lower-cased (see _base._upn).

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

-- ── Import bookkeeping ─────────────────────────────────────────────────────
-- One row per dataset load. mode='snapshot' means the table was cleared and
-- reloaded (point-in-time exports such as 30-day usage reports); mode='merge'
-- means rows were upserted by key into history (date-keyed metrics).

CREATE TABLE IF NOT EXISTS import_log (
    import_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT,
    table_name   TEXT NOT NULL,
    mode         TEXT NOT NULL,   -- 'snapshot' | 'merge'
    row_count    INTEGER NOT NULL,
    imported_at  TEXT NOT NULL
);

-- ── Agent ID crosswalk ─────────────────────────────────────────────────────
-- Every source names agents in its own ID space: Copilot Studio bot GUIDs
-- (dim_agent via Power Platform / Dataverse), Viva Copilot Studio report
-- AgentIds (a separate GUID space), and M365 Admin title IDs (T_/P_/U_/SP..).
-- Rebuilt by rebuild_agent_xref() after each sync; bot_id is the shared key.
-- match_method: override | exact_id | name_unique | unresolved

CREATE TABLE IF NOT EXISTS dim_agent_xref (
    source          TEXT NOT NULL,   -- 'm365_usage' | 'viva_cs'
    source_agent_id TEXT NOT NULL,
    agent_name      TEXT,
    title_id        TEXT,            -- m365_admin_agent_inventory.title_id
    bot_id          TEXT,            -- Copilot Studio bot GUID
    match_method    TEXT NOT NULL,
    PRIMARY KEY (source, source_agent_id)
);

-- ── Copilot-enabled people (Viva Adoption / Impact) ────────────────────────
-- fact_copilot_actions_per_person only keeps person-weeks with Copilot
-- activity; zero-activity rows are pruned on import. This table keeps the
-- per-person date span each report saw them in, so "enabled users"
-- denominators survive the pruning.

CREATE TABLE IF NOT EXISTS dim_copilot_person (
    person_id            TEXT PRIMARY KEY,
    organization         TEXT,
    adoption_first_date  TEXT,
    adoption_last_date   TEXT,
    impact_first_date    TEXT,
    impact_last_date     TEXT
);
"""

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


# Action columns that don't make a person-week "active": a row whose other
# action columns are all zero/NULL is pruned from fact_copilot_actions_per_person
# (see VivaMixin._prune_zero_copilot_actions).
_ZERO_PRUNE_EXEMPT_COLUMNS = ("organization", "total_copilot_enabled_days")
_ZERO_PRUNE_COLUMNS = tuple(c for c in _COPILOT_ACTION_COLUMNS if c not in _ZERO_PRUNE_EXEMPT_COLUMNS)

_COPILOT_USAGE_GRAPH_COUNT_COLUMNS = (
    "teams_chats", "teams_meetings", "word", "excel", "powerpoint",
    "outlook", "onenote", "loop", "copilot_chat",
)
_COPILOT_USAGE_CSV_COLUMNS = (
    "prompts_all_apps", "prompts_copilot_chat_work", "prompts_copilot_chat_web",
    "active_usage_days_all_apps",
    "last_activity_copilot_chat_work", "last_activity_copilot_chat_web",
    "last_activity_teams_copilot", "last_activity_word_copilot", "last_activity_excel_copilot",
    "last_activity_powerpoint_copilot", "last_activity_outlook_copilot",
    "last_activity_onenote_copilot", "last_activity_loop_copilot",
    "last_activity_m365_copilot_app", "last_activity_edge",
)


def _impact_action_select(col: str) -> str:
    """Impact view column for an action metric. Person-weeks pruned from
    fact_copilot_actions_per_person had zero activity, so their action
    metrics read back as 0; enabled-days wasn't kept, so it reads NULL."""
    if col == "organization":
        return "COALESCE(a.organization, cp.organization) AS organization"
    if col in _ZERO_PRUNE_EXEMPT_COLUMNS:
        return f"a.{col}"
    return f"CASE WHEN a.person_id IS NULL THEN 0 ELSE a.{col} END AS {col}"


# Compatibility views + indexes. Executed after _migrate() on every startup
# (views are CREATE IF NOT EXISTS; migrations that change a view's shape drop
# it first so it is recreated here).
_VIEW_NAMES = (
    "pva_agents", "viva_reports_cs_copilot_agents",
    "viva_reports_copilot_adoption", "viva_reports_copilot_impact",
    "m365_usage_active_users_services", "m365_usage_active_users_activity",
    "m365_usage_active_user_counts", "m365_copilot_usage",
)

_POST = """
CREATE INDEX IF NOT EXISTS idx_model_calls_conv  ON gen_ai_model_calls(conversation_id);
CREATE INDEX IF NOT EXISTS idx_model_calls_agent ON gen_ai_model_calls(gen_ai_agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_sol         ON pva_agent_solutions(solution_id);
CREATE INDEX IF NOT EXISTS idx_events_conv  ON conversation_events(conversation_id);
CREATE INDEX IF NOT EXISTS idx_events_run   ON conversation_events(run_id);
CREATE INDEX IF NOT EXISTS idx_calls_conv   ON connector_calls(conversation_id);
CREATE INDEX IF NOT EXISTS idx_calls_run    ON connector_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_az_dep_conv  ON az_dependency_failures(conversation_id);
CREATE INDEX IF NOT EXISTS idx_az_exc_conv  ON az_exceptions(conversation_id);
CREATE INDEX IF NOT EXISTS idx_pp_sessions_bot ON pp_bot_sessions(bot_id);
CREATE INDEX IF NOT EXISTS idx_m365_admin_inv_bot    ON m365_admin_agent_inventory(bot_id);
CREATE INDEX IF NOT EXISTS idx_m365_usage_users_user ON m365_usage_agent_users(user_principal_name);
CREATE INDEX IF NOT EXISTS idx_dim_ajp_journey ON dim_agent_journey_persona(journey_name);
CREATE INDEX IF NOT EXISTS idx_dim_ajp_persona ON dim_agent_journey_persona(persona_type);
CREATE INDEX IF NOT EXISTS idx_tokenomics_capacity_env    ON tokenomics_capacity_consumption(environment_id);
CREATE INDEX IF NOT EXISTS idx_tokenomics_capacity_date   ON tokenomics_capacity_consumption(consumption_date);
CREATE INDEX IF NOT EXISTS idx_tokenomics_entitlement_env ON tokenomics_entitlement_consumption(environment_id);
CREATE INDEX IF NOT EXISTS idx_tokenomics_per_agent_agent ON tokenomics_entitlement_per_agent(agent_id);
CREATE INDEX IF NOT EXISTS idx_tokenomics_per_agent_env   ON tokenomics_entitlement_per_agent(environment_id);
CREATE INDEX IF NOT EXISTS idx_tokenomics_per_user_user   ON tokenomics_entitlement_per_user(user_id);
CREATE INDEX IF NOT EXISTS idx_viva_consumption_credits_service ON viva_consumption_person_service_credits(service_name);
CREATE INDEX IF NOT EXISTS idx_viva_consumption_credits_people  ON viva_consumption_person_service_credits(people_historical_id);
CREATE INDEX IF NOT EXISTS idx_copilot_actions_date   ON fact_copilot_actions_per_person(metric_date);

CREATE VIEW IF NOT EXISTS pva_agents AS
SELECT agent_id, display_name, schema_name, environment_id, created_at,
       modified_at, published_at, created_by, owner_id, created_in, ai_model, properties
FROM dim_agent;

CREATE VIEW IF NOT EXISTS viva_reports_cs_copilot_agents AS
SELECT agent_id, display_name AS agent_name, description, surface, mode,
       categories, agent_type, is_included, excluded_reason
FROM dim_agent WHERE in_viva_report = 1;

CREATE VIEW IF NOT EXISTS viva_reports_copilot_adoption AS
SELECT person_id, metric_date, """ + ", ".join(_ADOPTION_ACTION_COLUMNS) + """
FROM fact_copilot_actions_per_person
WHERE in_adoption_report = 1;

CREATE VIEW IF NOT EXISTS viva_reports_copilot_impact AS
SELECT p.person_id, p.metric_date, """ + ", ".join(_impact_action_select(c) for c in _IMPACT_ACTION_COLUMNS) + """,
       """ + ", ".join(f"p.{c}" for c in _COPILOT_WORK_PATTERN_COLUMNS) + """
FROM fact_copilot_work_patterns p
LEFT JOIN fact_copilot_actions_per_person a
    ON a.person_id = p.person_id AND a.metric_date = p.metric_date
LEFT JOIN dim_copilot_person cp ON cp.person_id = p.person_id;

CREATE VIEW IF NOT EXISTS m365_usage_active_users_services AS
SELECT metric_date AS report_refresh_date, report_period, """ + ", ".join(
    f"MAX(CASE WHEN service_name='{s}' THEN active_count END) AS {s}_active, "
    f"MAX(CASE WHEN service_name='{s}' THEN inactive_count END) AS {s}_inactive"
    for s in _SERVICE_NAMES + ("office365",)
) + """
FROM fact_service_usage WHERE metric_source = 'services'
GROUP BY metric_date, report_period;

CREATE VIEW IF NOT EXISTS m365_usage_active_users_activity AS
SELECT metric_date AS report_date, report_period,
       MAX(report_refresh_date) AS report_refresh_date, """ + ", ".join(
    f"MAX(CASE WHEN service_name='{s}' THEN active_count END) AS {s}" for s in _SERVICE_NAMES
) + """
FROM fact_service_usage WHERE metric_source = 'activity'
GROUP BY metric_date, report_period;

CREATE VIEW IF NOT EXISTS m365_usage_active_user_counts AS
SELECT metric_date AS report_date, report_period,
       MAX(report_refresh_date) AS report_refresh_date, """ + ", ".join(
    f"MAX(CASE WHEN service_name='{s}' THEN active_count END) AS {s}"
    for s in _SERVICE_NAMES + ("office365",)
) + """
FROM fact_service_usage WHERE metric_source = 'counts'
GROUP BY metric_date, report_period;

-- Graph wins for the columns both sources report (last activity / report
-- dates), matching the old single-table merge behaviour.
CREATE VIEW IF NOT EXISTS m365_copilot_usage AS
SELECT k.user_principal_name,
       COALESCE(g.last_activity_date, c.last_activity_date) AS last_activity_date,
       """ + ", ".join(f"g.{c}" for c in _COPILOT_USAGE_GRAPH_COUNT_COLUMNS) + """,
       COALESCE(g.report_refresh_date, c.report_refresh_date) AS report_refresh_date,
       COALESCE(g.report_period, c.report_period) AS report_period,
       """ + ", ".join(f"c.{c}" for c in _COPILOT_USAGE_CSV_COLUMNS) + """
FROM (
    SELECT user_principal_name FROM m365_copilot_usage_graph
    UNION
    SELECT user_principal_name FROM m365_copilot_usage_csv
) k
LEFT JOIN m365_copilot_usage_graph g ON g.user_principal_name = k.user_principal_name
LEFT JOIN m365_copilot_usage_csv c   ON c.user_principal_name = k.user_principal_name;
"""

# kpi_snapshots columns added in schema_v3 (name, SQL type).
_KPI_V3_COLUMNS = (
    ("period", "TEXT"),
    ("period_end", "TEXT"),
    ("sources_loaded", "TEXT"),
    ("chat_users", "INTEGER"),
    ("chat_active_users", "INTEGER"),
    ("chat_prompts", "INTEGER"),
    ("connector_users", "INTEGER"),
    ("connector_responses", "INTEGER"),
    ("m365_agent_users", "INTEGER"),
    ("m365_active_agents", "INTEGER"),
    ("m365_agent_responses", "INTEGER"),
    ("viva_enabled_users", "INTEGER"),
    ("viva_active_users", "INTEGER"),
    ("viva_total_actions", "INTEGER"),
    ("cs_sessions", "INTEGER"),
    ("cs_resolution_rate", "REAL"),
    ("cs_escalation_rate", "REAL"),
    ("cs_abandon_rate", "REAL"),
    ("cs_csat_avg", "REAL"),
    ("cs_peak_wau", "INTEGER"),
    ("cowork_users", "INTEGER"),
    ("cowork_tasks", "INTEGER"),
    ("credits_entitled", "REAL"),
    ("credits_prepaid", "REAL"),
    ("credits_payg", "REAL"),
    ("credits_pct_used", "REAL"),
    ("capacity_total", "REAL"),
    ("capacity_avg_daily", "REAL"),
    ("consumption_credits", "REAL"),
)
