#!/usr/bin/env bash
# provision/phase2_mcp.sh
# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — MCP Server + Azure Infrastructure
# Creates:
#   • Entra app registration (agenttele-mcp-server) with read permissions on:
#       – Microsoft Graph: usage reports, Copilot analytics, Viva Insights,
#         directory, audit logs
#       – Dynamics CRM: Dataverse / Power Platform access
#       – Office 365 Management: activity feeds
#   • Azure Container Registry (agenttelemcp<SUFFIX>)
#   • Storage Account (agenttelemcp<SUFFIX>) + blob container
#   • Container Apps Environment + Container App (agenttele-mcp)
#   • Managed identity role assignments for storage and ACR
#   • Sync service principal role assignments for storage and Log Analytics
#
# All Azure resources are prefixed with  agenttele-mcp
#
# Run in Azure Cloud Shell:
#   bash phase2_mcp.sh
#
# Prerequisite: complete Phase 1 and have the App Insights connection string.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail   # -e removed: errors are handled explicitly

# ── CONFIG — fill in before running ──────────────────────────────────────────
SUBSCRIPTION_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
TENANT_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
RG="your-resource-group"
LOCATION="eastus"

# Globally-unique suffix appended to ACR and Storage names (1-8 lowercase alphanumeric).
# ACR name will be:     agenttelemcp<SUFFIX>
# Storage name will be: agenttelemcp<SUFFIX>
ACR_SUFFIX="mwc1"

# Application Insights connection string — output of Phase 1.
APP_INSIGHTS_CONN="InstrumentationKey=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx;IngestionEndpoint=https://eastus-8.in.applicationinsights.azure.com/;LiveEndpoint=https://eastus.livediagnostics.monitor.azure.com/;ApplicationId=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

# Object ID of the agent-telemetry-poc service principal
SYNC_SP_OBJECT_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

# Log Analytics Workspace resource ID — from Phase 1
LAW_RESOURCE_ID="/subscriptions/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx/resourceGroups/your-resource-group/providers/Microsoft.OperationalInsights/workspaces/agenttele-insights-law"
# ─────────────────────────────────────────────────────────────────────────────

ts()   { date "+%H:%M:%S"; }
step() { echo ""; echo "[$(ts)] ── $*"; }
info() { echo "          $*"; }
ok()   { echo "  [$(ts)] ✓  $*"; }
skip() { echo "  [$(ts)] –  $* — already exists, skipping."; }
warn() { echo "  [$(ts)] !  $*"; }

# Validate required vars
for VAR in SUBSCRIPTION_ID TENANT_ID RG LOCATION ACR_SUFFIX APP_INSIGHTS_CONN; do
  if [ -z "${!VAR:-}" ]; then
    echo "ERROR: $VAR is not set. Edit the CONFIG section at the top of this script."
    exit 1
  fi
done

if [[ ! "$ACR_SUFFIX" =~ ^[a-z0-9]{1,8}$ ]]; then
  echo "ERROR: ACR_SUFFIX must be 1-8 lowercase alphanumeric characters."
  exit 1
fi

# Derived names
ACR_NAME="agenttelemcp${ACR_SUFFIX}"
STORAGE_NAME="agenttelemcp${ACR_SUFFIX}"
APP_REG_NAME="agent-telemetry-poc"   # existing registration being reused
APP_ID_URI="api://${TENANT_ID}/agenttele-mcp"
CONTAINER="telemetry-data"
CA_ENV="agenttele-mcp-env"
CA_APP="agenttele-mcp"

exists_role() { az role assignment list --assignee "$1" --role "$2" --scope "$3" \
  --subscription "$SUBSCRIPTION_ID" --query "[0].id" -o tsv 2>/dev/null | grep -qv '^$'; }

echo ""
echo "======================================================"
echo "  Phase 2 — MCP Server + Azure Infrastructure"
echo "  Subscription:   $SUBSCRIPTION_ID"
echo "  Tenant:         $TENANT_ID"
echo "  Resource group: $RG  ($LOCATION)"
echo "  ACR:            $ACR_NAME"
echo "  Storage:        $STORAGE_NAME"
echo "  Container App:  $CA_APP"
echo "======================================================"

step "Setting subscription..."
az account set --subscription "$SUBSCRIPTION_ID"
ok "Subscription set."

# ── Resource providers ────────────────────────────────────────────────────────
step "Checking resource providers..."
for NS in Microsoft.ContainerRegistry Microsoft.App Microsoft.Storage; do
  info "Checking $NS..."
  STATE=$(az provider show -n "$NS" --subscription "$SUBSCRIPTION_ID" \
    --query "registrationState" -o tsv 2>/dev/null || echo "NotRegistered")
  if [ "$STATE" = "Registered" ]; then
    ok "$NS already registered."
  else
    info "Registering $NS (waiting)..."
    az provider register --namespace "$NS" --subscription "$SUBSCRIPTION_ID" --wait
    ok "$NS registered."
  fi
done

# ── Entra App Registration — reuse existing agent-telemetry-poc ───────────────
step "Entra App Registration: reusing agent-telemetry-poc"
info "Looking up existing app registration..."
MCP_APP_ID=$(az ad app list --display-name "agent-telemetry-poc" \
  --query "[0].appId" -o tsv 2>/dev/null || true)

if [ -z "$MCP_APP_ID" ]; then
  echo "ERROR: agent-telemetry-poc app registration not found."
  echo "       Check the app exists: az ad app list --query \"[?contains(displayName,'telemetry')].{Name:displayName,AppId:appId}\" -o table"
  exit 1
fi
ok "Found agent-telemetry-poc (appId: $MCP_APP_ID)."

info "Setting App ID URI: $APP_ID_URI"
az ad app update --id "$MCP_APP_ID" --identifier-uris "$APP_ID_URI" 2>/dev/null || \
  warn "App ID URI update skipped — may need admin consent in restricted tenants."

info "Ensuring service principal exists..."
az ad sp create --id "$MCP_APP_ID" 2>/dev/null || true
ok "Service principal ready."

# ── Telemetry.Read scope ──────────────────────────────────────────────────────
info "Checking Telemetry.Read scope..."
EXISTING_SCOPE=$(az ad app show --id "$MCP_APP_ID" \
  --query "api.oauth2PermissionScopes[?value=='Telemetry.Read'].id" -o tsv 2>/dev/null || true)
if [ -z "$EXISTING_SCOPE" ]; then
  info "Adding Telemetry.Read scope..."
  SCOPE_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
  if az ad app update --id "$MCP_APP_ID" --set \
    "api={\"oauth2PermissionScopes\":[{\"adminConsentDescription\":\"Read agent telemetry data\",\"adminConsentDisplayName\":\"Read telemetry\",\"id\":\"$SCOPE_ID\",\"isEnabled\":true,\"type\":\"User\",\"userConsentDescription\":\"Read agent telemetry\",\"userConsentDisplayName\":\"Read telemetry\",\"value\":\"Telemetry.Read\"}]}" 2>/dev/null; then
    ok "Telemetry.Read scope added."
  else
    warn "Telemetry.Read scope add skipped — requires Application Administrator."
    warn "Add manually: Entra ID → App registrations → agent-telemetry-poc → Expose an API → Add a scope"
  fi
else
  ok "Telemetry.Read scope already present."
fi

# ── API Permissions ───────────────────────────────────────────────────────────
GRAPH_APP="00000003-0000-0000-c000-000000000000"
CRM_APP="00000007-0000-0000-c000-000000000000"
O365_MGMT_APP="c5393580-f805-4401-95e8-94b7a6ef2fc2"

step "Resolving API permission IDs from tenant..."
get_graph_role() { az ad sp show --id "$GRAPH_APP" \
  --query "appRoles[?value=='$1'].id" -o tsv 2>/dev/null || true; }
get_o365_role()  { az ad sp show --id "$O365_MGMT_APP" \
  --query "appRoles[?value=='$1'].id" -o tsv 2>/dev/null || true; }
get_crm_role()   { az ad sp show --id "$CRM_APP" \
  --query "appRoles[?value=='$1'].id" -o tsv 2>/dev/null || true; }

info "Resolving Graph: Reports.Read.All..."
PERM_REPORTS=$(get_graph_role "Reports.Read.All")
info "Resolving Graph: ReportSettings.Read.All..."
PERM_REPORT_SETTINGS=$(get_graph_role "ReportSettings.Read.All")
info "Resolving Graph: Analytics.ReadAll (Viva Insights)..."
PERM_ANALYTICS=$(get_graph_role "Analytics.ReadAll")
info "Resolving Graph: User.Read.All..."
PERM_USER=$(get_graph_role "User.Read.All")
info "Resolving Graph: Directory.Read.All..."
PERM_DIR=$(get_graph_role "Directory.Read.All")
info "Resolving Graph: AuditLog.Read.All..."
PERM_AUDIT=$(get_graph_role "AuditLog.Read.All")
info "Resolving O365 Management: ActivityFeed.Read..."
PERM_ACTIVITY=$(get_o365_role "ActivityFeed.Read")
info "Resolving Dynamics CRM: user_impersonation..."
PERM_CRM=$(get_crm_role "user_impersonation")

echo ""
echo "          Permission resolution results:"
echo "            Graph Reports.Read.All:        ${PERM_REPORTS:-NOT FOUND}"
echo "            Graph ReportSettings.Read.All: ${PERM_REPORT_SETTINGS:-NOT FOUND}"
echo "            Graph Analytics.ReadAll:        ${PERM_ANALYTICS:-NOT FOUND}"
echo "            Graph User.Read.All:            ${PERM_USER:-NOT FOUND}"
echo "            Graph Directory.Read.All:       ${PERM_DIR:-NOT FOUND}"
echo "            Graph AuditLog.Read.All:        ${PERM_AUDIT:-NOT FOUND}"
echo "            O365 ActivityFeed.Read:         ${PERM_ACTIVITY:-NOT FOUND}"
echo "            CRM user_impersonation:         ${PERM_CRM:-NOT FOUND}"

step "Adding Microsoft Graph permissions..."
GRAPH_PERMS=""
for PERM_ID in "$PERM_REPORTS" "$PERM_REPORT_SETTINGS" "$PERM_ANALYTICS" \
               "$PERM_USER" "$PERM_DIR" "$PERM_AUDIT"; do
  [ -n "$PERM_ID" ] && GRAPH_PERMS="$GRAPH_PERMS ${PERM_ID}=Role"
done
if [ -n "$GRAPH_PERMS" ]; then
  # shellcheck disable=SC2086
  az ad app permission add --id "$MCP_APP_ID" --api "$GRAPH_APP" \
    --api-permissions $GRAPH_PERMS 2>/dev/null || true
  ok "Graph permissions added."
else
  warn "No Graph permissions resolved — skipped."
fi

step "Adding Office 365 Management permissions..."
if [ -n "$PERM_ACTIVITY" ]; then
  az ad app permission add --id "$MCP_APP_ID" --api "$O365_MGMT_APP" \
    --api-permissions "${PERM_ACTIVITY}=Role" 2>/dev/null || true
  ok "O365 Management ActivityFeed.Read added."
else
  warn "O365 Management SP not found in this tenant — skipping."
fi

step "Adding Dynamics CRM permission..."
if [ -n "$PERM_CRM" ]; then
  az ad app permission add --id "$MCP_APP_ID" --api "$CRM_APP" \
    --api-permissions "${PERM_CRM}=Scope" 2>/dev/null || true
  ok "Dynamics CRM user_impersonation added."
else
  warn "CRM SP not found in this tenant — skipping."
fi

step "Granting admin consent for all permissions..."
az ad app permission admin-consent --id "$MCP_APP_ID" 2>/dev/null && \
  ok "Admin consent granted." || \
  warn "Admin consent requires Global Admin — grant manually in Entra portal if this failed."

warn "NOTE: The sync SP also needs the 'Power Platform Administrator' Entra directory role"
warn "      to list environments and DLP policies via the BAP Admin API."
warn "      Entra ID → Roles and administrators → Power Platform Administrator → Add assignments."

# ── Container Registry ────────────────────────────────────────────────────────
step "Container Registry: $ACR_NAME"
info "Checking existence..."
if az acr show -n "$ACR_NAME" -g "$RG" --subscription "$SUBSCRIPTION_ID" &>/dev/null; then
  skip "ACR $ACR_NAME"
else
  info "Creating ACR (Basic SKU)..."
  az acr create -g "$RG" -n "$ACR_NAME" \
    --subscription "$SUBSCRIPTION_ID" --sku Basic --admin-enabled false
  ok "ACR created."
fi
ACR_ID=$(az acr show -n "$ACR_NAME" -g "$RG" \
  --subscription "$SUBSCRIPTION_ID" --query id -o tsv)
info "ACR ID: $ACR_ID"

# ── Storage Account ───────────────────────────────────────────────────────────
step "Storage Account: $STORAGE_NAME"
info "Checking existence..."
if az storage account show -n "$STORAGE_NAME" -g "$RG" \
    --subscription "$SUBSCRIPTION_ID" &>/dev/null; then
  skip "Storage Account $STORAGE_NAME"
else
  info "Creating storage account (Standard_LRS, no public blob access)..."
  az storage account create -n "$STORAGE_NAME" -g "$RG" -l "$LOCATION" \
    --subscription "$SUBSCRIPTION_ID" --sku Standard_LRS --allow-blob-public-access false
  ok "Storage Account created."
fi
STORAGE_ID=$(az storage account show -n "$STORAGE_NAME" -g "$RG" \
  --subscription "$SUBSCRIPTION_ID" --query id -o tsv)

step "Blob container: $CONTAINER"
info "Checking existence..."
if az storage container exists -n "$CONTAINER" --account-name "$STORAGE_NAME" \
    --subscription "$SUBSCRIPTION_ID" --auth-mode login \
    --query exists -o tsv 2>/dev/null | grep -q true; then
  skip "Blob container $CONTAINER"
else
  info "Creating blob container..."
  az storage container create -n "$CONTAINER" \
    --account-name "$STORAGE_NAME" --subscription "$SUBSCRIPTION_ID" --auth-mode login
  ok "Blob container created."
fi

# ── Container Apps Environment ────────────────────────────────────────────────
step "Container Apps Environment: $CA_ENV"
info "Checking existence..."
if az containerapp env show -n "$CA_ENV" -g "$RG" \
    --subscription "$SUBSCRIPTION_ID" &>/dev/null; then
  skip "Container Apps Environment $CA_ENV"
else
  info "Creating Container Apps Environment (this may take ~2 minutes)..."
  az containerapp env create -n "$CA_ENV" -g "$RG" -l "$LOCATION" \
    --subscription "$SUBSCRIPTION_ID" --logs-destination none
  ok "Container Apps Environment created."
fi

# ── Container App ─────────────────────────────────────────────────────────────
step "Container App: $CA_APP"
info "Checking existence..."
if az containerapp show -n "$CA_APP" -g "$RG" \
    --subscription "$SUBSCRIPTION_ID" &>/dev/null; then
  skip "Container App $CA_APP"
else
  info "Creating Container App with placeholder image..."
  az containerapp create -n "$CA_APP" -g "$RG" \
    --subscription "$SUBSCRIPTION_ID" \
    --environment "$CA_ENV" \
    --image "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest" \
    --system-assigned \
    --ingress external --target-port 8000 \
    --env-vars \
      MCP_TRANSPORT=http \
      AZURE_STORAGE_ACCOUNT="$STORAGE_NAME" \
      AZURE_STORAGE_CONTAINER="$CONTAINER" \
      AZURE_STORAGE_DB_BLOB=agent_telemetry.db \
      MCP_TENANT_ID="$TENANT_ID" \
      MCP_APP_ID_URI="$APP_ID_URI" \
      APP_INSIGHTS_CONN="$APP_INSIGHTS_CONN" \
      PORT=8000
  ok "Container App created."
fi

# ── Managed identity role assignments ─────────────────────────────────────────
step "Managed identity role assignments..."
info "Fetching Container App principal ID..."
PRINCIPAL_ID=$(az containerapp show -n "$CA_APP" -g "$RG" \
  --subscription "$SUBSCRIPTION_ID" --query identity.principalId -o tsv)
info "Principal ID: $PRINCIPAL_ID"

info "Checking AcrPull..."
if exists_role "$PRINCIPAL_ID" "AcrPull" "$ACR_ID"; then
  ok "AcrPull already assigned."
else
  az role assignment create --assignee "$PRINCIPAL_ID" \
    --role "AcrPull" --scope "$ACR_ID" --subscription "$SUBSCRIPTION_ID"
  ok "AcrPull assigned."
fi

info "Checking Storage Blob Data Reader..."
if exists_role "$PRINCIPAL_ID" "Storage Blob Data Reader" "$STORAGE_ID"; then
  ok "Storage Blob Data Reader already assigned."
else
  az role assignment create --assignee "$PRINCIPAL_ID" \
    --role "Storage Blob Data Reader" --scope "$STORAGE_ID" \
    --subscription "$SUBSCRIPTION_ID"
  ok "Storage Blob Data Reader assigned."
fi

step "Configuring ACR registry auth on Container App..."
az containerapp registry set -n "$CA_APP" -g "$RG" \
  --subscription "$SUBSCRIPTION_ID" \
  --server "${ACR_NAME}.azurecr.io" \
  --identity system
ok "ACR registry auth configured."

# ── Sync SP role assignments ──────────────────────────────────────────────────
if [ -n "${SYNC_SP_OBJECT_ID:-}" ]; then
  step "Sync SP role assignments (object ID: $SYNC_SP_OBJECT_ID)..."

  info "Checking Storage Blob Data Contributor..."
  if exists_role "$SYNC_SP_OBJECT_ID" "Storage Blob Data Contributor" "$STORAGE_ID"; then
    ok "Storage Blob Data Contributor already assigned."
  else
    az role assignment create --assignee "$SYNC_SP_OBJECT_ID" \
      --role "Storage Blob Data Contributor" --scope "$STORAGE_ID" \
      --subscription "$SUBSCRIPTION_ID"
    ok "Storage Blob Data Contributor assigned."
  fi

  if [ -n "${LAW_RESOURCE_ID:-}" ]; then
    info "Checking Log Analytics Reader..."
    if exists_role "$SYNC_SP_OBJECT_ID" "Log Analytics Reader" "$LAW_RESOURCE_ID"; then
      ok "Log Analytics Reader already assigned."
    else
      az role assignment create --assignee "$SYNC_SP_OBJECT_ID" \
        --role "Log Analytics Reader" --scope "$LAW_RESOURCE_ID" \
        --subscription "$SUBSCRIPTION_ID"
      ok "Log Analytics Reader assigned."
    fi
  else
    warn "LAW_RESOURCE_ID not set — skipping Log Analytics Reader assignment."
  fi
else
  warn "SYNC_SP_OBJECT_ID not set — skipping sync SP role assignments."
fi

# ── Done ──────────────────────────────────────────────────────────────────────
FQDN=$(az containerapp show -n "$CA_APP" -g "$RG" \
  --subscription "$SUBSCRIPTION_ID" \
  --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null || echo "<pending>")

echo ""
echo "======================================================"
echo "  [$(ts)] Phase 2 complete."
echo ""
echo "  MCP App Registration:  $APP_ID_URI"
echo "  MCP App ID:            $MCP_APP_ID"
echo "  MCP SSE endpoint:      https://${FQDN}/sse  (live after image deploy)"
echo "  ACR:                   ${ACR_NAME}.azurecr.io"
echo "  Storage:               $STORAGE_NAME / $CONTAINER"
echo ""
echo "  Next — push the real image:"
echo "    az acr build -r $ACR_NAME -t agenttele-mcp:latest ."
echo "    az containerapp update -n $CA_APP -g $RG \\"
echo "      --image ${ACR_NAME}.azurecr.io/agenttele-mcp:latest"
echo "======================================================"
