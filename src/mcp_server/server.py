"""
MCP server — exposes agent telemetry data to Microsoft AI agents.

Transports:
  Local (Claude Code):  stdio   — launched by .mcp.json
  Deployed (Azure):     HTTP/SSE — launched by Dockerfile CMD, protected by Entra ID

Auth (deployed only):
  Validates Bearer tokens issued by Entra ID for MCP_APP_ID_URI.
  Microsoft agent platforms (Copilot Studio, AI Foundry, M365 Copilot) send
  these tokens automatically when they call the MCP endpoint.
"""

import json
import os
import sqlite3
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# ---------------------------------------------------------------------------
# Bootstrap: download db from blob storage when running in Azure
# ---------------------------------------------------------------------------

def _maybe_download_db() -> None:
    from config.settings import settings
    if not settings.azure_storage_account:
        return
    if Path(settings.db_path).exists():
        return
    try:
        from src.store.blob_store import download_db
        download_db(
            settings.db_path,
            settings.azure_storage_account,
            settings.azure_storage_container,
            settings.azure_storage_db_blob,
        )
    except Exception as e:
        print(f"Warning: could not download db from blob storage: {e}", file=sys.stderr)


_maybe_download_db()

from config.settings import settings
from mcp.server import Server
from mcp.types import (
    CallToolResult,
    ListResourcesResult,
    ListToolsResult,
    ReadResourceResult,
    Resource,
    TextContent,
    Tool,
)

server = Server("agent-telemetry")

# ---------------------------------------------------------------------------
# Database helper
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS conversation_events (
    row_id TEXT PRIMARY KEY, run_id TEXT, timestamp TEXT, event_name TEXT,
    session_id TEXT, user_id TEXT, conversation_id TEXT, channel_id TEXT,
    design_mode INTEGER, topic_name TEXT, text TEXT, properties TEXT
);
CREATE TABLE IF NOT EXISTS connector_calls (
    row_id TEXT PRIMARY KEY, run_id TEXT, timestamp TEXT, connector_name TEXT,
    action_target TEXT, session_id TEXT, user_id TEXT, conversation_id TEXT,
    channel_id TEXT, design_mode INTEGER, success INTEGER, result_code TEXT,
    duration_ms REAL, properties TEXT
);
CREATE TABLE IF NOT EXISTS sync_runs (
    run_id TEXT PRIMARY KEY, started_at TEXT, events_new INTEGER, calls_new INTEGER
);
CREATE TABLE IF NOT EXISTS pva_bots (
    bot_id TEXT PRIMARY KEY, display_name TEXT, schema_name TEXT, environment_id TEXT,
    created_at TEXT, modified_at TEXT, published_at TEXT, properties TEXT
);
CREATE TABLE IF NOT EXISTS pva_environments (
    environment_id TEXT PRIMARY KEY, display_name TEXT, type TEXT, region TEXT,
    state TEXT, created_at TEXT, modified_at TEXT, sku TEXT, dataverse_url TEXT
);
CREATE TABLE IF NOT EXISTS pva_publishers (
    publisher_id TEXT PRIMARY KEY, display_name TEXT, unique_name TEXT,
    email TEXT, phone TEXT, custom_prefix TEXT, solution_count INTEGER
);
CREATE TABLE IF NOT EXISTS pva_dlp_policies (
    policy_id TEXT PRIMARY KEY, display_name TEXT, environment_type TEXT,
    created_by TEXT, created_at TEXT, modified_at TEXT, enforcement_mode TEXT,
    blocked_connectors TEXT, business_connectors TEXT, non_business_connectors TEXT
);
CREATE TABLE IF NOT EXISTS pva_bot_solutions (
    bot_id TEXT PRIMARY KEY, solution_id TEXT, solution_name TEXT,
    solution_unique TEXT, version TEXT, is_managed INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS az_dependency_failures (
    row_id TEXT PRIMARY KEY, operation_id TEXT, agent_id TEXT, agent_name TEXT,
    env_id TEXT, conversation_id TEXT, dependency_name TEXT, result_code TEXT,
    success INTEGER, duration_ms REAL, timestamp TEXT
);
CREATE TABLE IF NOT EXISTS az_exceptions (
    row_id TEXT PRIMARY KEY, operation_id TEXT, agent_id TEXT, conversation_id TEXT,
    exception_type TEXT, exception_message TEXT, timestamp TEXT
);
CREATE TABLE IF NOT EXISTS az_alerts (
    alert_id TEXT PRIMARY KEY, agent_id TEXT, alert_name TEXT,
    severity TEXT, fired_time TEXT, resource_id TEXT
);
"""

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_DDL)
    return conn


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


# ---------------------------------------------------------------------------
# Entra ID token validation
# ---------------------------------------------------------------------------

def _validate_token(request_headers: dict) -> None:
    """Raises ValueError if the API key is missing or invalid."""
    if not settings.mcp_api_key:
        return  # auth not configured — skip (local dev)

    # Check all headers AI Foundry and other platforms may use
    authorization = request_headers.get("authorization") or request_headers.get("Authorization")
    api_key = request_headers.get("api-key") or request_headers.get("x-api-key")

    if api_key:
        token = api_key
    elif authorization:
        token = authorization[7:] if authorization.startswith("Bearer ") else authorization
    else:
        raise ValueError("Missing Authorization header")

    if token != settings.mcp_api_key:
        raise ValueError("Invalid API key")


# ---------------------------------------------------------------------------
# Schema resource
# ---------------------------------------------------------------------------

_SCHEMA_DOC = """
# Agent Telemetry Database Schema

Copilot Studio agent telemetry from Azure Log Analytics / Application Insights.

## Tables

### conversation_events
Every event emitted by the agent — messages in, messages out, topic starts.
- timestamp: When the event occurred (UTC ISO)
- event_name: BotMessageReceived | BotMessageSend | TopicStart | ...
- session_id: Groups events in one browser/channel session
- user_id: Azure AD object ID of the user (source tenant)
- conversation_id: Groups a single conversation end-to-end
- channel_id: pva-studio | msteams | webchat | directline | ...
- design_mode: 1 = test traffic from Copilot Studio, 0 = production
- topic_name: Copilot Studio topic that handled this turn
- text: Message text (BotMessageReceived events only)

### connector_calls
Every time the agent invoked a Power Platform connector.
- timestamp, connector_name, action_target, conversation_id, session_id
- user_id, channel_id, design_mode
- success: 1 = succeeded, 0 = failed
- result_code: HTTP status returned by the connector
- duration_ms: Connector call latency in milliseconds

### sync_runs
One row per data sync run — when data was last refreshed.

### pva_bots
Copilot Studio / Power Virtual Agents bots registered in the Power Platform environment.
- bot_id: GUID of the bot
- display_name: Human-readable bot name (use this when reporting agent names)
- schema_name: Internal schema identifier
- environment_id: Power Platform environment GUID (join to pva_environments)
- created_at, modified_at, published_at: ISO timestamps

### pva_environments
Power Platform environments where agents are deployed.
- environment_id: GUID — joins to pva_bots.environment_id
- display_name: Human-readable environment name
- type / sku: e.g. Sandbox, Production, Default
- region: Azure region
- state: Ready / Disabled
- dataverse_url: Dataverse org URL for this environment

### pva_bot_solutions
Solution each bot/agent is packaged in (from Dataverse solutioncomponents).
- bot_id: joins to pva_bots.bot_id
- solution_name: Human-readable solution name
- solution_unique: Internal unique name (e.g. "WorkIQAgents")
- version: solution version string
- is_managed: 1 = managed/deployed, 0 = unmanaged/in development

### pva_publishers
Solution publishers registered in the Power Platform environment.
- publisher_id, display_name, unique_name, custom_prefix

### pva_dlp_policies
Data Loss Prevention policies governing which connectors agents can use.
- display_name: Policy name
- environment_type: AllEnvironments | OnlyEnvironments | ExceptEnvironments
- blocked_connectors: comma-separated blocked connector names
- business_connectors: connectors in the Business data group
- non_business_connectors: connectors in the Non-business group
NOTE: Requires Power Platform Admin role to sync — may be empty.

### az_dependency_failures
Failed connector/API calls captured by Azure Monitor Application Insights.
- operation_id: App Insights operation correlation ID
- agent_id, agent_name, env_id: from gen_ai.* properties
- conversation_id: join key back to conversation_events
- dependency_name: name of the failed dependency/connector
- result_code: HTTP or error code
- duration_ms: call duration
- timestamp: when the failure occurred

### az_exceptions
Exceptions logged by the agent runtime in Application Insights.
- operation_id: App Insights operation correlation ID
- agent_id: from gen_ai.agent.id property
- conversation_id: join key back to conversation_events
- exception_type: exception class name
- exception_message: exception detail message
- timestamp: when the exception was logged

### viva_person_insights
Per-user weekly Viva Insights activity breakdown (Graph Analytics API).
- user_id: Azure AD object ID — join to conversation_events.user_id
- week_start / week_end: ISO dates bounding the week
- focus_hours: uninterrupted focus blocks
- meeting_hours: scheduled meeting time
- email_hours: Outlook / email time
- chat_hours: Teams chat time
- after_hours: collaboration outside typical working hours
NOTE: requires Analytics.ReadAll app permission + Viva Insights license per user.
      Rows only appear for users who have had production conversations.

### viva_org_insights
Organisation-wide Viva Insights aggregate metrics (Management API — stubbed).
Populated once the Viva Insights Management API access is provisioned.

### az_alerts
Azure Monitor alerts that fired against agent resources.
- alert_id: Azure resource ID of the alert instance
- agent_id: from gen_ai.agent.id tag on the resource
- alert_name: alert rule name
- severity: Sev0–Sev4
- fired_time: when the alert fired
- resource_id: Azure resource that triggered the alert

## Key relationships
conversation_events.conversation_id = connector_calls.conversation_id
conversation_events.conversation_id = az_dependency_failures.conversation_id
conversation_events.conversation_id = az_exceptions.conversation_id
pva_bots.environment_id = pva_environments.environment_id
pva_bots.bot_id = pva_bot_solutions.bot_id
pva_bots.bot_id = az_dependency_failures.agent_id (approximate — depends on agent config)

## Cross-reference pattern
To find conversations with both OTel failures AND Azure Monitor signals:
  SELECT e.conversation_id, d.dependency_name, d.result_code, ex.exception_type
  FROM conversation_events e
  JOIN connector_calls c ON c.conversation_id = e.conversation_id AND c.success = 0
  LEFT JOIN az_dependency_failures d ON d.conversation_id = e.conversation_id
  LEFT JOIN az_exceptions ex ON ex.conversation_id = e.conversation_id
  WHERE d.row_id IS NOT NULL OR ex.row_id IS NOT NULL
  GROUP BY e.conversation_id

## Notes
- Filter design_mode = 0 for production traffic only
- user_id is an Azure AD object ID (Graph API lookup needed for email)
- There is NO agent_name column in conversation_events or connector_calls — use pva_bots for agent names
- az_* tables will be empty until agents are configured to write to Application Insights
"""


@server.list_resources()
async def list_resources() -> ListResourcesResult:
    return ListResourcesResult(resources=[
        Resource(
            uri="schema://tables",
            name="Database Schema",
            description="Schema documentation for all tables in agent_telemetry.db",
            mimeType="text/markdown",
        )
    ])


@server.read_resource()
async def read_resource(uri: str) -> ReadResourceResult:
    if str(uri) == "schema://tables":
        return ReadResourceResult(contents=[TextContent(type="text", text=_SCHEMA_DOC)])
    raise ValueError(f"Unknown resource: {uri}")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> ListToolsResult:
    return ListToolsResult(tools=[
        Tool(
            name="get_summary_stats",
            description="High-level statistics: total conversations, events, connector calls, date range, top connectors, production vs design-mode breakdown.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_conversations",
            description="List conversations with per-conversation stats. Optionally filter by channel_id or design_mode.",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {"type": "string", "description": "e.g. 'msteams', 'pva-studio', 'webchat'"},
                    "design_mode": {"type": "boolean", "description": "True = test only, False = production only"},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": [],
            },
        ),
        Tool(
            name="get_conversation_detail",
            description="Full event timeline for a single conversation: every message, topic, and connector call in order.",
            inputSchema={
                "type": "object",
                "properties": {
                    "conversation_id": {"type": "string"},
                },
                "required": ["conversation_id"],
            },
        ),
        Tool(
            name="get_connector_calls",
            description="List connector calls with timing and success info. Filter by connector name, action, success, or design_mode.",
            inputSchema={
                "type": "object",
                "properties": {
                    "connector_name": {"type": "string", "description": "e.g. 'Microsoft Teams'"},
                    "action_target": {"type": "string", "description": "e.g. 'shared_teams/GetAllTeams'"},
                    "success": {"type": "boolean"},
                    "design_mode": {"type": "boolean"},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": [],
            },
        ),
        Tool(
            name="get_user_prompts",
            description="List user prompts (messages sent to agents). Supports keyword search, conversation filter, and design_mode filter.",
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Keyword to search within prompt text (case-insensitive)"},
                    "conversation_id": {"type": "string", "description": "Return prompts from a single conversation"},
                    "design_mode": {"type": "boolean", "description": "True = test traffic only, False = production only"},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": [],
            },
        ),
        Tool(
            name="get_top_connectors",
            description="Connectors ranked by usage count with success/failure breakdown and average latency.",
            inputSchema={
                "type": "object",
                "properties": {
                    "design_mode": {"type": "boolean"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": [],
            },
        ),
        Tool(
            name="search_by_user",
            description="All conversations and connector calls for a specific Azure AD object ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": ["user_id"],
            },
        ),
        Tool(
            name="run_sql",
            description="Execute a read-only SELECT query for custom analysis not covered by other tools.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_agents",
            description="List all Copilot Studio agents with display name, environment, solution, and publish status.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_environments",
            description="List Power Platform environments with their agents and applicable DLP policies.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_viva_insights",
            description="Per-user Viva Insights weekly summary: focus, meeting, email, chat, and after-hours. Joined with conversation activity where possible.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id":     {"type": "string", "description": "Filter to a single Azure AD user ID"},
                    "week_start":  {"type": "string", "description": "ISO date e.g. 2026-05-19 — return data for this week only"},
                    "limit":       {"type": "integer", "default": 50},
                },
                "required": [],
            },
        ),
        Tool(
            name="get_agent_activity",
            description="Per-agent conversation breakdown: total, production, and test conversation counts with last activity timestamp. Joins telemetry to the agent registry via topic name prefix.",
            inputSchema={
                "type": "object",
                "properties": {
                    "design_mode": {"type": "boolean", "description": "True = test only, False = production only, omit for both"},
                },
                "required": [],
            },
        ),
        Tool(
            name="get_user_activity",
            description="Per-user conversation summary: conversation count, message count, channels used, agents interacted with, and last activity. Note: user_id is an Azure AD object ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "design_mode": {"type": "boolean", "description": "True = test only, False = production only, omit for both"},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": [],
            },
        ),
    ])


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> CallToolResult:
    try:
        result = _dispatch(name, arguments)
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(result, indent=2, default=str))])
    except Exception as e:
        return CallToolResult(content=[TextContent(type="text", text=f"Error: {e}")], isError=True)


def _dispatch(name: str, args: dict) -> object:
    conn = _db()
    try:
        if name == "get_summary_stats":     return _get_summary_stats(conn)
        if name == "get_conversations":     return _get_conversations(conn, args)
        if name == "get_conversation_detail": return _get_conversation_detail(conn, args["conversation_id"])
        if name == "get_user_prompts":      return _get_user_prompts(conn, args)
        if name == "get_connector_calls":   return _get_connector_calls(conn, args)
        if name == "get_top_connectors":    return _get_top_connectors(conn, args)
        if name == "search_by_user":        return _search_by_user(conn, args)
        if name == "run_sql":               return _run_sql(conn, args["query"])
        if name == "get_agents":            return _get_agents(conn)
        if name == "get_environments":      return _get_environments(conn)
        if name == "get_viva_insights":      return _get_viva_insights(conn, args)
        if name == "get_agent_activity":    return _get_agent_activity(conn, args)
        if name == "get_user_activity":     return _get_user_activity(conn, args)
        raise ValueError(f"Unknown tool: {name}")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _get_summary_stats(conn: sqlite3.Connection) -> dict:
    stats = {}
    stats["total_conversations"] = conn.execute("SELECT COUNT(DISTINCT conversation_id) FROM conversation_events").fetchone()[0]
    stats["production_conversations"] = conn.execute("SELECT COUNT(DISTINCT conversation_id) FROM conversation_events WHERE design_mode=0").fetchone()[0]
    stats["design_mode_conversations"] = conn.execute("SELECT COUNT(DISTINCT conversation_id) FROM conversation_events WHERE design_mode=1").fetchone()[0]
    stats["total_events"] = conn.execute("SELECT COUNT(*) FROM conversation_events").fetchone()[0]
    stats["total_connector_calls"] = conn.execute("SELECT COUNT(*) FROM connector_calls").fetchone()[0]
    stats["failed_connector_calls"] = conn.execute("SELECT COUNT(*) FROM connector_calls WHERE success=0").fetchone()[0]
    row = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM conversation_events").fetchone()
    stats["earliest_event"] = row[0]
    stats["latest_event"] = row[1]
    row = conn.execute("SELECT started_at FROM sync_runs ORDER BY started_at DESC LIMIT 1").fetchone()
    stats["last_synced"] = row[0] if row else None
    stats["top_5_connectors"] = _rows(conn, "SELECT connector_name, COUNT(*) AS calls FROM connector_calls GROUP BY connector_name ORDER BY calls DESC LIMIT 5")
    return stats


def _get_conversations(conn: sqlite3.Connection, args: dict) -> list[dict]:
    limit = int(args.get("limit", 50))
    filters, params = [], []
    if "channel_id" in args:
        filters.append("e.channel_id = ?"); params.append(args["channel_id"])
    if "design_mode" in args:
        filters.append("e.design_mode = ?"); params.append(1 if args["design_mode"] else 0)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    return _rows(conn, f"""
        SELECT e.conversation_id,
               MIN(e.session_id) AS session_id,
               MIN(e.user_id) AS user_id,
               MIN(e.channel_id) AS channel_id,
               MAX(e.design_mode) AS design_mode,
               MIN(e.timestamp) AS first_event,
               MAX(e.timestamp) AS last_event,
               SUM(CASE WHEN e.event_name='BotMessageReceived' THEN 1 ELSE 0 END) AS messages_received,
               SUM(CASE WHEN e.event_name='BotMessageSend' THEN 1 ELSE 0 END) AS messages_sent,
               GROUP_CONCAT(DISTINCT NULLIF(e.topic_name,'')) AS topics,
               COUNT(DISTINCT c.row_id) AS connector_calls
        FROM conversation_events e
        LEFT JOIN connector_calls c ON c.conversation_id = e.conversation_id
        {where}
        GROUP BY e.conversation_id ORDER BY first_event DESC LIMIT ?
    """, (*params, limit))


def _get_conversation_detail(conn: sqlite3.Connection, conversation_id: str) -> dict:
    return {
        "conversation_id": conversation_id,
        "events": _rows(conn, "SELECT timestamp, event_name, topic_name, text FROM conversation_events WHERE conversation_id=? ORDER BY timestamp", (conversation_id,)),
        "connector_calls": _rows(conn, "SELECT timestamp, connector_name, action_target, success, result_code, duration_ms FROM connector_calls WHERE conversation_id=? ORDER BY timestamp", (conversation_id,)),
    }


def _get_user_prompts(conn: sqlite3.Connection, args: dict) -> list[dict]:
    limit = int(args.get("limit", 50))
    filters = ["event_name = 'BotMessageReceived'", "text != ''", "text IS NOT NULL"]
    params: list = []
    if "search" in args:
        filters.append("text LIKE ?")
        params.append(f"%{args['search']}%")
    if "conversation_id" in args:
        filters.append("conversation_id = ?")
        params.append(args["conversation_id"])
    if "design_mode" in args:
        filters.append("design_mode = ?")
        params.append(1 if args["design_mode"] else 0)
    where = f"WHERE {' AND '.join(filters)}"
    return _rows(conn, f"""
        SELECT timestamp, conversation_id, user_id, channel_id, design_mode, text
        FROM conversation_events
        {where}
        ORDER BY timestamp DESC LIMIT ?
    """, (*params, limit))


def _get_connector_calls(conn: sqlite3.Connection, args: dict) -> list[dict]:
    limit = int(args.get("limit", 50))
    filters, params = [], []
    if "connector_name" in args: filters.append("connector_name=?"); params.append(args["connector_name"])
    if "action_target" in args: filters.append("action_target LIKE ?"); params.append(f"%{args['action_target']}%")
    if "success" in args: filters.append("success=?"); params.append(1 if args["success"] else 0)
    if "design_mode" in args: filters.append("design_mode=?"); params.append(1 if args["design_mode"] else 0)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    return _rows(conn, f"SELECT timestamp, connector_name, action_target, conversation_id, user_id, channel_id, design_mode, success, result_code, duration_ms FROM connector_calls {where} ORDER BY timestamp DESC LIMIT ?", (*params, limit))


def _get_top_connectors(conn: sqlite3.Connection, args: dict) -> list[dict]:
    limit = int(args.get("limit", 10))
    filters, params = [], []
    if "design_mode" in args: filters.append("design_mode=?"); params.append(1 if args["design_mode"] else 0)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    return _rows(conn, f"""
        SELECT connector_name, action_target,
               COUNT(*) AS total_calls, SUM(success) AS successful,
               SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) AS failed,
               ROUND(AVG(duration_ms),1) AS avg_duration_ms,
               ROUND(MAX(duration_ms),1) AS max_duration_ms
        FROM connector_calls {where}
        GROUP BY connector_name, action_target ORDER BY total_calls DESC LIMIT ?
    """, (*params, limit))


def _search_by_user(conn: sqlite3.Connection, args: dict) -> dict:
    uid, limit = args["user_id"], int(args.get("limit", 50))
    return {
        "user_id": uid,
        "conversations": _rows(conn, "SELECT DISTINCT conversation_id, channel_id, design_mode, MIN(timestamp) AS first_seen FROM conversation_events WHERE user_id=? GROUP BY conversation_id ORDER BY first_seen DESC LIMIT ?", (uid, limit)),
        "connector_calls": _rows(conn, "SELECT timestamp, connector_name, action_target, success, duration_ms FROM connector_calls WHERE user_id=? ORDER BY timestamp DESC LIMIT ?", (uid, limit)),
    }


def _run_sql(conn: sqlite3.Connection, query: str) -> list[dict]:
    if not query.strip().upper().startswith("SELECT"):
        raise ValueError("Only SELECT statements are allowed.")
    return _rows(conn, query)


def _get_agents(conn: sqlite3.Connection) -> list[dict]:
    return _rows(conn, """
        SELECT
            b.bot_id,
            b.display_name,
            b.environment_id,
            e.display_name   AS environment_name,
            e.type           AS environment_type,
            b.created_at,
            b.modified_at,
            b.published_at,
            s.solution_name,
            s.solution_unique,
            s.version        AS solution_version,
            s.is_managed
        FROM pva_bots b
        LEFT JOIN pva_environments e ON e.environment_id = b.environment_id
        LEFT JOIN pva_bot_solutions s ON s.bot_id = b.bot_id
        ORDER BY b.display_name
    """)


def _get_environments(conn: sqlite3.Connection) -> list[dict]:
    envs = _rows(conn, "SELECT * FROM pva_environments ORDER BY display_name")
    agents_by_env = {}
    for r in _rows(conn, "SELECT environment_id, display_name FROM pva_bots"):
        agents_by_env.setdefault(r["environment_id"], []).append(r["display_name"])

    dlp_all = _rows(conn, "SELECT display_name, environment_type, blocked_connectors, business_connectors, non_business_connectors FROM pva_dlp_policies")
    policies_all_envs = [p for p in dlp_all if p["environment_type"] == "AllEnvironments"]

    result = []
    for env in envs:
        eid = env["environment_id"]
        policies_specific = [p for p in dlp_all if p["environment_type"] == "OnlyEnvironments"]
        result.append({
            **env,
            "agents": agents_by_env.get(eid, []),
            "dlp_policies": policies_all_envs + policies_specific,
        })
    return result


def _get_viva_insights(conn: sqlite3.Connection, args: dict) -> list[dict]:
    filters, params = [], []
    if "user_id" in args:
        filters.append("v.user_id = ?"); params.append(args["user_id"])
    if "week_start" in args:
        filters.append("v.week_start = ?"); params.append(args["week_start"])
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    limit = int(args.get("limit", 50))

    return _rows(conn, f"""
        SELECT
            v.user_id,
            v.week_start,
            v.week_end,
            ROUND(v.focus_hours,   2) AS focus_hours,
            ROUND(v.meeting_hours, 2) AS meeting_hours,
            ROUND(v.email_hours,   2) AS email_hours,
            ROUND(v.chat_hours,    2) AS chat_hours,
            ROUND(v.after_hours,   2) AS after_hours,
            ROUND(v.focus_hours + v.meeting_hours + v.email_hours + v.chat_hours, 2)
                AS total_collaboration_hours,
            COUNT(DISTINCT e.conversation_id) AS agent_conversations_that_week
        FROM viva_person_insights v
        LEFT JOIN conversation_events e
            ON e.user_id = v.user_id
            AND date(e.timestamp) BETWEEN v.week_start AND v.week_end
            AND e.design_mode = 0
        {where}
        GROUP BY v.row_id
        ORDER BY v.week_start DESC, v.user_id
        LIMIT ?
    """, (*params, limit))


def _get_agent_activity(conn: sqlite3.Connection, args: dict) -> list[dict]:
    dm_filter = ""
    params: list = []
    if "design_mode" in args:
        dm_filter = "AND e.design_mode = ?"
        params.append(1 if args["design_mode"] else 0)

    return _rows(conn, f"""
        SELECT
            b.display_name          AS agent_name,
            b.schema_name,
            b.published_at,
            env.display_name        AS environment,
            COUNT(DISTINCT e.conversation_id)                                       AS total_conversations,
            COUNT(DISTINCT CASE WHEN e.design_mode = 0 THEN e.conversation_id END)  AS production_conversations,
            COUNT(DISTINCT CASE WHEN e.design_mode = 1 THEN e.conversation_id END)  AS test_conversations,
            MAX(e.timestamp)        AS last_activity
        FROM pva_bots b
        LEFT JOIN pva_environments env ON env.environment_id = b.environment_id
        LEFT JOIN conversation_events e
            ON e.topic_name LIKE b.schema_name || '.topic.%' {dm_filter}
        GROUP BY b.bot_id, b.display_name, b.schema_name, b.published_at, env.display_name
        ORDER BY last_activity DESC NULLS LAST
    """, tuple(params))


def _get_user_activity(conn: sqlite3.Connection, args: dict) -> list[dict]:
    limit = int(args.get("limit", 50))
    filters = ["user_id IS NOT NULL", "user_id != ''"]
    params: list = []
    if "design_mode" in args:
        filters.append("design_mode = ?")
        params.append(1 if args["design_mode"] else 0)
    where = "WHERE " + " AND ".join(filters)

    return _rows(conn, f"""
        SELECT
            e.user_id,
            COUNT(DISTINCT e.conversation_id)   AS total_conversations,
            SUM(CASE WHEN e.event_name = 'BotMessageReceived' THEN 1 ELSE 0 END) AS messages_sent,
            GROUP_CONCAT(DISTINCT e.channel_id) AS channels,
            GROUP_CONCAT(DISTINCT
                CASE WHEN e.topic_name LIKE '%.topic.%'
                THEN substr(e.topic_name, 1, instr(e.topic_name, '.topic.') - 1)
                END
            )                                   AS agents_interacted,
            MIN(e.timestamp)                    AS first_seen,
            MAX(e.timestamp)                    AS last_activity
        FROM conversation_events e
        {where}
        GROUP BY e.user_id
        ORDER BY last_activity DESC
        LIMIT ?
    """, (*params, limit))


# ---------------------------------------------------------------------------
# Entry points: stdio (local) or HTTP/SSE (deployed)
# ---------------------------------------------------------------------------

async def _run_stdio() -> None:
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def _run_http() -> None:
    import contextlib
    from mcp.server.sse import SseServerTransport
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Mount, Route
    import uvicorn

    class EntraAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if request.method == "OPTIONS" or request.url.path in ("/health", "/"):
                return await call_next(request)
            try:
                _validate_token(dict(request.headers))
            except ValueError as e:
                print(f"AUTH FAIL [{request.method} {request.url.path}] headers: {dict(request.headers)}", file=sys.stderr)
                return JSONResponse({"error": str(e)}, status_code=401)
            return await call_next(request)

    # Legacy SSE transport (Claude Code, older clients)
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())

    # Streamable HTTP transport (Copilot Studio, AI Foundry, newer MCP clients)
    session_manager = StreamableHTTPSessionManager(
        app=server,
        event_store=None,
        json_response=False,
        stateless=True,   # stateless = no session pinning required; simplest for agent platforms
    )

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with session_manager.run():
            yield

    starlette_app = Starlette(
        lifespan=lifespan,
        routes=[
            Route("/",          endpoint=lambda r: JSONResponse({"status": "ok"})),
            Route("/health",    endpoint=lambda r: JSONResponse({"status": "ok"})),
            Route("/sse",       endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )
    starlette_app.add_middleware(EntraAuthMiddleware)

    # Route /mcp* to the StreamableHTTP session manager directly (no prefix stripping)
    # and everything else to Starlette. This avoids Starlette's Mount stripping the
    # path before passing to the ASGI handler.
    async def root_app(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            if path == "/mcp" or path.startswith("/mcp/"):
                await session_manager.handle_request(scope, receive, send)
                return
        await starlette_app(scope, receive, send)

    uvicorn.run(root_app, host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    import asyncio
    mode = os.getenv("MCP_TRANSPORT", "stdio")
    if mode == "http":
        _run_http()
    else:
        asyncio.run(_run_stdio())
