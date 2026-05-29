#!/usr/bin/env bash
# provision/step2_identity.sh
# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Identity Permissions + Validation
#
# Grants the agent-telemetry-poc service principal all read permissions
# required to collect telemetry data across:
#   • Microsoft 365 usage reports (Copilot, Teams, Exchange, SharePoint)
#   • Viva Insights / MyAnalytics organisational analytics
#   • Power Platform environments, bots, DLP policies (via Dataverse & BAP API)
#   • User & directory data, audit logs
#   • Office 365 activity feeds
#
# What this script does:
#   1. Adds Microsoft Graph application permissions (read-only)
#   2. Adds Office 365 Management API permission
#   3. Adds Dynamics CRM delegated permission (for Dataverse access)
#   4. Grants tenant-wide admin consent for all permissions
#   5. Assigns the 'Power Platform Administrator' Entra directory role
#   6. Validates all permissions by calling each API surface as the SP
#
# Required admin role to run this script:
#   • Global Administrator   (can do all steps)
#   — OR —
#   • Privileged Role Administrator  (for step 5 — directory role assignment)
#   • Application Administrator      (for steps 1-4 — permissions & consent)
#
# Run in Azure Cloud Shell:
#   bash step2_identity.sh
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail   # -e removed: we track failures explicitly so the script never silently exits

# ── CONFIG ────────────────────────────────────────────────────────────────────
# App Name: agent-telemetry-poc
APP_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
TENANT_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

# Client secret — required for live API validation tests in Part 2.
# Leave blank to skip live tests and only validate configuration.
CLIENT_SECRET="REDACTED"

# Dataverse org URL — used to test Dynamics CRM / Power Platform access.
# From your .env: DATAVERSE_URL
DATAVERSE_URL="https://your-org.crm.dynamics.com"
# ─────────────────────────────────────────────────────────────────────────────

PROVISION_ERRORS=0   # Part 1 hard failures — permissions couldn't be added
MANUAL_ACTIONS=0     # Part 2 items that need manual follow-up before step 3

ts()     { date "+%H:%M:%S"; }
step()   { echo ""; echo "[$(ts)] ── $*"; }
info()   { echo "          $*"; }
ok()     { echo "  [$(ts)] ✓  $*"; }
fail()   { echo "  [$(ts)] ✗  $*"; PROVISION_ERRORS=$((PROVISION_ERRORS + 1)); }
warn()   { echo "  [$(ts)] !  $*"; }
action() { echo "  [$(ts)] ►  ACTION NEEDED: $*"; MANUAL_ACTIONS=$((MANUAL_ACTIONS + 1)); }
skip()   { echo "  [$(ts)] –  $*"; }

GRAPH_APP="00000003-0000-0000-c000-000000000000"
CRM_APP="00000007-0000-0000-c000-000000000000"
O365_MGMT_APP="c5393580-f805-4401-95e8-94b7a6ef2fc2"
PP_ADMIN_TEMPLATE_ID="11648597-926c-4cf3-9c36-bcebb0ba8dcc"
BAP_BASE="https://api.bap.microsoft.com"

for VAR in APP_ID TENANT_ID; do
  if [ -z "${!VAR:-}" ]; then
    echo "ERROR: $VAR is not set."
    exit 1
  fi
done

echo ""
echo "======================================================"
echo "  Step 2 — Identity Permissions + Validation"
echo "  App:    agent-telemetry-poc"
echo "  App ID: $APP_ID"
echo "  Tenant: $TENANT_ID"
if [ -n "$CLIENT_SECRET" ]; then
  echo "  Mode:   Full validation (live API tests enabled)"
else
  echo "  Mode:   Config validation only (set CLIENT_SECRET for live API tests)"
fi
echo "======================================================"
echo ""
echo "  Permissions to be granted:"
echo "    Microsoft Graph (application):"
echo "      • Reports.Read.All          — M365 usage + Copilot usage reports"
echo "      • ReportSettings.Read.All   — un-obfuscated user names in reports"
echo "      • Analytics.ReadAll         — Viva Insights org analytics"
echo "      • User.Read.All             — user directory"
echo "      • Directory.Read.All        — tenant directory"
echo "      • AuditLog.Read.All         — sign-in & audit logs"
echo "    Office 365 Management (application):"
echo "      • ActivityFeed.Read         — Power Platform & M365 activity events"
echo "    Dynamics CRM (delegated):"
echo "      • user_impersonation        — Dataverse / Power Platform per-env access"
echo "    Entra directory role:"
echo "      • Power Platform Administrator — BAP Admin API (environments, DLP)"
echo ""
read -r -p "  Type 'yes' to proceed: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "  Aborted."
  exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
# PART 1 — Grant permissions
# ─────────────────────────────────────────────────────────────────────────────

step "Resolving service principal object ID..."
SP_OBJECT_ID=$(az ad sp show --id "$APP_ID" --query id -o tsv 2>/dev/null || true)
if [ -z "$SP_OBJECT_ID" ]; then
  info "Service principal not found — creating..."
  az ad sp create --id "$APP_ID"
  SP_OBJECT_ID=$(az ad sp show --id "$APP_ID" --query id -o tsv)
fi
ok "Object ID: $SP_OBJECT_ID"

get_app_role()   { az ad sp show --id "$1" --query "appRoles[?value=='$2'].id" -o tsv 2>/dev/null || true; }
get_oauth_scope(){ az ad sp show --id "$1" --query "oauth2PermissionScopes[?value=='$2'].id" -o tsv 2>/dev/null || true; }

# Returns 0 (true) if the permission ID is already registered on the app
perm_exists() {
  local API_ID="$1" PERM_ID="$2"
  az ad app permission list --id "$APP_ID" \
    --query "[?resourceAppId=='${API_ID}'].resourceAccess[].id" \
    -o tsv 2>/dev/null | grep -qF "$PERM_ID"
}

step "Resolving permission IDs from tenant..."
info "Graph: Reports.Read.All..."
PERM_REPORTS=$(get_app_role "$GRAPH_APP" "Reports.Read.All")
info "Graph: ReportSettings.Read.All..."
PERM_REPORT_SETTINGS=$(get_app_role "$GRAPH_APP" "ReportSettings.Read.All")
info "Graph: Analytics.ReadAll..."
PERM_ANALYTICS=$(get_app_role "$GRAPH_APP" "Analytics.ReadAll")
info "Graph: User.Read.All..."
PERM_USER=$(get_app_role "$GRAPH_APP" "User.Read.All")
info "Graph: Directory.Read.All..."
PERM_DIR=$(get_app_role "$GRAPH_APP" "Directory.Read.All")
info "Graph: AuditLog.Read.All..."
PERM_AUDIT=$(get_app_role "$GRAPH_APP" "AuditLog.Read.All")
info "O365 Management: ActivityFeed.Read..."
PERM_ACTIVITY=$(get_app_role "$O365_MGMT_APP" "ActivityFeed.Read")
info "Dynamics CRM: user_impersonation..."
PERM_CRM=$(get_oauth_scope "$CRM_APP" "user_impersonation")

echo ""
echo "          Resolved:"
printf "            %-32s %s\n" "Reports.Read.All:"        "${PERM_REPORTS:-NOT FOUND}"
printf "            %-32s %s\n" "ReportSettings.Read.All:" "${PERM_REPORT_SETTINGS:-NOT FOUND}"
printf "            %-32s %s\n" "Analytics.ReadAll:"        "${PERM_ANALYTICS:-NOT FOUND}"
printf "            %-32s %s\n" "User.Read.All:"            "${PERM_USER:-NOT FOUND}"
printf "            %-32s %s\n" "Directory.Read.All:"       "${PERM_DIR:-NOT FOUND}"
printf "            %-32s %s\n" "AuditLog.Read.All:"        "${PERM_AUDIT:-NOT FOUND}"
printf "            %-32s %s\n" "ActivityFeed.Read:"        "${PERM_ACTIVITY:-NOT FOUND}"
printf "            %-32s %s\n" "CRM user_impersonation:"   "${PERM_CRM:-NOT FOUND}"

step "Adding Microsoft Graph permissions..."
GRAPH_PERMS=""
declare -A GRAPH_PERM_NAMES
GRAPH_PERM_NAMES["$PERM_REPORTS"]="Reports.Read.All"
GRAPH_PERM_NAMES["$PERM_REPORT_SETTINGS"]="ReportSettings.Read.All"
GRAPH_PERM_NAMES["$PERM_USER"]="User.Read.All"
GRAPH_PERM_NAMES["$PERM_DIR"]="Directory.Read.All"
GRAPH_PERM_NAMES["$PERM_AUDIT"]="AuditLog.Read.All"
[ -n "${PERM_ANALYTICS:-}" ] && GRAPH_PERM_NAMES["$PERM_ANALYTICS"]="Analytics.ReadAll"

for PERM_ID in "${!GRAPH_PERM_NAMES[@]}"; do
  NAME="${GRAPH_PERM_NAMES[$PERM_ID]}"
  if [ -z "$PERM_ID" ]; then
    warn "$NAME — permission ID not found in tenant, skipping."
  elif perm_exists "$GRAPH_APP" "$PERM_ID"; then
    skip "$NAME already on app."
  else
    GRAPH_PERMS="$GRAPH_PERMS ${PERM_ID}=Role"
    info "$NAME — queued to add."
  fi
done

if [ -n "$GRAPH_PERMS" ]; then
  # shellcheck disable=SC2086
  az ad app permission add --id "$APP_ID" --api "$GRAPH_APP" \
    --api-permissions $GRAPH_PERMS 2>/dev/null || true
  ok "Graph permissions added."
else
  ok "All Graph permissions already present."
fi

step "Adding Office 365 Management permission..."
if [ -z "${PERM_ACTIVITY:-}" ]; then
  warn "ActivityFeed.Read — permission ID not found in tenant, skipping."
elif perm_exists "$O365_MGMT_APP" "$PERM_ACTIVITY"; then
  skip "ActivityFeed.Read already on app."
else
  az ad app permission add --id "$APP_ID" --api "$O365_MGMT_APP" \
    --api-permissions "${PERM_ACTIVITY}=Role" 2>/dev/null || true
  ok "ActivityFeed.Read added."
fi

step "Adding Dynamics CRM permission..."
if [ -z "${PERM_CRM:-}" ]; then
  warn "user_impersonation — CRM SP not found in tenant, skipping."
elif perm_exists "$CRM_APP" "$PERM_CRM"; then
  skip "Dynamics CRM user_impersonation already on app."
else
  az ad app permission add --id "$APP_ID" --api "$CRM_APP" \
    --api-permissions "${PERM_CRM}=Scope" 2>/dev/null || true
  ok "Dynamics CRM user_impersonation added."
fi

step "Granting tenant-wide admin consent..."
info "Checking if consent is already granted..."
CONSENTED_COUNT=$(az rest --method GET \
  --url "https://graph.microsoft.com/v1.0/servicePrincipals/${SP_OBJECT_ID}/appRoleAssignments" \
  --query "length(value)" -o tsv 2>/dev/null || echo "0")

if [ "${CONSENTED_COUNT:-0}" -gt "0" ]; then
  ok "Admin consent already granted ($CONSENTED_COUNT role assignment(s) active) — skipping."
else
  info "No existing consent found — attempting to grant..."
  if az ad app permission admin-consent --id "$APP_ID" 2>&1; then
    ok "Admin consent granted."
  else
    warn "Admin consent failed (requires Global Administrator)."
    warn "Grant manually: Entra ID → App registrations → agent-telemetry-poc → API permissions → Grant admin consent"
  fi
fi

step "Assigning 'Power Platform Administrator' Entra directory role..."
info "Checking if role is activated in directory..."
ROLE_ID=$(az rest --method GET \
  --url "https://graph.microsoft.com/v1.0/directoryRoles" \
  --query "value[?roleTemplateId=='${PP_ADMIN_TEMPLATE_ID}'].id" -o tsv 2>/dev/null || true)

if [ -z "$ROLE_ID" ]; then
  info "Activating role in directory..."
  az rest --method POST \
    --url "https://graph.microsoft.com/v1.0/directoryRoles" \
    --headers "Content-Type=application/json" \
    --body "{\"roleTemplateId\": \"${PP_ADMIN_TEMPLATE_ID}\"}" > /dev/null 2>&1 || true
  ROLE_ID=$(az rest --method GET \
    --url "https://graph.microsoft.com/v1.0/directoryRoles" \
    --query "value[?roleTemplateId=='${PP_ADMIN_TEMPLATE_ID}'].id" -o tsv 2>/dev/null || true)
  [ -n "$ROLE_ID" ] && ok "Role activated." || warn "Could not activate role — may need Privileged Role Administrator."
else
  ok "Role already active."
fi

info "Checking existing membership..."
EXISTING_MEMBER=""
if [ -n "$ROLE_ID" ]; then
  EXISTING_MEMBER=$(az rest --method GET \
    --url "https://graph.microsoft.com/v1.0/directoryRoles/${ROLE_ID}/members" \
    --query "value[?id=='${SP_OBJECT_ID}'].id" -o tsv 2>/dev/null || true)
fi

if [ -n "$EXISTING_MEMBER" ]; then
  ok "Power Platform Administrator already assigned — skipping."
elif [ -z "$ROLE_ID" ]; then
  warn "Skipping role assignment — role ID could not be resolved (see above)."
else
  info "Not yet assigned — attempting to add..."
  if az rest --method POST \
      --url "https://graph.microsoft.com/v1.0/directoryRoles/${ROLE_ID}/members/\$ref" \
      --headers "Content-Type=application/json" \
      --body "{\"@odata.id\": \"https://graph.microsoft.com/v1.0/directoryObjects/${SP_OBJECT_ID}\"}" 2>&1; then
    ok "Power Platform Administrator role assigned."
  else
    warn "Role assignment failed — requires Privileged Role Administrator."
    warn "Assign manually: Entra ID → Roles and administrators → Power Platform Administrator → Add assignments → select the SP."
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# PART 2 — Validate
# ─────────────────────────────────────────────────────────────────────────────

echo ""
echo "======================================================"
echo "  [$(ts)] Part 2 — Validation"
echo "======================================================"

# ── Helper: acquire token via client credentials ──────────────────────────────
get_token() {
  local RESOURCE="$1"
  local SCOPE="${RESOURCE}/.default"
  curl -s -X POST \
    "https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/token" \
    -d "client_id=${APP_ID}&client_secret=${CLIENT_SECRET}&grant_type=client_credentials&scope=${SCOPE}" \
    | python3 -c "
import sys, json
d = json.load(sys.stdin)
t = d.get('access_token', '')
if not t:
    print('ERROR:' + d.get('error_description', str(d)), file=sys.stderr)
print(t)
"
}

# ── Helper: HTTP GET with bearer token ───────────────────────────────────────
api_get() {
  local URL="$1"
  local TOKEN="$2"
  curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Accept: application/json" \
    "$URL"
}

# ── Config checks (always run) ────────────────────────────────────────────────
step "Config validation — checking permissions are registered..."

CONSENT_COUNT=$(az ad app permission list --id "$APP_ID" \
  --query "length([*])" -o tsv 2>/dev/null || echo "0")
if [ "$CONSENT_COUNT" -gt "0" ]; then
  ok "$CONSENT_COUNT API permission entr(ies) registered on the app."
else
  fail "No permissions found on app registration — check Part 1 completed."
fi

info "Checking Power Platform Administrator role membership..."
MEMBER_CHECK=$(az rest --method GET \
  --url "https://graph.microsoft.com/v1.0/directoryRoles/${ROLE_ID}/members" \
  --query "value[?id=='${SP_OBJECT_ID}'].id" -o tsv 2>/dev/null || true)
if [ -n "$MEMBER_CHECK" ]; then
  ok "Power Platform Administrator role confirmed."
else
  action "SP is NOT in Power Platform Administrator role. Assign manually:"
  action "  Entra ID → Roles and administrators → Power Platform Administrator → Add assignments"
  action "  SP object ID: $SP_OBJECT_ID"
fi

# ── Live API tests (only if CLIENT_SECRET is set) ────────────────────────────
if [ -z "${CLIENT_SECRET:-}" ]; then
  echo ""
  warn "CLIENT_SECRET not set — skipping live API tests."
  warn "Set CLIENT_SECRET at the top of this script and re-run to validate"
  warn "that tokens are issued and each API surface returns 200."
else
  step "Live API tests — acquiring tokens and calling each surface..."

  # Microsoft Graph
  info "Acquiring Microsoft Graph token..."
  GRAPH_TOKEN=$(get_token "https://graph.microsoft.com")
  if [ -z "$GRAPH_TOKEN" ] || [[ "$GRAPH_TOKEN" == ERROR:* ]]; then
    fail "Graph token acquisition failed: $GRAPH_TOKEN"
  else
    ok "Graph token acquired."

    info "Testing Reports.Read.All — M365 usage report..."
    STATUS=$(api_get "https://graph.microsoft.com/v1.0/reports/getOffice365ActiveUserCounts(period='D7')" "$GRAPH_TOKEN")
    case "$STATUS" in
      200) ok  "Reports.Read.All: HTTP $STATUS" ;;
      302) action "Reports.Read.All: HTTP 302 — admin consent not yet applied. Grant consent in Entra portal then re-run." ;;
      403) action "Reports.Read.All: HTTP 403 — permission missing or consent denied. Check app registration." ;;
      *)   fail  "Reports.Read.All: HTTP $STATUS (unexpected)" ;;
    esac

    info "Testing User.Read.All — list one user..."
    STATUS=$(api_get "https://graph.microsoft.com/v1.0/users?\$top=1&\$select=id" "$GRAPH_TOKEN")
    [ "$STATUS" = "200" ] && ok "User.Read.All: HTTP $STATUS" || fail "User.Read.All: HTTP $STATUS"

    info "Testing Directory.Read.All — list organisation..."
    STATUS=$(api_get "https://graph.microsoft.com/v1.0/organization?\$select=id" "$GRAPH_TOKEN")
    [ "$STATUS" = "200" ] && ok "Directory.Read.All: HTTP $STATUS" || fail "Directory.Read.All: HTTP $STATUS"

    info "Testing Analytics.ReadAll — Viva Insights..."
    if [ -z "${PERM_ANALYTICS:-}" ]; then
      warn "Analytics.ReadAll — permission not found in this tenant's Graph SP; Viva Insights org analytics may not be available."
    else
      STATUS=$(api_get "https://graph.microsoft.com/v1.0/analytics/activityStatistics" "$GRAPH_TOKEN")
      case "$STATUS" in
        200|404) ok   "Analytics.ReadAll: HTTP $STATUS (404 = no data yet, permission OK)" ;;
        302)     warn "Analytics.ReadAll: HTTP 302 — consent pending." ;;
        *)       fail "Analytics.ReadAll: HTTP $STATUS" ;;
      esac
    fi
  fi

  # BAP Admin API (Power Platform environments)
  info "Acquiring BAP Admin API token..."
  BAP_TOKEN=$(get_token "https://api.bap.microsoft.com")
  if [ -z "$BAP_TOKEN" ] || [[ "$BAP_TOKEN" == ERROR:* ]]; then
    fail "BAP token acquisition failed: $BAP_TOKEN"
  else
    ok "BAP token acquired."
    info "Testing Power Platform environment listing..."
    STATUS=$(api_get "${BAP_BASE}/providers/Microsoft.BusinessAppPlatform/scopes/admin/environments?api-version=2021-04-01" "$BAP_TOKEN")
    if [ "$STATUS" = "200" ]; then
      ok "BAP environments: HTTP $STATUS"
    elif [ "$STATUS" = "403" ]; then
      action "BAP environments: HTTP 403 — assign Power Platform Administrator Entra directory role to the SP."
    else
      fail "BAP environments: HTTP $STATUS"
    fi
  fi

  # Dataverse / Dynamics CRM
  if [ -n "${DATAVERSE_URL:-}" ]; then
    DV_URL="${DATAVERSE_URL%/}"
    info "Acquiring Dataverse token for $DV_URL..."
    DV_TOKEN=$(get_token "$DV_URL")
    if [ -z "$DV_TOKEN" ] || [[ "$DV_TOKEN" == ERROR:* ]]; then
      fail "Dataverse token acquisition failed: $DV_TOKEN"
    else
      ok "Dataverse token acquired."
      info "Testing Dataverse bots endpoint..."
      STATUS=$(api_get "${DV_URL}/api/data/v9.2/bots?\$top=1&\$select=botid,name" "$DV_TOKEN")
      [ "$STATUS" = "200" ] && ok "Dataverse bots: HTTP $STATUS" || fail "Dataverse bots: HTTP $STATUS"
    fi
  else
    skip "DATAVERSE_URL not set — skipping Dataverse test."
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# Summary — always printed last so it's visible at the prompt
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "  [$(ts)] STEP 2 SUMMARY"
echo "  Service principal:  agent-telemetry-poc"
echo "  App ID:             $APP_ID"
echo "  Object ID:          $SP_OBJECT_ID"
echo "╚══════════════════════════════════════════════════════╝"

if [ "$PROVISION_ERRORS" -gt 0 ]; then
  echo ""
  echo "  ✗  $PROVISION_ERRORS PROVISIONING ERROR(S) — fix before step 3:"
  echo "     Scroll up and look for lines starting with  ✗"
  echo ""
  exit 1
fi

if [ "$MANUAL_ACTIONS" -gt 0 ]; then
  echo ""
  echo "  ►  $MANUAL_ACTIONS MANUAL ACTION(S) REQUIRED before step 3 fully works."
  echo ""
  echo "  Complete these in the Azure / Entra portal, then re-run to confirm:"
  echo ""

  # Re-check and reprint specifically what's outstanding
  if [ -z "${ROLE_ID:-}" ] || [ -z "$(az rest --method GET \
      --url "https://graph.microsoft.com/v1.0/directoryRoles/${ROLE_ID:-x}/members" \
      --query "value[?id=='${SP_OBJECT_ID}'].id" -o tsv 2>/dev/null || true)" ]; then
    echo "  1. Assign Entra directory role:"
    echo "       Entra ID → Roles and administrators"
    echo "       → 'Power Platform Administrator' → Add assignments"
    echo "       → paste SP object ID: $SP_OBJECT_ID"
    echo ""
  fi

  CONSENT_CHECK=$(az rest --method GET \
    --url "https://graph.microsoft.com/v1.0/servicePrincipals/${SP_OBJECT_ID}/appRoleAssignments" \
    --query "length(value)" -o tsv 2>/dev/null || echo "0")
  if [ "${CONSENT_CHECK:-0}" -eq "0" ]; then
    echo "  2. Grant admin consent:"
    echo "       Entra ID → App registrations → agent-telemetry-poc"
    echo "       → API permissions → Grant admin consent for <tenant>"
    echo ""
  fi

  echo "  After completing the above, re-run step2_identity.sh to confirm all green."
  echo "  Then run step3_mcp.sh."
  echo ""
else
  echo ""
  echo "  ✓  All checks passed — proceed to step3_mcp.sh"
  echo ""
fi
