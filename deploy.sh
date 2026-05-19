#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Usage: bash deploy.sh <config-file>
# Example: bash deploy.sh deploy-config/yokiel.env
#          bash deploy.sh deploy-config/mwc.env
# ---------------------------------------------------------------------------

CONFIG="${1:-}"
if [ -z "$CONFIG" ]; then
  echo "Usage: bash deploy.sh <config-file>"
  echo "Available configs:"
  ls deploy-config/*.env 2>/dev/null | sed 's/^/  /'
  exit 1
fi

if [ ! -f "$CONFIG" ]; then
  echo "Error: config file not found: $CONFIG"
  exit 1
fi

# shellcheck source=/dev/null
source "$CONFIG"

# Clear any SP env vars that would override az CLI's interactive login credentials
unset AZURE_CLIENT_ID AZURE_CLIENT_SECRET AZURE_TENANT_ID AZURE_SUBSCRIPTION_ID

# Validate required vars
for VAR in TENANT_ID SUBSCRIPTION_ID RG LOCATION LA_WORKSPACE_CUSTOMER_ID ACR STORAGE; do
  if [ -z "${!VAR:-}" ]; then
    echo "Error: $VAR is not set in $CONFIG"
    exit 1
  fi
done

if [ -z "${SYNC_SP:-}" ]; then
  echo "Error: SYNC_SP is not set in $CONFIG"
  echo "Create an app registration in tenant $TENANT_ID first, then set SYNC_SP to its Application (client) ID."
  exit 1
fi

# Fixed names (resource-group scoped, safe to reuse across tenants)
CONTAINER="telemetry-data"
ENV="agent-telemetry-env"
APP="agent-telemetry-mcp"
MCP_APP_REG_NAME="agent-telemetry-mcp-server"
MCP_APP_ID_URI="api://${TENANT_ID}/agent-telemetry-mcp"

echo ""
echo "======================================================"
echo "  Deploying to tenant: $TENANT_ID"
echo "  Subscription:        $SUBSCRIPTION_ID"
echo "  Resource group:      $RG ($LOCATION)"
echo "======================================================"
echo ""

# Ensure we're targeting the right subscription
az account set --subscription "$SUBSCRIPTION_ID"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

exists_acr()           { az acr show -n "$1" -g "$RG" --subscription "$SUBSCRIPTION_ID" &>/dev/null; }
exists_appinsights()   { az monitor app-insights component show -g "$RG" -a "$1" --subscription "$SUBSCRIPTION_ID" &>/dev/null; }
exists_storage()       { az storage account show -n "$1" -g "$RG" --subscription "$SUBSCRIPTION_ID" &>/dev/null; }
exists_container()     { az storage container exists -n "$1" --account-name "$STORAGE" --subscription "$SUBSCRIPTION_ID" --auth-mode login --query exists -o tsv 2>/dev/null | grep -q true; }
exists_app_env()       { az containerapp env show -n "$1" -g "$RG" --subscription "$SUBSCRIPTION_ID" &>/dev/null; }
exists_containerapp()  { az containerapp show -n "$1" -g "$RG" --subscription "$SUBSCRIPTION_ID" &>/dev/null; }
exists_role()          { az role assignment list --assignee "$1" --role "$2" --scope "$3" --subscription "$SUBSCRIPTION_ID" --query "[0].id" -o tsv 2>/dev/null | grep -qv '^$'; }
provider_registered()  { az provider show -n "$1" --subscription "$SUBSCRIPTION_ID" --query "registrationState" -o tsv 2>/dev/null | grep -q "Registered"; }

# ---------------------------------------------------------------------------
# 0. Resource providers
# ---------------------------------------------------------------------------

echo "==> Checking resource providers..."
for NS in Microsoft.ContainerRegistry Microsoft.App Microsoft.OperationalInsights Microsoft.Storage Microsoft.Insights; do
  if provider_registered "$NS"; then
    echo "    $NS already registered."
  else
    echo "    Registering $NS..."
    az provider register --namespace "$NS" --subscription "$SUBSCRIPTION_ID" --wait
  fi
done

# ---------------------------------------------------------------------------
# 1. Container Registry
# ---------------------------------------------------------------------------

echo "==> Container Registry..."
if exists_acr "$ACR"; then
  echo "    $ACR already exists, skipping create."
else
  az acr create -g "$RG" -n "$ACR" --subscription "$SUBSCRIPTION_ID" --sku Basic --admin-enabled false
fi

# ---------------------------------------------------------------------------
# 2. Application Insights (workspace-based, backed by the Log Analytics workspace)
# ---------------------------------------------------------------------------

APP_INSIGHTS_NAME="appinsights-agent-telemetry"
echo "==> Application Insights..."
if exists_appinsights "$APP_INSIGHTS_NAME"; then
  echo "    $APP_INSIGHTS_NAME already exists, skipping create."
else
  LA_RESOURCE_ID_EARLY=$(az monitor log-analytics workspace list \
    --subscription "$SUBSCRIPTION_ID" \
    --query "[?customerId=='$LA_WORKSPACE_CUSTOMER_ID'].id" -o tsv)
  if [ -z "$LA_RESOURCE_ID_EARLY" ]; then
    echo "    WARNING: Log Analytics workspace not found — skipping Application Insights create."
  else
    az monitor app-insights component create \
      -g "$RG" -a "$APP_INSIGHTS_NAME" -l "$LOCATION" \
      --subscription "$SUBSCRIPTION_ID" \
      --workspace "$LA_RESOURCE_ID_EARLY" \
      --application-type web
    echo "    Created $APP_INSIGHTS_NAME linked to Log Analytics workspace."
  fi
fi

APP_INSIGHTS_CONN=$(az monitor app-insights component show \
  -g "$RG" -a "$APP_INSIGHTS_NAME" --subscription "$SUBSCRIPTION_ID" \
  --query connectionString -o tsv 2>/dev/null || true)

# ---------------------------------------------------------------------------
# 3. Storage Account + Blob container
# ---------------------------------------------------------------------------

echo "==> Storage Account..."
if exists_storage "$STORAGE"; then
  echo "    $STORAGE already exists, skipping create."
else
  az storage account create -n "$STORAGE" -g "$RG" -l "$LOCATION" \
    --subscription "$SUBSCRIPTION_ID" --sku Standard_LRS --allow-blob-public-access false
fi

echo "==> Blob container..."
if exists_container "$CONTAINER"; then
  echo "    $CONTAINER already exists, skipping create."
else
  az storage container create -n "$CONTAINER" --account-name "$STORAGE" --subscription "$SUBSCRIPTION_ID" --auth-mode login
fi

# ---------------------------------------------------------------------------
# 3. App Registration for MCP server
# ---------------------------------------------------------------------------

echo "==> App Registration..."
MCP_APP_ID=$(az ad app list --display-name "$MCP_APP_REG_NAME" --query "[0].appId" -o tsv 2>/dev/null || true)

if [ -n "$MCP_APP_ID" ]; then
  echo "    $MCP_APP_REG_NAME already exists (appId: $MCP_APP_ID)."
  _APP_REG_OK=1
else
  if MCP_APP_ID=$(az ad app create --display-name "$MCP_APP_REG_NAME" --query appId -o tsv 2>/dev/null); then
    echo "    Created app registration. App ID: $MCP_APP_ID"
    _APP_REG_OK=1
  else
    echo "    WARNING: Insufficient directory permissions to create app registration."
    echo "    Skipping Entra ID app registration — MCP server will use key-based auth only."
    MCP_APP_ID=""
    _APP_REG_OK=0
  fi
fi

if [ "${_APP_REG_OK:-0}" = "1" ] && [ -n "$MCP_APP_ID" ]; then
  echo "    Setting App ID URI..."
  az ad app update --id "$MCP_APP_ID" --identifier-uris "$MCP_APP_ID_URI"

  echo "    Ensuring Telemetry.Read scope..."
  EXISTING_SCOPE=$(az ad app show --id "$MCP_APP_ID" \
    --query "api.oauth2PermissionScopes[?value=='Telemetry.Read'].id" -o tsv 2>/dev/null || true)
  if [ -z "$EXISTING_SCOPE" ]; then
    SCOPE_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
    az ad app update --id "$MCP_APP_ID" --set \
      "api={\"oauth2PermissionScopes\":[{\"adminConsentDescription\":\"Read agent telemetry data\",\"adminConsentDisplayName\":\"Read telemetry\",\"id\":\"$SCOPE_ID\",\"isEnabled\":true,\"type\":\"User\",\"userConsentDescription\":\"Read agent telemetry data\",\"userConsentDisplayName\":\"Read telemetry\",\"value\":\"Telemetry.Read\"}]}"
  else
    echo "    Telemetry.Read scope already present."
  fi

  echo "    Ensuring Telemetry.Data.Read app role..."
  EXISTING_ROLE=$(az ad app show --id "$MCP_APP_ID" \
    --query "appRoles[?value=='Telemetry.Data.Read'].id" -o tsv 2>/dev/null || true)
  if [ -z "$EXISTING_ROLE" ]; then
    ROLE_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
    az ad app update --id "$MCP_APP_ID" --set \
      "appRoles=[{\"allowedMemberTypes\":[\"Application\"],\"description\":\"Read agent telemetry data\",\"displayName\":\"Telemetry Read\",\"id\":\"$ROLE_ID\",\"isEnabled\":true,\"value\":\"Telemetry.Data.Read\"}]"
  else
    echo "    Telemetry.Data.Read app role already present."
  fi

  az ad sp create --id "$MCP_APP_ID" 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# 4. Log Analytics IAM for sync SP
# ---------------------------------------------------------------------------

echo "==> Log Analytics IAM..."
LA_RESOURCE_ID=$(az monitor log-analytics workspace list \
  --subscription "$SUBSCRIPTION_ID" \
  --query "[?customerId=='$LA_WORKSPACE_CUSTOMER_ID'].id" -o tsv)

if [ -z "$LA_RESOURCE_ID" ]; then
  echo "    WARNING: Workspace $LA_WORKSPACE_CUSTOMER_ID not found. Skipping IAM steps."
else
  echo "    Workspace: $LA_RESOURCE_ID"

  if exists_role "$SYNC_SP" "Log Analytics Reader" "$LA_RESOURCE_ID"; then
    echo "    Log Analytics Reader role already assigned."
  else
    echo "    Assigning Log Analytics Reader role..."
    az role assignment create --assignee "$SYNC_SP" \
      --role "Log Analytics Reader" --scope "$LA_RESOURCE_ID" --subscription "$SUBSCRIPTION_ID"
  fi

  LA_API_APP_ID="ca7f3f0b-7d91-482c-8e09-c5d840d0eac5"
  EXISTING_PERM=$(az ad app permission list --id "$SYNC_SP" \
    --query "[?resourceAppId=='$LA_API_APP_ID'].resourceAppId" -o tsv 2>/dev/null || true)

  if [ -n "$EXISTING_PERM" ]; then
    echo "    Log Analytics Data.Read permission already added."
  else
    echo "    Adding Log Analytics Data.Read permission..."
    LA_DATA_READ_ID=$(az ad sp show --id "$LA_API_APP_ID" \
      --query "appRoles[?value=='Data.Read'].id" -o tsv)
    az ad app permission add --id "$SYNC_SP" \
      --api "$LA_API_APP_ID" --api-permissions "${LA_DATA_READ_ID}=Role"
    az ad app permission admin-consent --id "$SYNC_SP"
  fi
fi

# ---------------------------------------------------------------------------
# 5. Container Apps environment + app
# ---------------------------------------------------------------------------

echo "==> Container Apps environment..."
if exists_app_env "$ENV"; then
  echo "    $ENV already exists, skipping create."
else
  az containerapp env create -n "$ENV" -g "$RG" -l "$LOCATION" --subscription "$SUBSCRIPTION_ID" --logs-destination none
fi

echo "==> Container App..."
ACR_ID=$(az acr show -n "$ACR" -g "$RG" --subscription "$SUBSCRIPTION_ID" --query id -o tsv)

if ! exists_containerapp "$APP"; then
  echo "    Creating Container App (placeholder image)..."
  az containerapp create -n "$APP" -g "$RG" --subscription "$SUBSCRIPTION_ID" \
    --environment "$ENV" \
    --image "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest" \
    --system-assigned \
    --ingress external --target-port 8000 \
    --env-vars \
      MCP_TRANSPORT=http \
      AZURE_STORAGE_ACCOUNT="$STORAGE" \
      AZURE_STORAGE_CONTAINER="$CONTAINER" \
      AZURE_STORAGE_DB_BLOB=agent_telemetry.db \
      MCP_TENANT_ID="$TENANT_ID" \
      MCP_APP_ID_URI="$MCP_APP_ID_URI" \
      PORT=8000
fi

echo "    Ensuring AcrPull role for managed identity..."
PRINCIPAL=$(az containerapp show -n "$APP" -g "$RG" --subscription "$SUBSCRIPTION_ID" --query identity.principalId -o tsv)
if exists_role "$PRINCIPAL" "AcrPull" "$ACR_ID"; then
  echo "    AcrPull already assigned."
else
  az role assignment create --assignee "$PRINCIPAL" --role AcrPull --scope "$ACR_ID" --subscription "$SUBSCRIPTION_ID"
fi

echo "    Configuring ACR registry auth..."
az containerapp registry set -n "$APP" -g "$RG" --subscription "$SUBSCRIPTION_ID" \
  --server "${ACR}.azurecr.io" \
  --identity system

echo "==> Building and pushing image..."
cd "$(dirname "$0")"
az acr build -r "$ACR" --subscription "$SUBSCRIPTION_ID" -t "${APP}:latest" \
  --build-arg "PYTHON_IMAGE=${ACR}.azurecr.io/python:3.12-slim" .
az account set --subscription "$SUBSCRIPTION_ID"

echo "    Updating to real image from ACR..."
az containerapp update -n "$APP" -g "$RG" --subscription "$SUBSCRIPTION_ID" \
  --image "${ACR}.azurecr.io/${APP}:latest" \
  --revision-suffix "v$(date +%s)"

# ---------------------------------------------------------------------------
# 6. Role assignments for blob storage
# ---------------------------------------------------------------------------

echo "==> Blob storage role assignments..."
PRINCIPAL=$(az containerapp show -n "$APP" -g "$RG" --subscription "$SUBSCRIPTION_ID" --query identity.principalId -o tsv)
STORAGE_RESOURCE_ID=$(az storage account show -n "$STORAGE" -g "$RG" --subscription "$SUBSCRIPTION_ID" --query id -o tsv)

if exists_role "$PRINCIPAL" "Storage Blob Data Reader" "$STORAGE_RESOURCE_ID"; then
  echo "    Managed identity Storage Blob Data Reader already assigned."
else
  az role assignment create --assignee "$PRINCIPAL" --subscription "$SUBSCRIPTION_ID" \
    --role "Storage Blob Data Reader" --scope "$STORAGE_RESOURCE_ID"
fi

if [ -n "${SYNC_SP:-}" ]; then
  if exists_role "$SYNC_SP" "Storage Blob Data Contributor" "$STORAGE_RESOURCE_ID"; then
    echo "    Sync SP Storage Blob Data Contributor already assigned."
  else
    az role assignment create --assignee "$SYNC_SP" --subscription "$SUBSCRIPTION_ID" \
      --role "Storage Blob Data Contributor" --scope "$STORAGE_RESOURCE_ID"
  fi
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

FQDN=$(az containerapp show -n "$APP" -g "$RG" --subscription "$SUBSCRIPTION_ID" \
  --query properties.configuration.ingress.fqdn -o tsv)

echo ""
echo "======================================================"
echo "  Deployment complete!"
echo ""
echo "  MCP SSE endpoint:         https://${FQDN}/sse"
echo "  MCP App Registration:     $MCP_APP_ID_URI"
echo "  MCP App ID:               $MCP_APP_ID"
echo ""
echo "  App Insights connection string (configure your agent to write telemetry here):"
echo "  ${APP_INSIGHTS_CONN}"
echo "======================================================"
