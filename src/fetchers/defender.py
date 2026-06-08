"""
Microsoft Defender for Cloud fetcher — security alerts, secure score.

Auth scope: https://management.azure.com/.default
Required role: Security Reader on the subscription.

Set DEFENDER_SUBSCRIPTION_ID in your .env to enable.
Full Defender incidents (correlated multi-resource attacks) are available via
the Microsoft 365 Defender API (security.microsoft.com) — stubbed below.
"""
import requests
from azure.core.credentials import TokenCredential

_MGMT_SCOPE = "https://management.azure.com/.default"
_MGMT_BASE  = "https://management.azure.com"


class DefenderFetcher:
    def __init__(self, credential: TokenCredential, subscription_id: str) -> None:
        self._credential    = credential
        self._subscription  = subscription_id
        self._sub_base      = f"{_MGMT_BASE}/subscriptions/{subscription_id}"

    def _headers(self) -> dict:
        token = self._credential.get_token(_MGMT_SCOPE).token
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    # ------------------------------------------------------------------
    # Security alerts (Defender for Cloud)
    # ------------------------------------------------------------------

    def fetch_alerts(self, severity_filter: str = "") -> list[dict]:
        """
        Defender for Cloud security alerts on the subscription.
        severity_filter: "High" | "Medium" | "Low" | "" (all)
        """
        params: dict = {"api-version": "2022-01-01"}
        if severity_filter:
            params["$filter"] = f"properties/severity eq '{severity_filter}'"
        resp = requests.get(
            f"{self._sub_base}/providers/Microsoft.Security/alerts",
            headers=self._headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        out = []
        for a in resp.json().get("value", []):
            props = a.get("properties", {})
            out.append({
                "alert_id":           a.get("name", ""),
                "display_name":       props.get("alertDisplayName", ""),
                "severity":           props.get("severity", ""),
                "status":             props.get("status", ""),
                "description":        props.get("description", ""),
                "remediation_steps":  props.get("remediationSteps", []),
                "compromised_entity": props.get("compromisedEntity", ""),
                "alert_type":         props.get("alertType", ""),
                "start_time":         props.get("startTimeUtc", ""),
                "end_time":           props.get("endTimeUtc", ""),
            })
        return out

    # ------------------------------------------------------------------
    # Secure score
    # ------------------------------------------------------------------

    def fetch_secure_score(self) -> list[dict]:
        """Defender for Cloud secure score for the subscription."""
        resp = requests.get(
            f"{self._sub_base}/providers/Microsoft.Security/secureScores",
            headers=self._headers(),
            params={"api-version": "2020-01-01"},
            timeout=30,
        )
        resp.raise_for_status()
        out = []
        for s in resp.json().get("value", []):
            props     = s.get("properties", {})
            current   = props.get("score", {}).get("current", 0)
            max_score = props.get("score", {}).get("max", 0)
            out.append({
                "name":         s.get("name", ""),
                "display_name": props.get("displayName", ""),
                "current_score": current,
                "max_score":    max_score,
                "percentage":   round(current / max_score * 100, 1) if max_score else 0,
                "weight":       props.get("weight", 0),
            })
        return out

    # ------------------------------------------------------------------
    # Incidents (Microsoft 365 Defender — stubbed)
    # ------------------------------------------------------------------

    def fetch_incidents(self) -> list[dict]:
        """
        Correlated multi-resource incidents from Microsoft 365 Defender.
        Requires Microsoft 365 Defender API (security.microsoft.com) and
        SecurityIncident.Read.All permission.
        Stubbed — returns [] until API access is provisioned.
        """
        # TODO: implement via GET https://api.security.microsoft.com/api/incidents
        return []
