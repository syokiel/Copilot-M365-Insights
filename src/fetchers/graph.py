"""
Microsoft Graph Reports API fetcher — M365 Copilot usage, Teams activity,
and Azure AD user directory resolution.
"""
import csv
import io

import requests
from azure.core.credentials import TokenCredential

_GRAPH_BASE  = "https://graph.microsoft.com/v1.0"
_GRAPH_SCOPE = "https://graph.microsoft.com/.default"


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

    def fetch_copilot_usage(self, lookback_days: int = 30) -> list[dict]:
        """Per-user M365 Copilot prompt activity across all surfaces."""
        rows = self._fetch_csv(
            f"/reports/getMicrosoft365CopilotUsageUserDetail(period='{_period(lookback_days)}')"
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
