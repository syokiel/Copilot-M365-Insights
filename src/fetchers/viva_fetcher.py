"""
viva_fetcher.py
─────────────────────────────────────────────────────────────────────────────
Fetches Viva Insights data from Microsoft Graph and the Viva Insights
Management API.

Two tiers of data:

1. Personal analytics  (Graph Analytics API — Analytics.ReadAll app permission)
   GET /v1.0/users/{id}/analytics/activityStatistics
   Returns per-user weekly focus / meeting / email / chat / after-hours blocks.
   Pivoted into one row per (user, week_start) before storage.

2. Org-level insights  (Viva Insights Management API — future / licensed)
   Placeholder methods stubbed out; wired but return [] until API access is
   confirmed. Requires Viva Insights Advanced or Workplace Analytics license.
   Base: https://api.adoption.m365.microsoft.com/v1.0/
─────────────────────────────────────────────────────────────────────────────
"""

import hashlib
import re
from datetime import datetime, timezone

import requests
from azure.identity import ClientSecretCredential

_GRAPH_BASE = "https://graph.microsoft.com"
_GRAPH_SCOPE = "https://graph.microsoft.com/.default"
_VIVA_MGMT_BASE = "https://api.adoption.m365.microsoft.com/v1.0"


def _duration_to_hours(iso: str) -> float:
    """Convert ISO 8601 duration (PT5H30M) to decimal hours."""
    if not iso:
        return 0.0
    h = int(m.group(1)) if (m := re.search(r"(\d+)H", iso)) else 0
    mins = int(m.group(1)) if (m := re.search(r"(\d+)M", iso)) else 0
    return round(h + mins / 60, 4)


def _row_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()


class VivaFetcher:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str) -> None:
        self._credential = ClientSecretCredential(tenant_id, client_id, client_secret)

    def _graph_headers(self) -> dict:
        token = self._credential.get_token(f"{_GRAPH_BASE}/.default").token
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def _viva_headers(self) -> dict:
        token = self._credential.get_token(f"{_VIVA_MGMT_BASE}/.default").token
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    # ──────────────────────────────────────────────────────────────────────────
    # Personal analytics (Graph Analytics API)
    # ──────────────────────────────────────────────────────────────────────────

    def fetch_person_insights(self, user_ids: list[str]) -> list[dict]:
        """
        Per-user weekly activity breakdown.
        Returns one dict per (user_id, week_start) with hours pivoted into columns.
        Silently skips users where the API returns 403 (no license or no consent).
        """
        headers = self._graph_headers()
        fetched_at = datetime.now(timezone.utc).isoformat()
        results: dict[str, dict] = {}   # key = row_id

        for user_id in user_ids:
            try:
                resp = requests.get(
                    f"{_GRAPH_BASE}/v1.0/users/{user_id}/analytics/activityStatistics",
                    headers=headers,
                    timeout=30,
                )
                if resp.status_code in (403, 404):
                    continue
                resp.raise_for_status()

                for stat in resp.json().get("value", []):
                    week_start = stat.get("startTime", "")[:10]
                    week_end   = stat.get("endTime",   "")[:10]
                    rid        = _row_id(user_id, week_start)

                    row = results.setdefault(rid, {
                        "row_id":         rid,
                        "user_id":        user_id,
                        "week_start":     week_start,
                        "week_end":       week_end,
                        "focus_hours":    0.0,
                        "meeting_hours":  0.0,
                        "email_hours":    0.0,
                        "chat_hours":     0.0,
                        "after_hours":    0.0,
                        "fetched_at":     fetched_at,
                    })

                    activity = (stat.get("activity") or "").lower()
                    hours    = _duration_to_hours(stat.get("duration", ""))

                    if "focus"       in activity:  row["focus_hours"]   = hours
                    elif "meeting"   in activity:  row["meeting_hours"] = hours
                    elif "email"     in activity:  row["email_hours"]   = hours
                    elif "chat"      in activity:  row["chat_hours"]    = hours
                    elif "afterhour" in activity or "after_hour" in activity:
                        row["after_hours"] = hours

            except Exception:
                continue

        return list(results.values())

    # ──────────────────────────────────────────────────────────────────────────
    # Org-level insights (Viva Insights Management API — stubbed)
    # ──────────────────────────────────────────────────────────────────────────

    def fetch_org_insights(self) -> list[dict]:
        """
        Organisation-wide Viva Insights aggregates.
        Requires Viva Insights Advanced / Workplace Analytics license.
        Stubbed — returns [] until API access token scope is confirmed.

        When ready, implement:
          GET {_VIVA_MGMT_BASE}/viva/insights/getMetrics
          or the relevant advanced analytics endpoint.
        """
        # TODO: implement once org-level Viva Insights API access is provisioned.
        return []

    def fetch_meeting_quality(self) -> list[dict]:
        """
        Teams meeting quality & collaboration patterns from Viva Insights.
        Stubbed — returns [] until API access is confirmed.
        """
        # TODO: implement via Viva Insights advanced metrics endpoint.
        return []
