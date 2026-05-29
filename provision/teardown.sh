#!/usr/bin/env bash
# provision/teardown.sh
# ─────────────────────────────────────────────────────────────────────────────
# Removes the resources created by the original deploy.sh.
# Does NOT touch the resource group, Log Analytics workspace, or any
# pre-existing infrastructure.
#
# Run in Azure Cloud Shell:
#   bash teardown.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── CONFIG — fill in before running ──────────────────────────────────────────
SUBSCRIPTION_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
RG="your-resource-group"
ACR="agenttelemetrymwccr"
STORAGE="stagenttelemetrymwc"
# ─────────────────────────────────────────────────────────────────────────────

ts() { date "+%H:%M:%S"; }
step() { echo ""; echo "[$(ts)] ── $*"; }
info() { echo "          $*"; }
ok()   { echo "  [$(ts)] ✓  $*"; }
skip() { echo "  [$(ts)] –  $* — not found, skipping."; }

# Validate
for VAR in SUBSCRIPTION_ID RG ACR STORAGE; do
  if [ -z "${!VAR:-}" ]; then
    echo "ERROR: $VAR is not set. Edit the CONFIG section at the top of this script."
    exit 1
  fi
done

echo ""
echo "======================================================"
echo "  TEARDOWN — subscription: $SUBSCRIPTION_ID"
echo "  Resource group:          $RG"
echo "======================================================"
echo ""
echo "  The following resources will be deleted: (10-20min)"
echo "    • Container App:         agent-telemetry-mcp"
echo "    • Container Apps Env:    agent-telemetry-env"
echo "    • Application Insights:  appinsights-agent-telemetry"
echo "    • ACR:                   $ACR"
echo "    • Storage Account:       $STORAGE"
echo "    • App Registration:      agent-telemetry-mcp-server"
echo ""
read -r -p "  Type 'yes' to confirm: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "  Aborted."
  exit 0
fi

step "Setting subscription..."
az account set --subscription "$SUBSCRIPTION_ID"
ok "Subscription set."

# ── Container App ─────────────────────────────────────────────────────────────
step "Container App: agent-telemetry-mcp"
info "Checking existence..."
if az containerapp show -n "agent-telemetry-mcp" -g "$RG" \
    --subscription "$SUBSCRIPTION_ID" &>/dev/null; then
  info "Found — deleting (this may take ~60 seconds)..."
  az containerapp delete -n "agent-telemetry-mcp" -g "$RG" \
    --subscription "$SUBSCRIPTION_ID" --yes
  ok "Container App deleted."
else
  skip "Container App"
fi

# ── Container Apps Environment ────────────────────────────────────────────────
step "Container Apps Environment: agent-telemetry-env"
info "Checking existence..."
if az containerapp env show -n "agent-telemetry-env" -g "$RG" \
    --subscription "$SUBSCRIPTION_ID" &>/dev/null; then
  info "Found — deleting (this may take ~90 seconds)..."
  az containerapp env delete -n "agent-telemetry-env" -g "$RG" \
    --subscription "$SUBSCRIPTION_ID" --yes
  ok "Container Apps Environment deleted."
else
  skip "Container Apps Environment"
fi

# ── Application Insights ──────────────────────────────────────────────────────
step "Application Insights: appinsights-agent-telemetry"
info "Checking existence..."
if az monitor app-insights component show -g "$RG" -a "appinsights-agent-telemetry" \
    --subscription "$SUBSCRIPTION_ID" &>/dev/null; then
  info "Found — deleting..."
  az monitor app-insights component delete -g "$RG" -a "appinsights-agent-telemetry" \
    --subscription "$SUBSCRIPTION_ID" --yes
  ok "Application Insights deleted."
else
  skip "Application Insights"
fi

# ── ACR ───────────────────────────────────────────────────────────────────────
step "Container Registry: $ACR"
info "Checking existence..."
if az acr show -n "$ACR" -g "$RG" --subscription "$SUBSCRIPTION_ID" &>/dev/null; then
  info "Found — deleting (purges all images)..."
  az acr delete -n "$ACR" -g "$RG" --subscription "$SUBSCRIPTION_ID" --yes
  ok "ACR deleted."
else
  skip "ACR"
fi

# ── Storage Account ───────────────────────────────────────────────────────────
step "Storage Account: $STORAGE"
info "Checking existence..."
if az storage account show -n "$STORAGE" -g "$RG" \
    --subscription "$SUBSCRIPTION_ID" &>/dev/null; then
  info "Found — deleting (purges all blobs including telemetry DB)..."
  az storage account delete -n "$STORAGE" -g "$RG" \
    --subscription "$SUBSCRIPTION_ID" --yes
  ok "Storage Account deleted."
else
  skip "Storage Account"
fi

# ── App Registration ──────────────────────────────────────────────────────────
step "App Registration: agent-telemetry-mcp-server"
info "Looking up app ID..."
APP_ID=$(az ad app list --display-name "agent-telemetry-mcp-server" \
  --query "[0].appId" -o tsv 2>/dev/null || true)
if [ -n "$APP_ID" ]; then
  info "Found (appId: $APP_ID) — deleting..."
  az ad app delete --id "$APP_ID"
  ok "App Registration deleted."
else
  skip "App Registration"
fi

echo ""
echo "======================================================"
echo "  [$(ts)] Teardown complete."
echo "======================================================"
