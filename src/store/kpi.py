"""KPI snapshot computation and history."""
import uuid
from datetime import datetime, timezone


class KpiMixin:
    def compute_kpi_snapshot(self, lookback_days: int, total_licenses: int = 0) -> dict:
        """Compute KPI values from current DB state and return as a dict."""
        from datetime import date, timedelta as td
        cutoff = (date.today() - td(days=lookback_days)).isoformat()

        enabled_users = self._conn.execute(
            "SELECT COUNT(*) FROM m365_copilot_usage"
        ).fetchone()[0] or 0

        active_users = self._conn.execute(
            "SELECT COUNT(*) FROM m365_copilot_usage "
            "WHERE last_activity_date IS NOT NULL AND last_activity_date != ''"
        ).fetchone()[0] or 0

        totals = self._conn.execute("""
            SELECT
                SUM(COALESCE(copilot_chat,0)),
                SUM(COALESCE(teams_chats,0) + COALESCE(teams_meetings,0)),
                SUM(COALESCE(outlook,0)),
                SUM(COALESCE(excel,0)),
                SUM(COALESCE(word,0)),
                SUM(COALESCE(powerpoint,0)),
                SUM(COALESCE(onenote,0)),
                SUM(COALESCE(loop,0)),
                SUM(COALESCE(teams_chats,0) + COALESCE(teams_meetings,0) +
                    COALESCE(word,0) + COALESCE(excel,0) + COALESCE(powerpoint,0) +
                    COALESCE(outlook,0) + COALESCE(onenote,0) + COALESCE(loop,0) +
                    COALESCE(copilot_chat,0))
            FROM m365_copilot_usage
        """).fetchone()
        (p_chat, p_teams, p_outlook, p_excel, p_word,
         p_ppt, p_onenote, p_loop, total_prompts) = [v or 0 for v in totals]

        power_users = self._conn.execute("""
            WITH user_totals AS (
                SELECT COALESCE(teams_chats,0)+COALESCE(teams_meetings,0)+
                       COALESCE(word,0)+COALESCE(excel,0)+COALESCE(powerpoint,0)+
                       COALESCE(outlook,0)+COALESCE(onenote,0)+COALESCE(loop,0)+
                       COALESCE(copilot_chat,0) AS total
                FROM m365_copilot_usage
                WHERE last_activity_date IS NOT NULL AND last_activity_date != ''
            ),
            ranked AS (
                SELECT total,
                       ROW_NUMBER() OVER (ORDER BY total DESC) AS rn,
                       COUNT(*) OVER () AS cnt
                FROM user_totals
            )
            SELECT COUNT(*) FROM ranked WHERE rn * 5 <= cnt
        """).fetchone()[0] or 0

        total_agents = self._conn.execute(
            "SELECT COUNT(*) FROM pva_agents"
        ).fetchone()[0] or 0

        active_agents = self._conn.execute(
            "SELECT COUNT(DISTINCT gen_ai_agent_id) FROM conversation_events "
            "WHERE design_mode=0 AND gen_ai_agent_id IS NOT NULL AND gen_ai_agent_id != '' "
            "AND timestamp >= ?", (cutoff,)
        ).fetchone()[0] or 0

        agents_with_owner = self._conn.execute(
            "SELECT COUNT(*) FROM pva_agents WHERE owner_id IS NOT NULL AND owner_id != ''"
        ).fetchone()[0] or 0

        total_conversations = self._conn.execute(
            "SELECT COUNT(DISTINCT conversation_id) FROM conversation_events "
            "WHERE design_mode=0 AND timestamp >= ?", (cutoff,)
        ).fetchone()[0] or 0

        agent_adopters = self._conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM conversation_events "
            "WHERE design_mode=0 AND user_id IS NOT NULL AND user_id != '' AND timestamp >= ?",
            (cutoff,)
        ).fetchone()[0] or 0

        production_agents = self._conn.execute("""
            SELECT COUNT(a.agent_id) FROM pva_agents a
            JOIN pva_environments e ON a.environment_id = e.environment_id
            WHERE LOWER(COALESCE(e.sku, e.type, '')) = 'production'
        """).fetchone()[0] or 0

        env_counts: dict[str, int] = {}
        for row in self._conn.execute("""
            SELECT LOWER(COALESCE(e.sku, e.type, 'unknown')) AS env_type, COUNT(a.agent_id)
            FROM pva_agents a
            LEFT JOIN pva_environments e ON a.environment_id = e.environment_id
            GROUP BY env_type
        """).fetchall():
            env_counts[row[0]] = row[1]

        return {
            "snapshot_id": str(uuid.uuid4()),
            "snapshot_date": datetime.now(timezone.utc).isoformat(),
            "lookback_days": lookback_days,
            "total_licenses": total_licenses or None,
            "enabled_users": enabled_users,
            "active_users": active_users,
            "activation_rate": round(enabled_users / total_licenses * 100, 1) if total_licenses else None,
            "adoption_rate": round(active_users / enabled_users * 100, 1) if enabled_users else None,
            "power_users": power_users,
            "total_prompts": total_prompts,
            "avg_prompts_per_user": round(total_prompts / active_users, 1) if active_users else None,
            "prompts_copilot_chat": p_chat,
            "prompts_teams": p_teams,
            "prompts_outlook": p_outlook,
            "prompts_excel": p_excel,
            "prompts_word": p_word,
            "prompts_powerpoint": p_ppt,
            "prompts_onenote": p_onenote,
            "prompts_loop": p_loop,
            "agent_adopters": agent_adopters,
            "agent_adoption_pct": round(agent_adopters / enabled_users * 100, 1) if enabled_users else None,
            "total_agents": total_agents,
            "active_agents": active_agents,
            "utilization_rate": round(active_agents / total_agents * 100, 1) if total_agents else None,
            "production_agents": production_agents,
            "non_prod_agents": total_agents - production_agents,
            "agents_with_owner": agents_with_owner,
            "ownership_pct": round(agents_with_owner / total_agents * 100, 1) if total_agents else None,
            "total_conversations": total_conversations,
            "env_default": env_counts.get("default", 0),
            "env_developer": env_counts.get("developer", 0),
            "env_teams": env_counts.get("teams", env_counts.get("microsoftteams", 0)),
            "env_production": env_counts.get("production", 0),
            "env_sandbox": env_counts.get("sandbox", 0),
            "env_trial": env_counts.get("trial", 0),
        }

    def upsert_kpi_snapshot(self, snap: dict) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO kpi_snapshots VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    snap["snapshot_id"], snap["snapshot_date"], snap["lookback_days"],
                    snap.get("total_licenses"), snap.get("enabled_users"), snap.get("active_users"),
                    snap.get("activation_rate"), snap.get("adoption_rate"), snap.get("power_users"),
                    snap.get("total_prompts"), snap.get("avg_prompts_per_user"),
                    snap.get("prompts_copilot_chat"), snap.get("prompts_teams"),
                    snap.get("prompts_outlook"), snap.get("prompts_excel"), snap.get("prompts_word"),
                    snap.get("prompts_powerpoint"), snap.get("prompts_onenote"), snap.get("prompts_loop"),
                    snap.get("agent_adopters"), snap.get("agent_adoption_pct"),
                    snap.get("total_agents"), snap.get("active_agents"), snap.get("utilization_rate"),
                    snap.get("production_agents"), snap.get("non_prod_agents"),
                    snap.get("agents_with_owner"), snap.get("ownership_pct"),
                    snap.get("total_conversations"),
                    snap.get("env_default", 0), snap.get("env_developer", 0),
                    snap.get("env_teams", 0), snap.get("env_production", 0),
                    snap.get("env_sandbox", 0), snap.get("env_trial", 0),
                ),
            )

    def fetch_kpi_snapshots(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM kpi_snapshots ORDER BY snapshot_date DESC"
        ).fetchall()
        return [dict(r) for r in rows]

