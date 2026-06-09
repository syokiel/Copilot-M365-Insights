"""
Power Platform Analytics API fetcher — per-bot session and topic analytics.

Uses the PP Analytics REST API (analytics.api.powerplatform.com), which is a
separate surface from the PP Admin API but shares the same auth scope.

Required role: Power Platform Administrator (or Environment Admin scoped to each env).
"""
import hashlib
from datetime import datetime, timedelta, timezone

import requests
from azure.core.credentials import TokenCredential

_PP_ANALYTICS_BASE  = "https://analytics.api.powerplatform.com"
_PP_ANALYTICS_SCOPE = "https://api.powerplatform.com/.default"


def _date_range(lookback_days: int) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return (
        (now - timedelta(days=lookback_days)).strftime("%Y-%m-%d"),
        now.strftime("%Y-%m-%d"),
    )


def _session_row_id(session_id: str, bot_id: str) -> str:
    return hashlib.sha1(f"{session_id}|{bot_id}".encode()).hexdigest()


class PPAnalyticsFetcher:
    def __init__(self, credential: TokenCredential) -> None:
        self._credential = credential

    def _headers(self) -> dict:
        token = self._credential.get_token(_PP_ANALYTICS_SCOPE).token
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def _get_paged(self, path: str, params: dict) -> list[dict]:
        items: list[dict] = []
        url: str | None = f"{_PP_ANALYTICS_BASE}{path}"
        first = True
        while url:
            resp = requests.get(
                url,
                headers=self._headers(),
                params=params if first else {},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink") or data.get("nextLink")
            first = False
        return items

    # ── Per-session data ──────────────────────────────────────────────────────

    def fetch_bot_sessions(
        self,
        environment_id: str,
        bot_id: str,
        lookback_days: int = 30,
    ) -> list[dict]:
        """
        Individual session records for one bot.
        Outcome values: Resolved, Escalated, Abandoned, Unengaged.
        """
        from_date, to_date = _date_range(lookback_days)
        raw = self._get_paged(
            "/analytics/bots/v1.0/sessions",
            {
                "botId":         bot_id,
                "environmentId": environment_id,
                "from":          from_date,
                "to":            to_date,
            },
        )
        out = []
        for s in raw:
            sid = (
                s.get("sessionId")
                or s.get("id")
                or s.get("conversationId", "")
            )
            out.append({
                "session_id":     sid,
                "bot_id":         bot_id,
                "environment_id": environment_id,
                "start_time":     s.get("startDateTime") or s.get("startTime", ""),
                "outcome":        s.get("outcome", ""),
                "duration_sec":   s.get("durationInSeconds") or s.get("duration"),
                "channel":        s.get("channelId") or s.get("channel", ""),
                "topic_id":       s.get("topicId", ""),
                "topic_name":     s.get("topicName") or s.get("triggeredTopicName", ""),
                "csat_score":     s.get("csatScore") or s.get("satisfactionScore"),
                "turn_count":     s.get("turnCount") or s.get("turns"),
            })
        return out

    # ── Per-topic aggregates ──────────────────────────────────────────────────

    def fetch_bot_topic_analytics(
        self,
        environment_id: str,
        bot_id: str,
        lookback_days: int = 30,
    ) -> list[dict]:
        """
        Aggregate topic performance metrics for one bot over the lookback period.
        One row per topic; counts are cumulative across the date range.
        """
        from_date, to_date = _date_range(lookback_days)
        raw = self._get_paged(
            "/analytics/bots/v1.0/topics",
            {
                "botId":         bot_id,
                "environmentId": environment_id,
                "from":          from_date,
                "to":            to_date,
            },
        )
        fetch_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out = []
        for t in raw:
            out.append({
                "bot_id":             bot_id,
                "environment_id":     environment_id,
                "topic_id":           t.get("topicId") or t.get("id", ""),
                "topic_name":         t.get("topicName") or t.get("name", ""),
                "fetch_date":         fetch_date,
                "period_from":        from_date,
                "period_to":          to_date,
                "total_sessions":     t.get("totalSessions") or t.get("sessionCount"),
                "resolved_sessions":  t.get("resolvedSessions") or t.get("resolvedCount"),
                "escalated_sessions": t.get("escalatedSessions") or t.get("escalatedCount"),
                "abandoned_sessions": t.get("abandonedSessions") or t.get("abandonedCount"),
                "trigger_count":      t.get("triggerCount") or t.get("triggeredCount"),
                "success_rate":       t.get("successRate") or t.get("resolutionRate"),
            })
        return out

    # ── Convenience: fetch all bots in a list of (env_id, bot_id) pairs ──────

    def fetch_all_sessions(
        self,
        agents: list[dict],
        lookback_days: int = 30,
    ) -> list[dict]:
        """Iterate known agents and collect sessions across all of them."""
        all_sessions: list[dict] = []
        errors = 0
        for agent in agents:
            env_id = agent.get("environment_id", "")
            bot_id = agent.get("agent_id", "")
            if not env_id or not bot_id:
                continue
            try:
                sessions = self.fetch_bot_sessions(env_id, bot_id, lookback_days)
                all_sessions.extend(sessions)
            except Exception:
                errors += 1
                # Stop after 3 consecutive errors — API likely unavailable
                if errors >= 3:
                    break
        return all_sessions

    def fetch_all_topic_analytics(
        self,
        agents: list[dict],
        lookback_days: int = 30,
    ) -> list[dict]:
        """Iterate known agents and collect topic analytics across all of them."""
        all_topics: list[dict] = []
        errors = 0
        for agent in agents:
            env_id = agent.get("environment_id", "")
            bot_id = agent.get("agent_id", "")
            if not env_id or not bot_id:
                continue
            try:
                topics = self.fetch_bot_topic_analytics(env_id, bot_id, lookback_days)
                all_topics.extend(topics)
            except Exception:
                errors += 1
                if errors >= 3:
                    break
        return all_topics
