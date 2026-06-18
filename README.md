# Copilot Insights

Governance and telemetry reporting for Microsoft Copilot Studio agents across an M365 tenant. Pulls data from a dozen Azure and Microsoft 365 APIs, stores it in a local SQLite database, and outputs a multi-sheet Excel workbook — plus an MCP server that lets AI agents (Copilot Studio, M365 Copilot, AI Foundry) query the telemetry in plain English.

---

## What it does

- **Collects** usage, connector health, DLP violations, agent inventory, and M365 Copilot adoption from across your tenant
- **Stores** everything in a local SQLite database (optionally synced to Azure Blob Storage)
- **Exports** a timestamped Excel workbook with 20+ analytical sheets
- **Exposes** an MCP server (stdio locally, HTTP on Azure Container Apps) so AI agents can query the data conversationally

<img width="1078" height="1032" alt="image" src="https://github.com/user-attachments/assets/c1778089-8d53-4886-952f-352322820692" />

---

## Data sources

| Source | What it provides |
|---|---|
| Log Analytics / App Insights | Agent invocations, connector calls, OTel traces |
| Azure Monitor | Dependency failures, exceptions, alerts |
| Power Platform Admin API | Agent inventory, environments, DLP policies |
| Dataverse Web API | Agent solutions, publisher info |
| Microsoft Graph | M365 Copilot usage, Teams usage, user directory |
| Viva Insights | Person-level productivity signals |
| Copilot Studio Analytics (CSV) | Sessions, topics, WAU, autonomous metrics |
| Microsoft Purview | Data governance signals |
| Microsoft Defender for Cloud | Security alerts, secure score |
|---|---|
| Export / Import (.csv)|
| Microsoft Insights Reports | Copilot Impact, Copilot Adoption, Copilot Studio Agents |
| Microsoft M365 Admin Agent Inventory | Agent listing with metadata | M365 Admin > Agents > All Agents > Export |
| Microsoft M365 Admin Usage | M365 Admin > Reports > Usage > Microsoft 365 Copilot > Agents > Export (3x: Users,Agents, Users & Agents) |
| Microsoft M365 Admin Credit Usage | M365 Admin > Reports > Usage > Microsoft 365 Copilot > Credits > Export  |
| Microsoft Power Platform Credit Usage | Power Platform Admin > Licensing > Copilot Studio > Export (3x: Env,Agent,User) | 
| Microsoft Power Platform Credit Usage | Power Platform Admin > Licensing > Copilot Studio > Manage Agents > Export | 
|
| .config sample
# M365 Insights — 
| VIVA_REPROT_CS_DIR=imports/June2026/CS+Agents+Report_YOKIEL  # Copilot Studio CSV export folder — set path to auto-import on every sync/all run
| VIVA_REPORT_ADOPTION=imports/June2026/Copilot Adoption Report_YOKIEL.Csv
| VIVA_REPORT_IMPACT=imports/June2026/Copilot Impact_YOKIEL.Csv
# M365 Admin Center — 
| M365ADMIN_AGENT_INVENTORY=imports/June2026/Agents_2026-06-12_16_10_35.csv
| M365ADMIN_USAGE_REPORT_Users=imports/June2026/DeclarativeAgents_Users_30_2026-06-18T18-11-03.csv
| M365ADMIN_USAGE_REPORT_Agents=imports/June2026/DeclarativeAgents_Agents_30_2026-06-12T16-09-57.csv
| M365ADMIN_USAGE_REPORT_AgentUser=imports/June2026/DeclarativeAgents_Users___agents_30_2026-06-12T16-09-29.csv
| M365USAGE_REPORT_Credits=imports/June2026/????.csv
# Power Platform Admin Center — Copilot credit consumption (Tokenomics_* tables)
| PPADMIN_LICENSES_CS_CONSUMPTION_ENV=imports/June2026/EntitlementConsumptionTenantDetailsReport_MCSMessages_180.csv
| PPADMIN_LICENSES_CS_CONSUMPTION_AGENT=imports/June2026/EntitlementConsumptionTenantPerAgentDetailsReport_MCSMessages_180.csv
| PPADMIN_LICENSES_CS_CONSUMPTION_USER=imports/June2026/EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages_180.csv
| PPADMIN_LICENSES_CS_CONSUMPTION_MANAGEAGENTS=imports/June2026/CapacityConsumptionTenantDetailsReport.csv
---

## Excel output sheets

Summary, Agents, Invocations, Connectors, Environments, Publishers, DLP Policies, AI Usage, Azure Health, Cross-Reference, KPI History, M365 Copilot, M365 Copilot Trend, M365 App Users, O365 Users, M365 Packages, Teams Usage, Viva, Viva Sessions, Viva Topics, Viva WAU, Viva Autonomous

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

Key variables:

| Variable | Description |
|---|---|
| `AZURE_TENANT_ID` | Entra ID tenant (required) |
| `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` | Service principal — omit to use `az login` |
| `LOG_ANALYTICS_WORKSPACE_ID` | App Insights workspace |
| `DATAVERSE_URL` | e.g. `https://orgXXXXXXXX.crm.dynamics.com` |
| `AZURE_STORAGE_ACCOUNT` | Blob storage account for the deployed MCP server |
| `LOOKBACK_DAYS` | How far back to pull data (default: 30) |

For multi-tenant use, keep a separate `.env` file per tenant and pass it with `--env`:

```bash
python -m src.main --env .env.mwc all
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
  fetchers/       # One module per data source
  writers/        # One module per Excel sheet
  mcp_server/     # MCP server (stdio + HTTP)
  agent/          # Bot Framework conversational agent
  store/          # SQLite + Azure Blob Storage
config/           # Settings and datasource config (gitignored — use .env)
provision/        # One-time Azure setup scripts
deploy.sh         # Build + deploy to Azure Container Apps
Dockerfile        # Container image for the MCP server
```
<img width="1085" height="598" alt="image" src="https://github.com/user-attachments/assets/efeabcb1-69eb-4c2b-8556-8ad12c330aa6" />
