# Copilot & M365 Insights

Governance and telemetry reporting for Microsoft Copilot Studio agents across an M365 tenant. Pulls data from a dozen Azure and Microsoft 365 APIs, stores it in a local SQLite database, and outputs a multi-sheet Excel workbook — plus an MCP server that lets AI agents (Copilot Studio, M365 Copilot, AI Foundry) query the telemetry in plain English.

---

## What it does

- **Collects** usage, connector health, DLP violations, agent inventory, M365 Copilot adoption, and Copilot credit consumption from across your tenant
- **Imports** CSV exports from the M365 Admin Center, Power Platform Admin Center, and Viva Insights
- **Stores** everything in a local SQLite database (optionally synced to Azure Blob Storage)
- **Exports** a timestamped Excel workbook with 30+ analytical sheets
- **Scores** agent experience quality using an XLA model: Persona → Journey → XLA
- **Exposes** an MCP server (stdio locally, HTTP on Azure Container Apps) so AI agents can query the data conversationally

<img width="1078" height="1032" alt="image" src="https://github.com/user-attachments/assets/c1778089-8d53-4886-952f-352322820692" />

---

## Data sources

### Live API sources

| Source | What it provides |
|---|---|
| Log Analytics / App Insights | Agent invocations, connector calls, OTel traces |
| Azure Monitor | Dependency failures, exceptions, alerts |
| Power Platform Admin API | Agent inventory, environments, DLP policies |
| Dataverse Web API | Agent solutions, publisher info |
| Microsoft Graph | M365 Copilot usage, Teams usage, user directory |
| Viva Insights | Person-level productivity signals |
| Microsoft Purview | Data governance signals |
| Microsoft Defender for Cloud | Security alerts, secure score |

### CSV imports (manual export → local file → auto-imported on sync)

| Env var | Where to export from | What it populates | Current Export Format |
|---|---|---|---|
| `VIVA_REPROT_CS_DIR` | Viva Insights / M365 Copilot Admin > Copilot Studio agents report > Export folder | Session metrics, topics, WAU, autonomous metrics | Folder: `AgentSessionMetrics.Csv`, `AgentTopicMetrics.Csv`, `AgentKnowledgeSourceMetrics.Csv`, `AgentAutonomousMetrics_*.Csv`, `AgentActionMetrics.Csv`, `CopilotAgent.Csv`, `AgentWeeklyActiveUsers.Csv`, `AgentExtendedMetadata.Csv` |
| `VIVA_REPORT_ADOPTION` | Viva Insights > Copilot Adoption report > Export | Per-user weekly Copilot prompt counts by app | `Copilot Adoption Report_<Tenant>.Csv` |
| `VIVA_REPORT_IMPACT` | Viva Insights > Copilot Impact report > Export | Per-user work-pattern signals alongside Copilot activity | `Copilot Impact_<Tenant>.Csv` |
| `VIVA_REPORT_CONSUMPTION` | Viva Insights > Consumption > Export (weekly dashboard) | Per-person weekly Copilot credit consumption by service (enhances Tokenomics) | Folder: `PeopleMetaData.csv`, `PersonServiceCreditsMetrics.csv`, `SpendingPolicyMetadata.csv` |
| `VIVA_REPORT_CONSUMPTION_DAILY` | Viva Insights > Consumption > Export (daily, incl. GitHub) | Per-person **daily** M365 service credits (e.g. Cowork) and GitHub AI credits → Credits_Daily, GitHub_AI_Credits, KPI GitHub metrics. Kept separate from the weekly export so the two aren't double-counted | Folder: `PeopleMetaData.csv`, `PersonM365CreditsMetrics.csv`, `PersonGitHubCreditsMetrics.csv`, `M365SpendingPolicyMetaData.csv` |
| `M365ADMIN_AGENT_INVENTORY` | M365 Admin Center > Copilot > Agents > All agents > Export | Full agent registry with metadata, permissions, instructions | `Agents_YYYY-MM-DD_HH_MM_SS.csv` |
| `M365ADMIN_USAGE_REPORT_AGENTS` | M365 Admin > Reports > Usage > M365 Copilot > Agents > Export (Agents tab) | 30-day per-agent active users and responses | `DeclarativeAgents_Agents_30_YYYY-MM-DDTHH-MM-SS.csv` |
| `M365ADMIN_USAGE_REPORT_AGENTUSERS` | M365 Admin > Reports > Usage > M365 Copilot > Agents > Export (Users & Agents tab) | 30-day per-user per-agent activity | `DeclarativeAgents_Users___agents_30_YYYY-MM-DDTHH-MM-SS.csv` |
| `M365ADMIN_USAGE_REPORT_USERS` | M365 Admin > Reports > Usage > M365 Copilot > Agents > Export (Users tab) | 30-day per-user rollup (agents used, responses received) | `DeclarativeAgents_Users_30_YYYY-MM-DDTHH-MM-SS.csv` |
| `M365ADMIN_COWORK_USAGE` | M365 Admin Center > Copilot > Cowork > Cowork Usage Details > Export | Per-user Cowork task activity | `CoworkUserDetails.csv` |
| `M365ADMIN_USAGE_COPILOT` | M365 Admin > Reports > Usage > M365 Copilot > Copilot > Copilot Usage Details > Export | Per-user Copilot prompt/last-activity detail (merges into M365_Copilot_Usage) | `FastCopilotActivityUserDetailM_D_YYYY H_MM_SS PM.csv` |
| `M365ADMIN_USAGE_COPILOT_CHAT` | M365 Admin > Reports > Usage > M365 Copilot > Copilot Chat > Usage Details > Export | Per-user Copilot Chat prompts, active days and per-surface last activity (licensed and unlicensed) → M365_Copilot_Chat_Usage | `FastCopilotChatActivityUserDetailM_D_YYYY H_MM_SS PM.csv` |
| `M365ADMIN_CONNECTORS_USAGE` | M365 Admin > Reports > Usage > M365 Copilot > Connectors > Export (Connectors tab) | 30-day per-connector active users and Copilot responses → M365_Connectors_Usage | `ConnectorsUsage_Connectors_P30_YYYY-MM-DDTHH-MM-SS.csv` |
| `M365ADMIN_CONNECTORS_USERS` | M365 Admin > Reports > Usage > M365 Copilot > Connectors > Export (Users tab) | 30-day per-user connectors used and responses received → M365_Connectors_Users | `ConnectorsUsage_Users_P30_YYYY-MM-DDTHH-MM-SS.csv` |
| `PPADMIN_LICENSES_CS_CONSUMPTION_ENV` | Power Platform Admin > Licensing > Copilot Studio > Export > Entitlement Consumption (Tenant) | Per-environment prepaid vs PAYG credit burn | `EntitlementConsumptionTenantDetailsReport_MCSMessages_180.csv` |
| `PPADMIN_LICENSES_CS_CONSUMPTION_AGENT` | Power Platform Admin > Licensing > Copilot Studio > Export > Entitlement Consumption (Per Agent) | Per-agent credit consumption by feature and channel | `EntitlementConsumptionTenantPerAgentDetailsReport_MCSMessages_180.csv` |
| `PPADMIN_LICENSES_CS_CONSUMPTION_USER` | Power Platform Admin > Licensing > Copilot Studio > Export > Entitlement Consumption (Per User) | Per-user credit consumption | `EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages_180.csv` |
| `PPADMIN_LICENSES_CS_CONSUMPTION_MANAGEAGENTS` | Power Platform Admin > Licensing > Copilot Studio > Manage Agents > Export | Daily capacity consumption by resource, feature, and channel | `CapacityConsumptionTenantDetailsReport.csv` |
| `M365USAGE_ACTIVATIONS_USERS` | M365 Admin > Reports > Usage > Microsoft 365 Apps usage > Activations > Export | Per-user M365 Apps activation status by device type | `Office365ActivationsUserDetailM_D_YYYY H_MM_SS PM.csv` |
| `M365USAGE_ACTIVE_USERS_SERVICES` | M365 Admin > Reports > Usage > Microsoft 365 Apps usage > Active Users > Services Export | Tenant-wide active vs. inactive user counts per service | `Office365ServicesUserCountsM_D_YYYY H_MM_SS PM.csv` |
| `M365USAGE_ACTIVE_USERS_ACTIVITY` | M365 Admin > Reports > Usage > Microsoft 365 Apps activity > Active Users > Activity Export | Daily/period activity counts per service | `Office365ActiveUserActivityCountsM_D_YYYY H_MM_SS PM.csv` |
| `M365USAGE_ACTIVE_USERS_COUNTS` | M365 Admin > Reports > Usage > Active users - Office 365 > Active Users > Users Export | Tenant-wide active vs. inactive user counts per service | `Office365ActiveUserCountsM_D_YYYY H_MM_SS PM.csv` |
| `M365USAGE_ACTIVE_USERS_DETAIL` | M365 Admin > Reports > Usage > Microsoft 365 Apps usage > Active Users > Export | Per-user license/activity detail per service | `Office365ActiveUserDetailM_D_YYYY H_MM_SS PM.csv` |
| `M365USAGE_PROPLUS_PLATFORMS` | M365 Admin > Reports > Usage > Microsoft 365 Apps usage > Usage > Platforms Export | User counts by platform (Windows/Mac/mobile/web) | `ProPlusUsagePlatformsUserCountsV2M_D_YYYY H_MM_SS PM.csv` |
| `M365USAGE_PROPLUS_COUNTS` | M365 Admin > Reports > Usage > Microsoft 365 Apps usage > Usage > Users Export | User counts per M365 App (Outlook, Word, Excel, PowerPoint, OneNote, Teams) | `ProPlusUsageUserCountsV2M_D_YYYY H_MM_SS PM.csv` |
| `M365USAGE_PROPLUS_DETAIL` | M365 Admin > Reports > Usage > Microsoft 365 Apps usage > Usage > Export | Per-user app/platform usage flags and last-activity dates | `ProPlusUsageUserDetailV2M_D_YYYY H_MM_SS PM.csv` |
| `BILLING_LICENCES` | M365 Admin Center > Billing > Licenses (Your products) > Export | Tenant license inventory: total/assigned/expired counts per SKU | `ProductList_M_D_YYYY_H_MM_SS_AM/PM.csv` |
| `AGENT_JOURNEY_MAP` | Maintained manually — see [Experience Model](#experience-model-xla) below | Agent → Journey → Persona dimension for XLA scoring | Manual CSV: `agent_id,agent_name,journey_name,persona_type` |
| `USAGE_AGENT_ID_OVERRIDES` | Maintained manually — see [Usage-to-Credit Agent ID Crosswalk](#usage-to-credit-agent-id-crosswalk) below | Forces `m365_usage_agents.resolved_agent_id` for ambiguous agent names | Manual CSV: `agent_name,bot_id` |

---

## Excel output sheets

| Sheet | Contents |
|---|---|
| **Copilot_Adoption_Summary** | Tenant-wide KPIs for the latest period vs the previous one, plus when each source was last loaded |
| **Cowork_Summary** | Cowork task activity and credit consumption dashboard |
| **KPI History** | One row per data period (month): Copilot users/prompts, Copilot Chat, Viva adoption, agent usage, Copilot Studio outcomes, credits — with trend charts |
| **KPI Trends** | Weekly/monthly series from the stored history (Copilot activity, agent sessions, credits, M365 service usage) with charts — works from a single import |
| **XLA_Measurements** | XLA scorecard computed from session metrics |
| **XLA_Persona_Journey** | XLA scores aggregated by persona and journey (colour-coded) |
| **XLA_Agent_Contribution** | Per-agent breakdown of sessions, completion, escalation by persona/journey |
| **Invocations** | OTel conversation events |
| **Connectors** | Connector call detail with latency and success rates |
| **AI_Model_Calls** | Generative AI model call log |
| **Agents** | Full agent registry from Dataverse |
| **Environments** | Power Platform environments |
| **Publishers** | Dataverse publishers |
| **DLP Policies** | Data loss prevention policy list |
| **M365_Copilot_Usage** | Per-user M365 Copilot usage (Graph API and/or the Copilot Usage Details CSV export) |
| **M365_Copilot_Chat_Usage** | Per-user Microsoft 365 Copilot Chat prompts and activity by surface, licensed and unlicensed users |
| **M365_Connectors_Usage** | 30-day per-connector active users and responses provided in Copilot |
| **M365_Connectors_Users** | 30-day per-user connectors used and responses received |
| **M365_Copilot_Trend** | Tenant-wide active user count trend |
| **M365_Copilot_Packages** | Copilot licence packages |
| **M365_O365_Users** | Broad O365 activity (Exchange, SharePoint, Teams) |
| **M365_App_Users** | Per-user M365 app activation status |
| **M365_Agent_Inventory** | Agent registry from M365 Admin Center |
| **M365_Usage_Agents** | 30-day per-agent usage snapshot |
| **M365_Usage_AgentUsers** | 30-day per-user per-agent activity |
| **M365_Usage_Users** | 30-day per-user agent activity rollup |
| **M365_Cowork_Usage** | Per-user Cowork task activity |
| **M365_Activations** | Per-user M365 Apps activation status by device type |
| **M365_Services_Counts** | Active/inactive user counts per service (Exchange, Teams, OneDrive, SharePoint, Yammer) |
| **M365_Activity_Counts** | Daily activity counts per service |
| **M365_Active_Counts** | Tenant-wide active user count trend |
| **M365_Active_Users** | Per-user license/activity detail per service |
| **M365_ProPlus_Platforms** | User counts by platform (Windows/Mac/mobile/web) |
| **M365_ProPlus_Counts** | User counts per M365 App |
| **M365_ProPlus_Users** | Per-user app/platform usage detail |
| **Billing_Licences** | Tenant licence inventory (product list): total / assigned / available / % assigned / expired per SKU |
| **Teams_Usage** | Teams chat, meeting, and call activity |
| **Viva_Person_Insights** | Person-level Viva productivity signals |
| **Viva_CS_Sessions** | Daily session outcomes and CSAT per agent |
| **Viva_CS_Topics** | Per-topic session breakdown |
| **Viva_CS_WAU** | Weekly active users per agent |
| **Viva_CS_Autonomous** | Daily autonomous run summary |
| **Viva_Copilot_Adoption** | Per-user weekly Copilot prompt counts by app (weeks with Copilot activity only) |
| **Viva_Copilot_Impact** | Per-user productivity signals alongside Copilot activity |
| **Tokenomics_Summary** | Credit consumption dashboard: entitlement, burn rate, top agents/users, credits by service |
| **Tokenomics_Capacity** | Daily capacity consumption by resource/feature/channel |
| **Tokenomics_Entitlement** | Per-environment prepaid vs PAYG entitlement burn |
| **Tokenomics_PerAgent** | Credit consumption broken down by agent |
| **Tokenomics_PerUser** | Credit consumption broken down by user |
| **Tokenomics_Consumption_Detail** | Per-person, per-service credit consumption (Viva Insights Consumption export) |
| **Credits_Daily** | Daily credits by service (M365 services such as Cowork, and GitHub AI) plus per-person daily M365 detail (Viva daily consumption export) |
| **GitHub_AI_Credits** | Per-person GitHub AI credit rollup: active days, total and average credits, Copilot licence flag |
| **AzureMonitor_Health** | Dependency failures and exceptions from Azure Monitor |
| **CrossRef_Summary** | Conversations with correlated OTel + Azure Monitor failures |

---

## Experience Model (XLA)

The XLA model shifts reporting from *"did the agent work?"* to *"did the agent improve the experience for the right persona in the right journey?"*

### How it works

1. You maintain `imports/agent_journey_persona_map.csv` — a static file that assigns each agent to a **journey** and **persona**.
2. On every sync, this file is loaded into the `dim_agent_journey_persona` table.
3. Session metrics are joined against it to produce XLA scores per persona+journey combination.
4. Results appear in the `XLA_Persona_Journey` and `XLA_Agent_Contribution` sheets.

### The mapping file

```csv
agent_id,agent_name,journey_name,persona_type
1b772240-...,IT Compass,Get Help,end_user
87393e81-...,Finance Policy Chat,Find Info,knowledge_worker
e2e9b9bf-...,Cyber Event Information Agent,Automate Work,operations
```

**`journey_name`** — one of four values:

| Value | When to use |
|---|---|
| `Get Help` | User needs answers, support, or assistance |
| `Complete Task` | User needs to submit, create, or process something |
| `Find Info` | User needs to look something up or understand something |
| `Automate Work` | Agent runs autonomously with no direct user interaction |

**`persona_type`** — who is using the agent:

| Value | Who |
|---|---|
| `end_user` | General employee — broad audience |
| `it_support` | IT ops or service desk staff |
| `hr` | HR team or HR-driven processes |
| `knowledge_worker` | Analysts, finance, legal, sales — information-intensive roles |
| `operations` | Engineering or ops teams running processes or pipelines |

Point `AGENT_JOURNEY_MAP` at the file in your `.env`. The `agent_id` must match exactly what appears in the Viva CS session reports (grab it from the Tokenomics or M365 Admin reports if needed). One agent can have multiple rows if it serves multiple journeys or personas.

**XLA score formula:** `completion_rate × 0.6 + (100 − escalation_rate) × 0.2 + (100 − abandonment_rate) × 0.2`

Scores ≥ 75 are green, 50–74 amber, < 50 red in the Excel sheet.

---

## Agent ID Crosswalk

Each source names agents in its own ID space:

| Source | ID | Example |
|---|---|---|
| Power Platform / Dataverse, tokenomics, `m365_admin_agent_inventory.bot_id` | Copilot Studio bot GUID | `73ef9d26-ac47-f111-…` |
| Viva Copilot Studio report (`viva_reports_cs_*`) | Viva AgentId (a separate GUID space) | `01e3d1c9-25f8-af6f-…` |
| M365 Admin usage report / inventory `title_id` | Title ID | `T_…`, `P_…`, `U_…`, `SP…` |

At the end of every sync the `dim_agent_xref` table is rebuilt to map each source's agent onto the bot GUID, recording how the match was made (`match_method`):

- **M365 usage-report agents:** manual override (by name) → exact match on the inventory `title_id` → an inventory name that maps to exactly one bot GUID → `unresolved`.
- **Viva Copilot Studio agents:** their own ID when Power Platform/Dataverse data is loaded → exact inventory `bot_id` → a unique inventory name → `unresolved`.

Names shared by several agents (the same agent cloned across dev/test/prod) are never guessed — they stay `unresolved`. `m365_usage_agents.resolved_agent_id` is filled from the crosswalk, so joins between usage volume and credit consumption should key off `resolved_agent_id` (or `dim_agent_xref.bot_id`), not agent names. Many usage-report agents (e.g. SharePoint agents) match an inventory row but have no Copilot Studio GUID at all; `dim_agent_xref.title_id` still links those.

To force a mapping for an ambiguous name:

1. Run a sync, then list unresolved agents: `SELECT * FROM dim_agent_xref WHERE match_method = 'unresolved'`.
2. Add a row per name to your override file:

```csv
agent_name,bot_id
Software Provisioning Agent,73ef9d26-ac47-f111-bec6-00224805f648
```

3. Point `USAGE_AGENT_ID_OVERRIDES` at the file in your `.env` and re-run sync. Overrides always win over automatic matching.

---

## Prerequisites

- Python 3.12+
- Azure CLI (`az login`) — or a service principal with the permissions granted by `provision/step2_identity.sh`
- An M365 tenant with Copilot Studio agents and Application Insights connected

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

---

## Configuration

Copy the example and fill in your values:

```bash
cp config/.env.example .env
```

### Core variables

| Variable | Description |
|---|---|
| `AZURE_TENANT_ID` | Entra ID tenant (required) |
| `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` | Service principal — omit to use `az login` |
| `LOG_ANALYTICS_WORKSPACE_ID` | App Insights workspace |
| `DATAVERSE_URL` | e.g. `https://orgXXXXXXXX.crm.dynamics.com` |
| `AZURE_STORAGE_ACCOUNT` | Blob storage account for the deployed MCP server |
| `LOOKBACK_DAYS` | How far back to pull data (default: 30) |
| `OUTPUT_PATH` | Excel output filename (default: `agent_telemetry.xlsx`) |
| `DB_PATH` | SQLite database path (default: `agent_telemetry.db`) |

### CSV import variables

```env
# Viva / M365 Insights
VIVA_REPROT_CS_DIR=imports/June2026/CS+Agents+Report_YOKIEL
VIVA_REPORT_ADOPTION=imports/June2026/Copilot Adoption Report_YOKIEL.Csv
VIVA_REPORT_IMPACT=imports/June2026/Copilot Impact_YOKIEL.Csv
VIVA_REPORT_CONSUMPTION=imports/June2026/ConsumptionDashboard-Weekly
VIVA_REPORT_CONSUMPTION_DAILY=imports/June2026/Consumption_Daily

# M365 Admin Center
M365ADMIN_AGENT_INVENTORY=imports/June2026/Agents_2026-06-12_16_10_35.csv
M365ADMIN_USAGE_REPORT_AGENTS=imports/June2026/DeclarativeAgents_Agents_30_2026-06-12T16-09-57.csv
M365ADMIN_USAGE_REPORT_AGENTUSERS=imports/June2026/DeclarativeAgents_Users___agents_30_2026-06-12T16-09-29.csv
M365ADMIN_USAGE_REPORT_USERS=imports/June2026/DeclarativeAgents_Users_30_2026-06-18T18-11-03.csv
M365ADMIN_COWORK_USAGE=imports/June2026/Usage_Reports/CoworkUserDetails.csv
M365ADMIN_USAGE_COPILOT=imports/June2026/Usage_Reports/FastCopilotActivityUserDetail*.csv
M365ADMIN_USAGE_COPILOT_CHAT=imports/June2026/Copilot_Reports/FastCopilotChatActivityUserDetail*.csv
M365ADMIN_CONNECTORS_USAGE=imports/June2026/Copilot_Reports/ConnectorsUsage_Connectors_P30_*.csv
M365ADMIN_CONNECTORS_USERS=imports/June2026/Copilot_Reports/ConnectorsUsage_Users_P30_*.csv

# Power Platform Admin Center — Copilot credit consumption (Tokenomics_* tables)
PPADMIN_LICENSES_CS_CONSUMPTION_ENV=imports/June2026/EntitlementConsumptionTenantDetailsReport_MCSMessages_180.csv
PPADMIN_LICENSES_CS_CONSUMPTION_AGENT=imports/June2026/EntitlementConsumptionTenantPerAgentDetailsReport_MCSMessages_180.csv
PPADMIN_LICENSES_CS_CONSUMPTION_USER=imports/June2026/EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages_180.csv
PPADMIN_LICENSES_CS_CONSUMPTION_MANAGEAGENTS=imports/June2026/CapacityConsumptionTenantDetailsReport.csv

# M365 Usage Details (M365 Admin Center > Reports > Usage) & Billing
M365USAGE_ACTIVATIONS_USERS=imports/June2026/Usage_Reports/Office365ActivationsUserDetail.csv
M365USAGE_ACTIVE_USERS_SERVICES=imports/June2026/Usage_Reports/Office365ServicesUserCounts.csv
M365USAGE_ACTIVE_USERS_ACTIVITY=imports/June2026/Usage_Reports/Office365ActiveUserActivityCounts.csv
M365USAGE_ACTIVE_USERS_COUNTS=imports/June2026/Usage_Reports/Office365ActiveUserCounts.csv
M365USAGE_ACTIVE_USERS_DETAIL=imports/June2026/Usage_Reports/Office365ActiveUserDetail.csv
M365USAGE_PROPLUS_PLATFORMS=imports/June2026/Usage_Reports/ProPlusUsagePlatformsUserCountsV2.csv
M365USAGE_PROPLUS_COUNTS=imports/June2026/Usage_Reports/ProPlusUsageUserCountsV2.csv
M365USAGE_PROPLUS_DETAIL=imports/June2026/Usage_Reports/ProPlusUsageUserDetailV2.csv
# License inventory (M365 Admin Center → Billing → Licenses → Export)
BILLING_LICENCES=imports/June2026/Usage_Reports/ProductList.csv

# Experience model — Agent → Journey → Persona mapping for XLA scoring
AGENT_JOURNEY_MAP=imports/agent_journey_persona_map.csv
```

Paths accept `*` wildcards; the most recently modified match is used, so the timestamp the M365 Admin Center appends to every export filename doesn't need editing. Leave a variable unset (or commented out) when you don't have that export — the importer is skipped.

For multi-tenant use, keep a separate `.env` file per tenant and pass it with `--env`:

```bash
python -m src.main --env .env.<tenant> all
```

Per-datasource auth overrides (e.g. `LOG_ANALYTICS_CLIENT_ID`) are documented in `config/.env.example`.

---

## Usage

```bash
# Fetch all sources and export workbook in one step
python -m src.main all

# Fetch only (no export)
python -m src.main sync

# Export last sync to Excel (no new fetch)
python -m src.main export

# Import Copilot Studio analytics CSV exports from Viva
python -m src.main import-viva <path/to/csv/folder>
```

The workbook is written to `OUTPUT_PATH` (default: `agent_telemetry_<timestamp>.xlsx`).

CSV imports (Viva, M365 Admin, Power Platform, and the XLA mapping file) run automatically as part of `sync` and `all` whenever the corresponding env var is set.

---

## Data storage and monthly refreshes

Keep **one SQLite database per tenant** (`DB_PATH`) and re-run `sync` each month against the new exports — history accumulates, point-in-time reports are replaced.

| Kind of data | Examples | On each import |
|---|---|---|
| **Snapshot** (point-in-time, usually a 30-day window) | M365 usage reports, agent inventory, Copilot Chat / connectors usage, licences, activations, Power Platform environments / DLP | Table is cleared and reloaded, so users and agents missing from the new export don't linger |
| **History** (keyed by date) | Viva Copilot Studio daily/weekly metrics, Copilot Adoption/Impact, credit consumption by date, OTel events, KPI snapshots | Merged by key — new dates are added, re-imported dates are updated |

- An empty or missing export leaves the previous snapshot in place rather than wiping it.
- Every load is recorded in `import_log` (table, `snapshot`/`merge`, row count, time), and every sync in `sync_runs`.
- Copilot Adoption/Impact person-weeks with no Copilot activity are dropped after import (typically well over half the rows). Each person's first/last date in each report is kept in `dim_copilot_person`, which is what "enabled users" figures (e.g. the XLA scorecard) count. Impact work-pattern rows are all kept; for dropped weeks the Impact sheet shows 0 for action metrics and a blank "Enabled Days".
- User principal names are stored lower-cased in every table so sources with different casing join correctly.
- Existing databases are upgraded in place automatically the first time a newer version opens them (including the copy the deployed MCP server downloads). A very large tenant DB can take ~15–20 s on that first open.

### KPI history

Each sync writes one `kpi_snapshots` row for the **data period** its exports cover (`YYYY-MM`, from the latest report date in the loaded files — override with `KPI_PERIOD`). Re-running a month replaces its row, so running a tenant's months in chronological order rebuilds KPI History. Metrics from point-in-time exports are only recorded for the period whose run loaded them (a month without a Cowork export shows a blank, not last month's number); Viva and Copilot Studio metrics cover the last 4 weeks of data up to the period's date. The summary sheet compares the latest period with the previous one and lists which sources were carried forward from an earlier run.

A typical monthly refresh for a tenant:

```bash
# 1. Save the month's exports under imports/<Tenant>/<Tenant>_<MON><YEAR>/
#    (CS+Agents+Report_*/, ConsumptionDashboard-Weekly_*/, Copilot_Reports/, Usage_Reports/)
# 2. Repoint the paths in .env.<tenant> at the new folder; comment out any export you didn't get
# 3. Sync and export
python -m src.main --env .env.<tenant> all
```

---

## MCP server

The MCP server lets AI agents (Copilot Studio, M365 Copilot, Azure AI Foundry) query telemetry in natural language.

### Local (Claude Code / stdio)

Add to your `.mcp.json`:

```json
{
  "mcpServers": {
    "agent-telemetry": {
      "command": "python",
      "args": ["-m", "src.mcp_server.server"],
      "env": { "DB_PATH": "agent_telemetry.db", "MCP_TRANSPORT": "stdio" }
    }
  }
}
```

For several tenants, add one entry per tenant database (e.g. `agent-telemetry-<tenant>` with `DB_PATH=agent_telemetry_<tenant>.db`); each server reads only its own tenant's data.

### Deployed (Azure Container Apps / HTTP)

```bash
bash deploy.sh deploy-config/<tenant>.env
```

The deploy script provisions an ACR, builds and pushes the Docker image, creates an Azure Container App, and wires up Entra ID authentication. Microsoft agent platforms send Bearer tokens automatically.

---

## Provisioning a new tenant

Run the three provision scripts in order (from Azure Cloud Shell or with appropriate admin roles):

```bash
# 1. Create Log Analytics workspace + Application Insights
bash provision/step1_insights.sh

# 2. Grant the sync service principal all required read permissions + admin consent
bash provision/step2_identity.sh

# 3. Register the MCP server app in Entra ID
bash provision/step3_mcp.sh
```

See the header comments in each script for required admin roles and outputs.

---

## Project structure

```
src/
  fetchers/       # One module per data source (API + CSV importers)
  writers/        # One module per Excel sheet
  mcp_server/     # MCP server (stdio + HTTP)
  agent/          # Bot Framework conversational agent
  store/          # SQLite store (per-domain mixins: _schema/_base/_migrations + one module per data area) + Azure Blob Storage
config/           # Settings and datasource config (gitignored — use .env)
imports/          # Drop CSV exports here (gitignored)
  agent_journey_persona_map.csv   # XLA experience model — agent → journey → persona
provision/        # One-time Azure setup scripts
deploy.sh         # Build + deploy to Azure Container Apps
Dockerfile        # Container image for the MCP server
```

<img width="992" height="418" alt="image" src="https://github.com/user-attachments/assets/59e30e82-02f1-4bd9-9d24-2f75784eed1a" />
