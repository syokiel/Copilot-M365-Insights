#!/usr/bin/env python3
"""
Export ALL Copilot Studio agents in the tenant -- past the Power Platform admin
center 1,000-item display cap.

It calls the Power Platform Inventory API (which is what the PPAC screen itself
calls). That API is backed by Azure Resource Graph, covers every environment in
the tenant in a single query, and pages with skipToken -- so there is no 1,000
limit on the data, only on the UI.

Endpoint:
    POST https://api.powerplatform.com/resourcequery/resources/query?api-version=2024-10-01
Resource type:
    microsoft.copilotstudio/agents   (V2 / Copilot Studio + Agent Builder agents)
    NOTE: classic / Power Virtual Agents V1 bots are NOT in this inventory.

Requirements:
    pip install msal requests

Auth (one-time setup):
    1. Register a Microsoft Entra app (Public client) in your tenant.
    2. Add a *delegated* permission to the "Power Platform API"
       (first-party app id 8578e004-a5c6-46e7-913e-12f58912df43).
    3. Sign in below as a Power Platform Administrator -- inventory visibility
       follows the signed-in user's admin scope.

If you already have Azure CLI logged in as the admin, you can skip the app
registration entirely -- see get_token_via_azcli() at the bottom.

1- az login --allow-no-subscriptions --tenant Stryker.onmicrosoft.com
2-

"""

import csv
import sys
import requests
import msal

# ---------------------------------------------------------------- config ----
TENANT_ID = "4e9dbbfb-394a-4583-8810-53f81f819e3b"
CLIENT_ID = ""  # used only by get_token() — get_token_via_azcli() needs no app reg
SCOPE = ["https://api.powerplatform.com/.default"]

API = "https://api.powerplatform.com/resourcequery/resources/query?api-version=2024-10-01"
PAGE_SIZE = 1000
OUT = "copilot_studio_agents.csv"


# ------------------------------------------------------------- auth (MSAL) --
def get_token():
    """Interactive device-code sign-in as a Power Platform admin."""
    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
    )
    flow = app.initiate_device_flow(scopes=SCOPE)
    if "user_code" not in flow:
        raise RuntimeError(f"Device flow init failed: {flow}")
    print(flow["message"])  # open the URL, enter the code, sign in
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(result.get("error_description", result))
    return result["access_token"]


# ---------------------------------------------------------- query helper ----
def query_all(token, type_filter, field_list):
    """Page through every record of a given resource type using skipToken.

    Pagination contract: send Top + (SkipToken once it exists). Do NOT send a
    numeric Skip -- the API honors Skip over SkipToken, which restarts every
    page at row 0 and loops forever. Multiple guards below also hard-stop if the
    service ever fails to advance.
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    id_field = field_list[0].split("=")[0].strip()  # first projected alias = unique id
    rows, seen, skip_token, prev_token = [], set(), "", None
    while True:
        options = {"Top": PAGE_SIZE}
        if skip_token:
            options["SkipToken"] = skip_token
        body = {
            "TableName": "PowerPlatformResources",
            "Clauses": [
                {"$type": "where", "FieldName": "type",
                 "Operator": "==", "Values": [f"'{type_filter}'"]},
                {"$type": "project", "FieldList": field_list},
            ],
            "Options": options,
        }
        resp = requests.post(API, headers=headers, json=body, timeout=120)
        resp.raise_for_status()
        data = resp.json()

        page = data.get("data", [])
        new = 0
        for r in page:
            key = r.get(id_field)
            if key not in seen:
                seen.add(key)
                rows.append(r)
                new += 1

        total = data.get("totalRecords")
        print(f"  fetched {len(rows)} / {total}  (page {len(page)}, new {new})")

        skip_token = data.get("skipToken") or ""
        # --- termination guards (any one ends the loop) ---
        if not skip_token:
            break
        if total is not None and len(rows) >= total:
            break
        if new == 0:                       # page contributed nothing new
            break
        if skip_token == prev_token:       # token stopped advancing
            break
        prev_token = skip_token
    return rows


# ----------------------------------------------------------------- main -----
def main():
    token = get_token_via_azcli()   # uses your `az login` session

    # 1) environments -> id:name lookup (so the CSV shows names, not GUIDs)
    print("Fetching environments...")
    envs = query_all(token, "microsoft.powerplatform/environments", [
        "envId = name",
        "envName = tostring(properties.displayName)",
        "envType = tostring(properties.environmentType)",
        "envRegion = location",
    ])
    env_meta = {e.get("envId"): e for e in envs}

    # 2) every Copilot Studio agent in the tenant
    print("Fetching Copilot Studio agents...")
    agents = query_all(token, "microsoft.copilotstudio/agents", [
        "agentId = name",
        "displayName = tostring(properties.displayName)",
        "environmentId = tostring(properties.environmentId)",
        "createdAt = tostring(properties.createdAt)",
        "createdBy = tostring(properties.createdBy)",
        "ownerId = tostring(properties.ownerId)",
        "lastPublishedAt = tostring(properties.lastPublishedAt)",
        "createdIn = tostring(properties.createdIn)",
        "schemaName = tostring(properties.schemaName)",
    ])

    # 3) enrich with environment name + write CSV
    cols = ["agentId", "displayName", "environmentId", "environmentName",
            "environmentType", "environmentRegion",
            "createdAt", "createdBy", "ownerId", "lastPublishedAt",
            "createdIn", "schemaName"]
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for a in agents:
            env = env_meta.get(a.get("environmentId", ""), {})
            a["environmentName"]   = env.get("envName", "")
            a["environmentType"]   = env.get("envType", "")
            a["environmentRegion"] = env.get("envRegion", "")
            w.writerow({c: a.get(c, "") for c in cols})

    print(f"\nDone. {len(agents)} agents written to {OUT}")


# ----------------------------------------- optional: Azure CLI token path ---
def get_token_via_azcli():
    """
    No app registration needed. Requires Azure CLI logged in as the admin:
        az login
    Then swap get_token() for this in main().
    """
    import json, subprocess
    out = subprocess.check_output([
        "az", "account", "get-access-token",
        "--resource", "https://api.powerplatform.com",
        "-o", "json",
    ])
    return json.loads(out)["accessToken"]


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print(f"HTTP error: {e}\n{e.response.text}", file=sys.stderr)
        sys.exit(1)
