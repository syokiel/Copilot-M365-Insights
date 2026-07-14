"""
Microsoft Graph Reports API fetcher — M365 Copilot usage, Teams activity,
Copilot admin catalog, O365/M365 app usage, and Azure AD user resolution.
"""
import csv
import io
import json

import requests
from azure.core.credentials import TokenCredential

_GRAPH_BASE   = "https://graph.microsoft.com/v1.0"
_GRAPH_SCOPE  = "https://graph.microsoft.com/.default"


def _period(days: int) -> str:
    for threshold, label in ((7, "D7"), (30, "D30"), (90, "D90")):
        if days <= threshold:
            return label
    return "D180"


def _int(val: str) -> int | None:
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


class GraphFetcher:
    def __init__(self, credential: TokenCredential) -> None:
        self._credential = credential

    def _headers(self) -> dict:
        token = self._credential.get_token(_GRAPH_SCOPE).token
        return {"Authorization": f"Bearer {token}"}

    def _fetch_csv(self, path: str) -> list[dict]:
        resp = requests.get(
            f"{_GRAPH_BASE}{path}",
            headers=self._headers(),
            timeout=60,
            allow_redirects=True,
        )
        resp.raise_for_status()
        text = resp.content.decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))

    def _fetch_json(self, path: str, params: dict | None = None) -> dict:
        resp = requests.get(
            f"{_GRAPH_BASE}{path}",
            headers={**self._headers(), "Accept": "application/json"},
            params=params or {},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def _fetch_json_paged(self, path: str) -> list[dict]:
        """Follow @odata.nextLink to collect all pages."""
        items: list[dict] = []
        url: str | None = f"{_GRAPH_BASE}{path}"
        hdrs = {**self._headers(), "Accept": "application/json"}
        while url:
            resp = requests.get(url, headers=hdrs, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
        return items

    def fetch_copilot_usage(self, lookback_days: int = 30) -> list[dict]:
        """Per-user M365 Copilot prompt activity across all surfaces."""
        rows = self._fetch_csv(
            f"/copilot/reports/getMicrosoft365CopilotUsageUserDetail(period='{_period(lookback_days)}')"
        )
        return [
            {
                "report_refresh_date": r.get("Report Refresh Date", ""),
                "user_principal_name": r.get("User Principal Name", ""),
                "display_name":        r.get("Display Name", ""),
                "last_activity_date":  r.get("Last Activity Date", ""),
                "teams_chats":         _int(r.get("Teams Chats", "")),
                "teams_meetings":      _int(r.get("Teams Meetings", "")),
                "word":                _int(r.get("Word", "")),
                "excel":               _int(r.get("Excel", "")),
                "powerpoint":          _int(r.get("PowerPoint", "")),
                "outlook":             _int(r.get("Outlook", "")),
                "onenote":             _int(r.get("OneNote", "")),
                "loop":                _int(r.get("Loop", "")),
                "copilot_chat":        _int(r.get("Copilot Chat", "")),
                "report_period":       r.get("Report Period", ""),
            }
            for r in rows
        ]

    def fetch_teams_activity(self, lookback_days: int = 30) -> list[dict]:
        """Per-user Teams activity (messages, calls, meetings)."""
        rows = self._fetch_csv(
            f"/reports/getTeamsUserActivityUserDetail(period='{_period(lookback_days)}')"
        )
        return [
            {
                "report_refresh_date":  r.get("Report Refresh Date", ""),
                "user_principal_name":  r.get("User Principal Name", ""),
                "last_activity_date":   r.get("Last Activity Date", ""),
                "team_chat_messages":   _int(r.get("Team Chat Message Count", "")),
                "private_chat_messages": _int(r.get("Private Chat Message Count", "")),
                "calls":                _int(r.get("Call Count", "")),
                "meetings":             _int(r.get("Meeting Count", "")),
                "meetings_organized":   _int(r.get("Meetings Organized Count", "")),
                "meetings_attended":    _int(r.get("Meetings Attended Count", "")),
                "report_period":        r.get("Report Period", ""),
            }
            for r in rows
        ]

    # ── Copilot user count summary ────────────────────────────────────────────

    def fetch_copilot_user_count_summary(self, lookback_days: int = 30) -> list[dict]:
        """
        Aggregate Copilot enabled/active user counts for the period.
        GET /copilot/reports/getMicrosoft365CopilotUserCountSummary(period='D30')
        Returns one row per report-refresh-date.
        """
        rows = self._fetch_csv(
            f"/copilot/reports/getMicrosoft365CopilotUserCountSummary(period='{_period(lookback_days)}')"
        )
        out = []
        for r in rows:
            out.append({
                "report_refresh_date": r.get("Report Refresh Date", ""),
                "report_period":       r.get("Report Period", ""),
                "enabled_users":       _int(r.get("Microsoft 365 Copilot Enabled Users")),
                "active_users":        _int(r.get("Microsoft 365 Copilot Active Users")),
                "chat_active":         _int(r.get("Copilot Chat Active Users")
                                            or r.get("Microsoft 365 Copilot Chat Active Users")),
                "teams_active":        _int(r.get("Teams Chat Active Users")
                                            or r.get("Microsoft Teams Copilot Active Users")),
                "teams_meetings_active": _int(r.get("Teams Meetings Copilot Active Users")),
                "word_active":         _int(r.get("Word Active Users")),
                "excel_active":        _int(r.get("Excel Active Users")),
                "powerpoint_active":   _int(r.get("PowerPoint Active Users")),
                "outlook_active":      _int(r.get("Outlook Active Users")),
                "onenote_active":      _int(r.get("OneNote Active Users")),
                "loop_active":         _int(r.get("Loop Active Users")),
                "windows_active":      _int(r.get("Windows Copilot Active Users")),
                "web_active":          _int(r.get("Web Copilot Active Users")),
                "mobile_active":       _int(r.get("Mobile Copilot Active Users")),
            })
        return out

    # ── Copilot user count trend ──────────────────────────────────────────────

    def fetch_copilot_user_count_trend(self, lookback_days: int = 30) -> list[dict]:
        """
        Daily Copilot active user counts across the period.
        GET /copilot/reports/getMicrosoft365CopilotUserCountTrend(period='D30')
        """
        rows = self._fetch_csv(
            f"/copilot/reports/getMicrosoft365CopilotUserCountTrend(period='{_period(lookback_days)}')"
        )
        out = []
        for r in rows:
            out.append({
                "report_date":         r.get("Report Date", ""),
                "report_refresh_date": r.get("Report Refresh Date", ""),
                "report_period":       r.get("Report Period", ""),
                "active_users":        _int(r.get("Microsoft 365 Copilot Active Users")),
                "chat_active":         _int(r.get("Copilot Chat Active Users")
                                            or r.get("Microsoft 365 Copilot Chat Active Users")),
                "teams_active":        _int(r.get("Teams Chat Active Users")),
                "teams_meetings_active": _int(r.get("Teams Meetings Copilot Active Users")),
                "word_active":         _int(r.get("Word Active Users")),
                "excel_active":        _int(r.get("Excel Active Users")),
                "powerpoint_active":   _int(r.get("PowerPoint Active Users")),
                "outlook_active":      _int(r.get("Outlook Active Users")),
                "onenote_active":      _int(r.get("OneNote Active Users")),
                "loop_active":         _int(r.get("Loop Active Users")),
            })
        return out

    # ── Copilot admin packages catalog ───────────────────────────────────────

    def fetch_copilot_packages(self) -> list[dict]:
        """
        List all Copilot extension packages deployed in the tenant.
        GET /copilot/admin/catalog/packages
        """
        items = self._fetch_json_paged("/copilot/admin/catalog/packages")
        out = []
        for p in items:
            out.append({
                "package_id":      p.get("id", ""),
                "display_name":    p.get("name", "") or p.get("displayName", ""),
                "description":     p.get("description", ""),
                "type":            p.get("type", ""),
                "state":           p.get("state", ""),
                "publisher_name":  p.get("publisherName", "") or p.get("publisherId", ""),
                "app_id":          p.get("appId", "") or p.get("teamsAppId", ""),
                "properties":      json.dumps({
                    k: v for k, v in p.items()
                    if k not in ("id", "name", "displayName", "description", "type",
                                 "state", "publisherName", "publisherId", "appId", "teamsAppId")
                }),
            })
        return out

    # ── O365 active user detail ───────────────────────────────────────────────

    def fetch_o365_active_user_detail(self, lookback_days: int = 30) -> list[dict]:
        """
        Per-user O365 service activity (Exchange, Teams, SharePoint, etc.).
        GET /reports/getOffice365ActiveUserDetail(period='D30')
        """
        rows = self._fetch_csv(
            f"/reports/getOffice365ActiveUserDetail(period='{_period(lookback_days)}')"
        )
        out = []
        for r in rows:
            out.append({
                "user_principal_name":       r.get("User Principal Name", ""),
                "display_name":              r.get("Display Name", ""),
                "is_deleted":                1 if r.get("Is Deleted", "").upper() == "TRUE" else 0,
                "exchange_last_activity":    r.get("Exchange Last Activity Date", ""),
                "onedrive_last_activity":    r.get("OneDrive Last Activity Date", ""),
                "sharepoint_last_activity":  r.get("SharePoint Last Activity Date", ""),
                "teams_last_activity":       r.get("Teams Last Activity Date", ""),
                "yammer_last_activity":      r.get("Yammer Last Activity Date", ""),
                "has_exchange_license":      1 if r.get("Has Exchange License", "").upper() == "TRUE" else 0,
                "has_onedrive_license":      1 if r.get("Has OneDrive License", "").upper() == "TRUE" else 0,
                "has_sharepoint_license":    1 if r.get("Has SharePoint License", "").upper() == "TRUE" else 0,
                "has_teams_license":         1 if r.get("Has Teams License", "").upper() == "TRUE" else 0,
                "has_yammer_license":        1 if r.get("Has Yammer License", "").upper() == "TRUE" else 0,
                "report_refresh_date":       r.get("Report Refresh Date", ""),
                "report_period":             r.get("Report Period", ""),
            })
        return out

    # ── M365 app user detail ──────────────────────────────────────────────────

    def fetch_m365_app_user_detail(self, lookback_days: int = 30) -> list[dict]:
        """
        Per-user M365 app usage across platforms (Windows/Mac/Mobile/Web).
        GET /reports/getM365AppUserDetail(period='D30')
        Activity columns are True/False per app × platform; we collapse to any-platform.
        """
        rows = self._fetch_csv(
            f"/reports/getM365AppUserDetail(period='{_period(lookback_days)}')"
        )

        def _any(*keys: str) -> int | None:
            vals = [r.get(k, "") for k in keys]
            if not any(v for v in vals):  # all empty → no data
                return None
            return 1 if any(v.upper() == "TRUE" for v in vals) else 0

        out = []
        for r in rows:
            out.append({
                "user_principal_name":  r.get("User Principal Name", ""),
                "last_activation_date": r.get("Last Activation Date", ""),
                "last_activity_date":   r.get("Last Activity Date", ""),
                "report_refresh_date":  r.get("Report Refresh Date", ""),
                "report_period":        r.get("Report Period", ""),
                "outlook_active": _any("Outlook (Windows)", "Outlook (Mac)", "Outlook (Mobile)", "Outlook (Web)"),
                "word_active":    _any("Word (Windows)",    "Word (Mac)",    "Word (Mobile)",    "Word (Web)"),
                "excel_active":   _any("Excel (Windows)",   "Excel (Mac)",   "Excel (Mobile)",   "Excel (Web)"),
                "ppt_active":     _any("PowerPoint (Windows)", "PowerPoint (Mac)", "PowerPoint (Mobile)", "PowerPoint (Web)"),
                "onenote_active": _any("OneNote (Windows)", "OneNote (Mac)", "OneNote (Mobile)", "OneNote (Web)"),
                "teams_active":   _any("Microsoft Teams (Windows)", "Microsoft Teams (Mac)", "Microsoft Teams (Mobile)", "Microsoft Teams (Web)"),
                "sharepoint_active": _any("SharePoint (Windows)", "SharePoint (Mac)", "SharePoint (Mobile)", "SharePoint (Web)"),
                "onedrive_active":   _any("OneDrive (Windows)", "OneDrive (Mac)", "OneDrive (Mobile)", "OneDrive (Web)"),
            })
        return out

    def fetch_all_user_ids(self, max_users: int = 999) -> list[str]:
        """
        Page through the tenant user directory and return Azure AD object IDs.
        Used as a fallback source for Viva when no IDs are available from the
        local store (e.g. no conversation events or agent owner data yet).
        """
        headers = self._headers()
        ids: list[str] = []
        url: str = f"{_GRAPH_BASE}/users"
        params: dict = {"$select": "id", "$top": min(max_users, 999)}
        while url and len(ids) < max_users:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            ids.extend(u["id"] for u in data.get("value", []) if u.get("id"))
            url = data.get("@odata.nextLink", "")
            params = {}
        return ids[:max_users]

    def resolve_users(self, user_ids: list[str]) -> list[dict]:
        """
        Resolve Azure AD object IDs to user profiles.
        Returns one dict per unique ID; found=False when the user doesn't exist.
        Silently skips IDs that error for reasons other than 404.
        """
        headers = self._headers()
        results = []
        seen: set[str] = set()
        for uid in user_ids:
            if not uid or uid in seen:
                continue
            seen.add(uid)
            try:
                resp = requests.get(
                    f"{_GRAPH_BASE}/users/{uid}",
                    headers=headers,
                    params={"$select": "id,displayName,userPrincipalName,department,jobTitle"},
                    timeout=30,
                )
                if resp.status_code == 404:
                    results.append({
                        "user_id": uid, "display_name": "", "upn": "",
                        "department": "", "job_title": "", "found": False,
                    })
                else:
                    resp.raise_for_status()
                    u = resp.json()
                    results.append({
                        "user_id":      uid,
                        "display_name": u.get("displayName", ""),
                        "upn":          u.get("userPrincipalName", ""),
                        "department":   u.get("department", "") or "",
                        "job_title":    u.get("jobTitle", "") or "",
                        "found":        True,
                    })
            except Exception:
                continue
        return results
