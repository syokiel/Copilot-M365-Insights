"""KPI snapshots: one row per data period, computed at the end of each sync.

A snapshot describes the *period the imported exports cover* (not the day the
sync ran), so re-running a month replaces its row and running months in
chronological order rebuilds KPI History. Metrics sourced from point-in-time
exports are only filled when that export was loaded in the same run (a report
carried forward from an earlier month never inflates a later one); metrics
from dated history use a trailing window ending at the period's data date.
"""
from datetime import date, datetime, timedelta, timezone

# (table, date column) whose latest value marks the end of the data period.
_PERIOD_DATE_SOURCES = (
    ("m365_copilot_usage_csv", "report_refresh_date"),
    ("m365_copilot_usage_graph", "report_refresh_date"),
    ("m365_copilot_chat_usage", "report_refresh_date"),
    ("m365_usage_active_users_detail", "report_refresh_date"),
    ("m365_usage_activations_users", "report_refresh_date"),
    ("m365_usage_proplus_detail", "report_refresh_date"),
    ("m365_usage_agents", "last_activity_date"),
)

# Trailing window (days) for metrics computed from weekly/daily history.
_TRAILING_DAYS = 28

_GRAPH_PROMPT_COLUMNS = (
    "teams_chats", "teams_meetings", "word", "excel", "powerpoint",
    "outlook", "onenote", "loop", "copilot_chat",
)
_HAS_GRAPH = "(" + " OR ".join(f"{c} IS NOT NULL" for c in _GRAPH_PROMPT_COLUMNS) + ")"
_GRAPH_TOTAL = " + ".join(f"COALESCE({c}, 0)" for c in _GRAPH_PROMPT_COLUMNS)
# Per-user prompt total: Graph per-app counts when the Graph pull has the
# user, otherwise the CSV export's "Prompts submitted for All Apps".
_USER_PROMPTS = f"CASE WHEN {_HAS_GRAPH} THEN {_GRAPH_TOTAL} ELSE COALESCE(prompts_all_apps, 0) END"


def _days_before(iso_date: str, days: int) -> str:
    return (date.fromisoformat(iso_date[:10]) - timedelta(days=days)).isoformat()


def _rate(part, whole):
    return round(part / whole * 100, 1) if whole else None


class KpiMixin:
    def _tables_loaded_this_run(self) -> set[str] | None:
        """Tables loaded by the current sync run (None = no run open, so
        treat everything in the DB as current)."""
        if not self._run_id:
            return None
        rows = self._conn.execute(
            "SELECT DISTINCT table_name FROM import_log WHERE run_id = ?", (self._run_id,)
        ).fetchall()
        return {r[0].split(" [")[0] for r in rows}

    def _scalar(self, sql: str, *params):
        return self._conn.execute(sql, params).fetchone()[0]

    def compute_kpi_snapshot(self, lookback_days: int, total_licenses: int = 0,
                             period: str | None = None) -> dict:
        """Compute the KPI row for the data period loaded by the current run."""
        loaded = self._tables_loaded_this_run()

        def has(*tables: str) -> bool:
            return loaded is None or any(t in loaded for t in tables)

        # ── Period ───────────────────────────────────────────────────────
        dates = [
            self._scalar(f"SELECT MAX({col}) FROM {table} WHERE COALESCE({col}, '') != ''")
            for table, col in _PERIOD_DATE_SOURCES if has(table)
        ]
        dates = [d[:10] for d in dates if d]
        if not dates:
            for sql in ("SELECT MAX(metric_date) FROM fact_copilot_work_patterns",
                        "SELECT MAX(metric_date) FROM viva_reports_cs_session_metrics",
                        "SELECT MAX(substr(timestamp, 1, 10)) FROM conversation_events"):
                d = self._scalar(sql)
                if d:
                    dates.append(d[:10])
        period_end = max(dates) if dates else date.today().isoformat()
        period = period or period_end[:7]
        cutoff = _days_before(period_end, lookback_days)
        period_end_ts = period_end + "T23:59:59"

        snap: dict = {
            "snapshot_id": f"period-{period}",
            "snapshot_date": datetime.now(timezone.utc).isoformat(),
            "lookback_days": lookback_days,
            "period": period,
            "period_end": period_end,
            "sources_loaded": ",".join(sorted(loaded)) if loaded else None,
        }

        # ── M365 Copilot (Graph pull and/or CSV export) ─────────────────
        if not total_licenses and has("billing_licences"):
            total_licenses = self._scalar(
                "SELECT SUM(total_licenses) FROM billing_licences WHERE product_title = 'Microsoft 365 Copilot'"
            ) or 0
        snap["total_licenses"] = total_licenses or None
        if has("m365_copilot_usage_graph", "m365_copilot_usage_csv"):
            enabled = self._scalar("SELECT COUNT(*) FROM m365_copilot_usage") or 0
            active = self._scalar(
                "SELECT COUNT(*) FROM m365_copilot_usage "
                "WHERE last_activity_date IS NOT NULL AND last_activity_date != ''"
            ) or 0
            row = self._conn.execute(f"""
                SELECT SUM({_USER_PROMPTS}),
                       SUM(COALESCE(copilot_chat, COALESCE(prompts_copilot_chat_work, 0)
                                                 + COALESCE(prompts_copilot_chat_web, 0))),
                       SUM(COALESCE(teams_chats, 0) + COALESCE(teams_meetings, 0)),
                       SUM(outlook), SUM(excel), SUM(word), SUM(powerpoint), SUM(onenote), SUM(loop),
                       MAX({_HAS_GRAPH})
                FROM m365_copilot_usage
            """).fetchone()
            total_prompts = row[0] or 0
            graph = bool(row[9])
            power_users = self._scalar(f"""
                WITH t AS (
                    SELECT {_USER_PROMPTS} AS total FROM m365_copilot_usage
                    WHERE last_activity_date IS NOT NULL AND last_activity_date != ''
                ), ranked AS (
                    SELECT ROW_NUMBER() OVER (ORDER BY total DESC) AS rn, COUNT(*) OVER () AS cnt FROM t
                )
                SELECT COUNT(*) FROM ranked WHERE rn * 5 <= cnt
            """) or 0
            snap.update({
                "enabled_users": enabled,
                "active_users": active,
                "activation_rate": _rate(enabled, total_licenses),
                "adoption_rate": _rate(active, enabled),
                "power_users": power_users,
                "total_prompts": total_prompts,
                "avg_prompts_per_user": round(total_prompts / active, 1) if active else None,
                "prompts_copilot_chat": row[1] or 0,
                # Per-app counts only exist in the Graph pull.
                "prompts_teams": row[2] if graph else None,
                "prompts_outlook": row[3] if graph else None,
                "prompts_excel": row[4] if graph else None,
                "prompts_word": row[5] if graph else None,
                "prompts_powerpoint": row[6] if graph else None,
                "prompts_onenote": row[7] if graph else None,
                "prompts_loop": row[8] if graph else None,
            })

        if has("m365_copilot_chat_usage"):
            row = self._conn.execute(
                "SELECT COUNT(*), SUM(COALESCE(prompts_submitted, 0) > 0), SUM(prompts_submitted) "
                "FROM m365_copilot_chat_usage"
            ).fetchone()
            snap.update({"chat_users": row[0], "chat_active_users": row[1], "chat_prompts": row[2]})

        if has("m365_connectors_users"):
            row = self._conn.execute(
                "SELECT COUNT(*), SUM(responses_received) FROM m365_connectors_users"
            ).fetchone()
            snap.update({"connector_users": row[0], "connector_responses": row[1]})

        if has("m365_usage_agents"):
            row = self._conn.execute(
                "SELECT SUM(COALESCE(responses_sent, 0) > 0), SUM(responses_sent) FROM m365_usage_agents"
            ).fetchone()
            snap.update({"m365_active_agents": row[0], "m365_agent_responses": row[1]})
        if has("m365_usage_users"):
            snap["m365_agent_users"] = self._scalar("SELECT COUNT(*) FROM m365_usage_users")

        if has("m365_cowork_usage"):
            row = self._conn.execute("SELECT COUNT(*), SUM(total_tasks) FROM m365_cowork_usage").fetchone()
            snap.update({"cowork_users": row[0], "cowork_tasks": row[1]})

        # ── Agent inventory + OTel conversations ─────────────────────────
        total_agents = self._scalar("SELECT COUNT(*) FROM pva_agents") or 0
        agents_with_owner = self._scalar(
            "SELECT COUNT(*) FROM pva_agents WHERE owner_id IS NOT NULL AND owner_id != ''"
        ) or 0
        otel = (
            "FROM conversation_events WHERE design_mode = 0 AND timestamp >= ? AND timestamp <= ?"
        )
        active_agents = self._scalar(
            f"SELECT COUNT(DISTINCT gen_ai_agent_id) {otel} "
            "AND gen_ai_agent_id IS NOT NULL AND gen_ai_agent_id != ''", cutoff, period_end_ts,
        ) or 0
        agent_adopters = self._scalar(
            f"SELECT COUNT(DISTINCT user_id) {otel} AND user_id IS NOT NULL AND user_id != ''",
            cutoff, period_end_ts,
        ) or 0
        enabled_users = snap.get("enabled_users")
        snap["total_agents"] = total_agents
        # Tenants without App Insights telemetry / Power Platform agent records
        # get blanks rather than misleading zeros.
        if self._scalar("SELECT EXISTS (SELECT 1 FROM conversation_events)"):
            snap.update({
                "active_agents": active_agents,
                "utilization_rate": _rate(active_agents, total_agents),
                "total_conversations": self._scalar(
                    f"SELECT COUNT(DISTINCT conversation_id) {otel}", cutoff, period_end_ts
                ) or 0,
                "agent_adopters": agent_adopters,
                "agent_adoption_pct": _rate(agent_adopters, enabled_users),
            })
        if self._scalar("SELECT EXISTS (SELECT 1 FROM dim_agent WHERE environment_id IS NOT NULL)"):
            snap.update({
                "agents_with_owner": agents_with_owner,
                "ownership_pct": _rate(agents_with_owner, total_agents),
            })
        if has("pva_environments"):
            env_counts = dict(self._conn.execute("""
                SELECT LOWER(COALESCE(e.sku, e.type, 'unknown')), COUNT(a.agent_id)
                FROM pva_agents a LEFT JOIN pva_environments e ON a.environment_id = e.environment_id
                GROUP BY 1
            """).fetchall())
            production = env_counts.get("production", 0)
            snap.update({
                "production_agents": production,
                "non_prod_agents": total_agents - production,
                "env_default": env_counts.get("default", 0),
                "env_developer": env_counts.get("developer", 0),
                "env_teams": env_counts.get("teams", env_counts.get("microsoftteams", 0)),
                "env_production": production,
                "env_sandbox": env_counts.get("sandbox", 0),
                "env_trial": env_counts.get("trial", 0),
            })

        # ── Viva Copilot Adoption (weekly history, trailing window) ──────
        viva_end = self._scalar(
            "SELECT MAX(adoption_last_date) FROM dim_copilot_person WHERE adoption_last_date <= ?",
            period_end,
        )
        if viva_end:
            viva_start = _days_before(viva_end, _TRAILING_DAYS - 1)
            row = self._conn.execute("""
                SELECT COUNT(DISTINCT CASE WHEN total_copilot_actions > 0 THEN person_id END),
                       SUM(total_copilot_actions)
                FROM fact_copilot_actions_per_person
                WHERE in_adoption_report = 1 AND metric_date BETWEEN ? AND ?
            """, (viva_start, viva_end)).fetchone()
            snap.update({
                "viva_enabled_users": self._scalar(
                    "SELECT COUNT(*) FROM dim_copilot_person "
                    "WHERE adoption_first_date <= ? AND adoption_last_date >= ?", viva_end, viva_start,
                ),
                "viva_active_users": row[0],
                "viva_total_actions": row[1],
            })

        # ── Copilot Studio agent sessions (daily history, trailing window) ─
        cs_end = self._scalar(
            "SELECT MAX(metric_date) FROM viva_reports_cs_session_metrics WHERE metric_date <= ?", period_end,
        )
        if cs_end:
            cs_start = _days_before(cs_end, _TRAILING_DAYS - 1)
            row = self._conn.execute("""
                SELECT SUM(total_sessions), SUM(resolved_sessions), SUM(escalated_sessions),
                       SUM(abandoned_sessions),
                       SUM(COALESCE(csat_1,0) + 2*COALESCE(csat_2,0) + 3*COALESCE(csat_3,0)
                           + 4*COALESCE(csat_4,0) + 5*COALESCE(csat_5,0)),
                       SUM(COALESCE(csat_1,0) + COALESCE(csat_2,0) + COALESCE(csat_3,0)
                           + COALESCE(csat_4,0) + COALESCE(csat_5,0))
                FROM viva_reports_cs_session_metrics WHERE metric_date BETWEEN ? AND ?
            """, (cs_start, cs_end)).fetchone()
            sessions = row[0] or 0
            snap.update({
                "cs_sessions": sessions,
                "cs_resolution_rate": _rate(row[1] or 0, sessions),
                "cs_escalation_rate": _rate(row[2] or 0, sessions),
                "cs_abandon_rate": _rate(row[3] or 0, sessions),
                "cs_csat_avg": round(row[4] / row[5], 2) if row[5] else None,
                "cs_peak_wau": self._scalar("""
                    SELECT MAX(wau) FROM (
                        SELECT SUM(active_user_count) AS wau FROM viva_reports_cs_weekly_active_users
                        WHERE start_date BETWEEN ? AND ? GROUP BY start_date
                    )""", cs_start, cs_end),
            })

        # ── Credits ──────────────────────────────────────────────────────
        if has("tokenomics_entitlement_consumption"):
            row = self._conn.execute(
                "SELECT SUM(entitled_quantity), SUM(prepaid_consumed_quantity), SUM(payg_consumed_quantity) "
                "FROM tokenomics_entitlement_consumption WHERE usage_date <= ?", (period_end,)
            ).fetchone()
            entitled, prepaid, payg = (v or 0 for v in row)
            snap.update({
                "credits_entitled": round(entitled, 1),
                "credits_prepaid": round(prepaid, 1),
                "credits_payg": round(payg, 1),
                "credits_pct_used": _rate(prepaid + payg, entitled),
            })
        if has("tokenomics_capacity_consumption"):
            row = self._conn.execute(
                "SELECT SUM(consumed_quantity), COUNT(DISTINCT substr(consumption_date, 1, 10)) "
                "FROM tokenomics_capacity_consumption WHERE consumption_date <= ?", (period_end_ts,)
            ).fetchone()
            total_cap = row[0] or 0
            snap.update({
                "capacity_total": round(total_cap, 1),
                "capacity_avg_daily": round(total_cap / row[1], 1) if row[1] else None,
            })
        cons_end = self._scalar(
            "SELECT MAX(metric_date) FROM viva_consumption_person_service_credits WHERE metric_date <= ?",
            period_end,
        )
        if cons_end:
            snap["consumption_credits"] = round(self._scalar(
                "SELECT SUM(total_credits_used) FROM viva_consumption_person_service_credits "
                "WHERE metric_date BETWEEN ? AND ?", _days_before(cons_end, _TRAILING_DAYS - 1), cons_end,
            ) or 0, 1)
        gh_end = self._scalar(
            "SELECT MAX(metric_date) FROM viva_consumption_github_credits WHERE metric_date <= ?", period_end,
        )
        if gh_end:
            row = self._conn.execute(
                "SELECT COUNT(DISTINCT person_id), SUM(total_credits_used) FROM viva_consumption_github_credits "
                "WHERE metric_date BETWEEN ? AND ?", (_days_before(gh_end, _TRAILING_DAYS - 1), gh_end),
            ).fetchone()
            snap.update({"github_users": row[0], "github_credits": round(row[1] or 0, 1)})

        return snap

    def upsert_kpi_snapshot(self, snap: dict) -> None:
        """Insert or replace a snapshot. Period snapshots share an id per
        period, so re-running a month replaces its row."""
        columns = [
            row[1] for row in self._conn.execute("PRAGMA table_info(kpi_snapshots)").fetchall()
            if row[1] in snap
        ]
        with self._conn:
            self._conn.execute(
                f"INSERT OR REPLACE INTO kpi_snapshots ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                tuple(snap[c] for c in columns),
            )

    def fetch_kpi_snapshots(self) -> list[dict]:
        """Newest first. Snapshots from before period keying (period IS NULL)
        sort by the date they were taken."""
        rows = self._conn.execute(
            "SELECT * FROM kpi_snapshots "
            "ORDER BY COALESCE(period_end, substr(snapshot_date, 1, 10)) DESC, snapshot_date DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Trends (computed from dated history at export time)
    # ------------------------------------------------------------------

    def fetch_trend_copilot_weekly(self) -> list[dict]:
        """Weekly M365 Copilot activity from the Viva Adoption report.
        enabled_users counts people whose Adoption-report span covers the week
        (weekly enabled rows are pruned once they have no activity)."""
        rows = self._conn.execute("""
            SELECT metric_date AS week,
                   (SELECT COUNT(*) FROM dim_copilot_person p
                    WHERE p.adoption_first_date <= f.metric_date
                      AND p.adoption_last_date >= f.metric_date) AS enabled_users,
                   COUNT(DISTINCT CASE WHEN total_copilot_actions > 0 THEN person_id END) AS active_users,
                   SUM(total_copilot_actions) AS total_actions,
                   SUM(actions_copilot_chat) AS chat_actions,
                   SUM(actions_teams) AS teams_actions,
                   SUM(actions_outlook) AS outlook_actions,
                   SUM(actions_word) AS word_actions,
                   SUM(actions_excel) AS excel_actions,
                   SUM(actions_powerpoint) AS powerpoint_actions
            FROM fact_copilot_actions_per_person f
            WHERE in_adoption_report = 1
            GROUP BY metric_date
            ORDER BY metric_date
        """).fetchall()
        return [dict(r) for r in rows]

    def fetch_trend_agent_sessions_monthly(self) -> list[dict]:
        """Monthly Copilot Studio agent outcomes (Viva Copilot Studio report)."""
        rows = self._conn.execute("""
            WITH s AS (
                SELECT substr(metric_date, 1, 7) AS month,
                       COUNT(DISTINCT agent_id) AS agents,
                       SUM(total_sessions) AS sessions, SUM(engaged_sessions) AS engaged,
                       SUM(resolved_sessions) AS resolved, SUM(escalated_sessions) AS escalated,
                       SUM(abandoned_sessions) AS abandoned,
                       SUM(COALESCE(csat_1,0) + 2*COALESCE(csat_2,0) + 3*COALESCE(csat_3,0)
                           + 4*COALESCE(csat_4,0) + 5*COALESCE(csat_5,0)) AS csat_points,
                       SUM(COALESCE(csat_1,0) + COALESCE(csat_2,0) + COALESCE(csat_3,0)
                           + COALESCE(csat_4,0) + COALESCE(csat_5,0)) AS csat_n
                FROM viva_reports_cs_session_metrics GROUP BY 1
            ), w AS (
                SELECT substr(start_date, 1, 7) AS month, MAX(wau) AS peak_wau
                FROM (SELECT start_date, SUM(active_user_count) AS wau
                      FROM viva_reports_cs_weekly_active_users GROUP BY start_date)
                GROUP BY 1
            ), a AS (
                SELECT substr(metric_date, 1, 7) AS month,
                       SUM(total_runs) AS autonomous_runs, SUM(successful_runs) AS autonomous_ok
                FROM viva_reports_cs_autonomous_metrics GROUP BY 1
            )
            SELECT s.month, s.agents, s.sessions, s.engaged,
                   ROUND(s.resolved  * 100.0 / NULLIF(s.sessions, 0), 1) AS resolution_rate,
                   ROUND(s.escalated * 100.0 / NULLIF(s.sessions, 0), 1) AS escalation_rate,
                   ROUND(s.abandoned * 100.0 / NULLIF(s.sessions, 0), 1) AS abandon_rate,
                   ROUND(s.csat_points * 1.0 / NULLIF(s.csat_n, 0), 2) AS csat_avg,
                   w.peak_wau, a.autonomous_runs,
                   ROUND(a.autonomous_ok * 100.0 / NULLIF(a.autonomous_runs, 0), 1) AS autonomous_success_rate
            FROM s LEFT JOIN w USING (month) LEFT JOIN a USING (month)
            ORDER BY s.month
        """).fetchall()
        return [dict(r) for r in rows]

    def fetch_trend_credits_monthly(self) -> list[dict]:
        """Monthly credit burn: Power Platform capacity consumption, Viva
        Consumption credits (weekly export), and the daily export's M365
        service and GitHub AI credits."""
        rows = self._conn.execute("""
            WITH cap AS (
                SELECT substr(consumption_date, 1, 7) AS month,
                       SUM(CASE WHEN is_billable THEN consumed_quantity ELSE 0 END) AS billable,
                       SUM(CASE WHEN is_billable THEN 0 ELSE consumed_quantity END) AS non_billable
                FROM tokenomics_capacity_consumption GROUP BY 1
            ), viva AS (
                SELECT substr(metric_date, 1, 7) AS month, SUM(total_credits_used) AS consumption_credits,
                       COUNT(DISTINCT person_id) AS consumption_people
                FROM viva_consumption_person_service_credits GROUP BY 1
            ), daily AS (
                SELECT substr(metric_date, 1, 7) AS month, SUM(total_credits_used) AS m365_daily_credits
                FROM viva_consumption_person_daily_credits GROUP BY 1
            ), gh AS (
                SELECT substr(metric_date, 1, 7) AS month, SUM(total_credits_used) AS github_credits,
                       COUNT(DISTINCT person_id) AS github_people
                FROM viva_consumption_github_credits GROUP BY 1
            ), months AS (
                SELECT month FROM cap UNION SELECT month FROM viva
                UNION SELECT month FROM daily UNION SELECT month FROM gh
            )
            SELECT m.month,
                   ROUND(cap.billable, 1) AS capacity_billable,
                   ROUND(cap.non_billable, 1) AS capacity_non_billable,
                   ROUND(viva.consumption_credits, 1) AS consumption_credits,
                   viva.consumption_people,
                   ROUND(daily.m365_daily_credits, 1) AS m365_daily_credits,
                   ROUND(gh.github_credits, 1) AS github_credits,
                   gh.github_people
            FROM months m LEFT JOIN cap USING (month) LEFT JOIN viva USING (month)
            LEFT JOIN daily USING (month) LEFT JOIN gh USING (month)
            WHERE m.month IS NOT NULL
            ORDER BY m.month
        """).fetchall()
        return [dict(r) for r in rows]

    def fetch_trend_services_monthly(self) -> list[dict]:
        """Monthly peak daily active users per M365 service (Office 365
        active user counts export)."""
        rows = self._conn.execute("""
            SELECT substr(metric_date, 1, 7) AS month,
                   MAX(CASE WHEN service_name = 'office365'  THEN active_count END) AS office365,
                   MAX(CASE WHEN service_name = 'exchange'   THEN active_count END) AS exchange,
                   MAX(CASE WHEN service_name = 'teams'      THEN active_count END) AS teams,
                   MAX(CASE WHEN service_name = 'sharepoint' THEN active_count END) AS sharepoint,
                   MAX(CASE WHEN service_name = 'onedrive'   THEN active_count END) AS onedrive
            FROM fact_service_usage WHERE metric_source = 'counts'
            GROUP BY 1 ORDER BY 1
        """).fetchall()
        return [dict(r) for r in rows]

    def fetch_import_status(self) -> list[dict]:
        """Latest load of each table and whether it came from the most recent
        sync run (anything else is carried forward from an earlier run)."""
        rows = self._conn.execute("""
            WITH latest_run AS (SELECT run_id FROM sync_runs ORDER BY started_at DESC LIMIT 1),
            latest AS (
                SELECT table_name, MAX(import_id) AS import_id FROM import_log GROUP BY table_name
            )
            SELECT l.table_name, l.mode, l.row_count, l.imported_at,
                   (l.run_id = (SELECT run_id FROM latest_run)) AS current_run
            FROM import_log l JOIN latest USING (table_name, import_id)
            ORDER BY current_run, l.table_name
        """).fetchall()
        return [dict(r) for r in rows]
