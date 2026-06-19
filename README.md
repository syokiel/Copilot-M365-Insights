# Copilot Insights

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

| Env var | Where to export from | What it populates |
|---|---|---|
| `VIVA_REPROT_CS_DIR` | Viva Insights / M365 Copilot Admin > Copilot Studio agents report > Export folder | Session metrics, topics, WAU, autonomous metrics |
| `VIVA_REPORT_ADOPTION` | Viva Insights > Copilot Adoption report > Export | Per-user weekly Copilot prompt counts by app |
| `VIVA_REPORT_IMPACT` | Viva Insights > Copilot Impact report > Export | Per-user work-pattern signals alongside Copilot activity |
| `M365ADMIN_AGENT_INVENTORY` | M365 Admin Center > Copilot > Agents > All agents > Export | Full agent registry with metadata, permissions, instructions |
| `M365ADMIN_USAGE_REPORT_AGENTS` | M365 Admin > Reports > Usage > M365 Copilot > Agents > Export (Agents tab) | 30-day per-agent active users and responses |
| `M365ADMIN_USAGE_REPORT_AGENTUSERS` | M365 Admin > Reports > Usage > M365 Copilot > Agents > Export (Users & Agents tab) | 30-day per-user per-agent activity |
| `M365ADMIN_USAGE_REPORT_USERS` | M365 Admin > Reports > Usage > M365 Copilot > Agents > Export (Users tab) | 30-day per-user rollup (agents used, responses received) |
| `PPADMIN_LICENSES_CS_CONSUMPTION_ENV` | Power Platform Admin > Licensing > Copilot Studio > Export > Entitlement Consumption (Tenant) | Per-environment prepaid vs PAYG credit burn |
| `PPADMIN_LICENSES_CS_CONSUMPTION_AGENT` | Power Platform Admin > Licensing > Copilot Studio > Export > Entitlement Consumption (Per Agent) | Per-agent credit consumption by feature and channel |
| `PPADMIN_LICENSES_CS_CONSUMPTION_USER` | Power Platform Admin > Licensing > Copilot Studio > Export > Entitlement Consumption (Per User) | Per-user credit consumption |
| `PPADMIN_LICENSES_CS_CONSUMPTION_MANAGEAGENTS` | Power Platform Admin > Licensing > Copilot Studio > Manage Agents > Export | Daily capacity consumption by resource, feature, and channel |
| `AGENT_JOURNEY_MAP` | Maintained manually — see [Experience Model](#experience-model-xla) below | Agent → Journey → Persona dimension for XLA scoring |

---

## Excel output sheets

| Sheet | Contents |
|---|---|
| **Summary** | Tenant-wide KPI snapshot |
| **KPI History** | KPI trend over time |
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
| **M365_Copilot_Usage** | Per-user M365 Copilot usage (Graph API) |
| **M365_Copilot_Trend** | Tenant-wide active user count trend |
| **M365_Copilot_Packages** | Copilot licence packages |
| **M365_O365_Users** | Broad O365 activity (Exchange, SharePoint, Teams) |
| **M365_App_Users** | Per-user M365 app activation status |
| **M365_Agent_Inventory** | Agent registry from M365 Admin Center |
| **M365_Usage_Agents** | 30-day per-agent usage snapshot |
| **M365_Usage_AgentUsers** | 30-day per-user per-agent activity |
| **M365_Usage_Users** | 30-day per-user agent activity rollup |
| **Teams_Usage** | Teams chat, meeting, and call activity |
| **Viva_Person_Insights** | Person-level Viva productivity signals |
| **Viva_CS_Sessions** | Daily session outcomes and CSAT per agent |
| **Viva_CS_Topics** | Per-topic session breakdown |
| **Viva_CS_WAU** | Weekly active users per agent |
| **Viva_CS_Autonomous** | Daily autonomous run summary |
| **Viva_Copilot_Adoption** | Per-user weekly Copilot prompt counts by app |
| **Viva_Copilot_Impact** | Per-user productivity signals alongside Copilot activity |
| **Tokenomics_Capacity** | Daily capacity consumption by resource/feature/channel |
| **Tokenomics_Entitlement** | Per-environment prepaid vs PAYG entitlement burn |
| **Tokenomics_PerAgent** | Credit consumption broken down by agent |
| **Tokenomics_PerUser** | Credit consumption broken down by user |
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

# M365 Admin Center
M365ADMIN_AGENT_INVENTORY=imports/June2026/Agents_2026-06-12_16_10_35.csv
M365ADMIN_USAGE_REPORT_AGENTS=imports/June2026/DeclarativeAgents_Agents_30_2026-06-12T16-09-57.csv
M365ADMIN_USAGE_REPORT_AGENTUSERS=imports/June2026/DeclarativeAgents_Users___agents_30_2026-06-12T16-09-29.csv
M365ADMIN_USAGE_REPORT_USERS=imports/June2026/DeclarativeAgents_Users_30_2026-06-18T18-11-03.csv

# Power Platform Admin Center — Copilot credit consumption (Tokenomics_* tables)
PPADMIN_LICENSES_CS_CONSUMPTION_ENV=imports/June2026/EntitlementConsumptionTenantDetailsReport_MCSMessages_180.csv
PPADMIN_LICENSES_CS_CONSUMPTION_AGENT=imports/June2026/EntitlementConsumptionTenantPerAgentDetailsReport_MCSMessages_180.csv
PPADMIN_LICENSES_CS_CONSUMPTION_USER=imports/June2026/EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages_180.csv
PPADMIN_LICENSES_CS_CONSUMPTION_MANAGEAGENTS=imports/June2026/CapacityConsumptionTenantDetailsReport.csv

# Experience model — Agent → Journey → Persona mapping for XLA scoring
AGENT_JOURNEY_MAP=imports/agent_journey_persona_map.csv
```

For multi-tenant use, keep a separate `.env` file per tenant and pass it with `--env`:

```bash
python -m src.main --env .env.stryker all
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

## MCP server

The MCP server lets AI agents (Copilot Studio, M365 Copilot, Azure AI Foundry) query telemetry in natural language.

### Local (Claude Code / stdio)

Add to your `.mcp.json`:

```json
{
  "mcpServers": {
    "agent-telemetry": {
      "command": "python",
      "args": ["-m", "src.mcp_server.server"]
    }
  }
}
```

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
  store/          # SQLite + Azure Blob Storage
config/           # Settings and datasource config (gitignored — use .env)
imports/          # Drop CSV exports here (gitignored)
  agent_journey_persona_map.csv   # XLA experience model — agent → journey → persona
provision/        # One-time Azure setup scripts
deploy.sh         # Build + deploy to Azure Container Apps
Dockerfile        # Container image for the MCP server
```

<img width="992" height="418" alt="image" src="https://github.com/user-attachments/assets/59e30e82-02f1-4bd9-9d24-2f75784eed1a" />
