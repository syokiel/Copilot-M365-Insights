"""Viva Insights: person/org insights API, Copilot Studio analytics exports, Copilot Adoption/Impact and the Consumption dashboard."""

from src.store._schema import (
    _COPILOT_ACTION_COLUMNS,
    _COPILOT_WORK_PATTERN_COLUMNS,
    _ZERO_PRUNE_COLUMNS,
)


class VivaMixin:
    def upsert_viva_person_insights(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('viva_person_insights', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_person_insights
                    (row_id, user_id, week_start, week_end,
                     focus_hours, meeting_hours, email_hours, chat_hours, after_hours,
                     fetched_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (r["row_id"], r["user_id"], r["week_start"], r.get("week_end"),
                     r.get("focus_hours", 0), r.get("meeting_hours", 0),
                     r.get("email_hours", 0), r.get("chat_hours", 0),
                     r.get("after_hours", 0), r.get("fetched_at")),
                )
                written += cur.rowcount
        return written

    def fetch_viva_person_insights(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_person_insights ORDER BY week_start DESC, user_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_org_insights(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('viva_org_insights', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_org_insights
                    (row_id, metric_date, period,
                     avg_focus_hours, avg_meeting_hours, avg_email_hours,
                     avg_chat_hours, avg_after_hours, population_size, fetched_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (r["row_id"], r["metric_date"], r.get("period"),
                     r.get("avg_focus_hours"), r.get("avg_meeting_hours"),
                     r.get("avg_email_hours"), r.get("avg_chat_hours"),
                     r.get("avg_after_hours"), r.get("population_size"),
                     r.get("fetched_at")),
                )
                written += cur.rowcount
        return written

    def upsert_viva_reports_cs_session_metrics(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('viva_reports_cs_session_metrics', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_reports_cs_session_metrics VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r['agent_id'], r['metric_date'],
                     r.get('total_sessions'), r.get('resolved_sessions'), r.get('escalated_sessions'),
                     r.get('abandoned_sessions'), r.get('engaged_sessions'), r.get('unengaged_sessions'),
                     r.get('csat_responses'), r.get('csat_1'), r.get('csat_2'), r.get('csat_3'),
                     r.get('csat_4'), r.get('csat_5'),
                     r.get('avg_duration_all'), r.get('avg_duration_unengaged'), r.get('avg_duration_engaged'),
                     r.get('avg_duration_resolved'), r.get('avg_duration_escalated'), r.get('avg_duration_abandoned'),
                     r.get('ks_engaged'), r.get('ks_unengaged'), r.get('ks_resolved'),
                     r.get('ks_escalated'), r.get('ks_abandoned')),
                )
                written += cur.rowcount
        return written

    def fetch_viva_reports_cs_session_metrics(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_reports_cs_session_metrics ORDER BY metric_date DESC, agent_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_reports_cs_topic_metrics(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('viva_reports_cs_topic_metrics', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_reports_cs_topic_metrics VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r['agent_id'], r['topic_id'], r.get('topic_name'), r['metric_date'],
                     r.get('total_sessions'), r.get('resolved_sessions'), r.get('escalated_sessions'),
                     r.get('abandoned_sessions'), r.get('engaged_sessions'), r.get('unengaged_sessions'),
                     r.get('csat_responses'), r.get('csat_1'), r.get('csat_2'), r.get('csat_3'),
                     r.get('csat_4'), r.get('csat_5')),
                )
                written += cur.rowcount
        return written

    def fetch_viva_reports_cs_topic_metrics(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_reports_cs_topic_metrics ORDER BY metric_date DESC, agent_id, topic_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_reports_cs_knowledge_source_metrics(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('viva_reports_cs_knowledge_source_metrics', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_reports_cs_knowledge_source_metrics VALUES
                    (?,?,?,?,?,?,?,?,?,?,?)""",
                    (r['agent_id'], r['source_type'], r['metric_date'],
                     r.get('count_total'), r.get('count_unengaged'), r.get('count_engaged'),
                     r.get('count_resolved'), r.get('count_escalated'), r.get('count_abandoned'),
                     r.get('count_autonomous'), r.get('count_successful_autonomous')),
                )
                written += cur.rowcount
        return written

    def upsert_viva_reports_cs_autonomous_metrics(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('viva_reports_cs_autonomous_metrics', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_reports_cs_autonomous_metrics VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r['agent_id'], r['metric_date'],
                     r.get('total_runs'), r.get('successful_runs'), r.get('failed_runs'),
                     r.get('total_duration'), r.get('successful_duration'), r.get('failed_duration'),
                     r.get('ks_successful'), r.get('ks_failed'),
                     r.get('actions_successful'), r.get('actions_failed'),
                     r.get('no_op_successful'), r.get('no_op_failed')),
                )
                written += cur.rowcount
        return written

    def fetch_viva_reports_cs_autonomous_metrics(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_reports_cs_autonomous_metrics ORDER BY metric_date DESC, agent_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_reports_cs_autonomous_trigger_metrics(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('viva_reports_cs_autonomous_trigger_metrics', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_reports_cs_autonomous_trigger_metrics VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r['agent_id'], r['trigger_schema_name'], r['metric_date'],
                     r.get('total_runs'), r.get('successful_runs'), r.get('failed_runs'),
                     r.get('total_duration'), r.get('successful_duration'), r.get('failed_duration'),
                     r.get('ks_successful'), r.get('ks_failed'),
                     r.get('actions_successful'), r.get('actions_failed'),
                     r.get('no_op_successful'), r.get('no_op_failed')),
                )
                written += cur.rowcount
        return written

    def upsert_viva_reports_cs_action_metrics(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('viva_reports_cs_action_metrics', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_reports_cs_action_metrics VALUES (?,?,?,?,?,?,?)""",
                    (r['agent_id'], r['action_schema_name'], r['metric_date'],
                     r.get('total_runs'), r.get('successful_actions_in_runs'),
                     r.get('actions_in_successful_runs'), r.get('successful_actions_in_successful_runs')),
                )
                written += cur.rowcount
        return written

    def fetch_viva_reports_cs_action_metrics(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_reports_cs_action_metrics ORDER BY metric_date DESC, agent_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_reports_cs_weekly_active_users(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('viva_reports_cs_weekly_active_users', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_reports_cs_weekly_active_users VALUES (?,?,?)""",
                    (r['agent_id'], r['start_date'], r.get('active_user_count')),
                )
                written += cur.rowcount
        return written

    def fetch_viva_reports_cs_weekly_active_users(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_reports_cs_weekly_active_users ORDER BY start_date DESC, agent_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_reports_cs_extended_metadata(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('viva_reports_cs_extended_metadata', rows, snapshot=True)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_reports_cs_extended_metadata VALUES (?,?,?)""",
                    (r['agent_id'], r.get('aad_tenant_id'), r.get('roi_configuration')),
                )
                written += cur.rowcount
        return written

    def _upsert_copilot_actions(self, r: dict, source_col: str) -> int:
        """Shared by upsert_viva_reports_copilot_adoption/_impact: COALESCE-
        upsert the columns both CSV exports can supply into
        fact_copilot_actions_per_person, and flag which source wrote it via
        source_col ('in_adoption_report' or 'in_impact_report')."""
        cols = _COPILOT_ACTION_COLUMNS
        col_list = ", ".join(("person_id", "metric_date") + cols + (source_col,))
        placeholders = ", ".join(["?"] * (2 + len(cols) + 1))
        set_clause = ",\n                        ".join(
            f"{c} = COALESCE(excluded.{c}, fact_copilot_actions_per_person.{c})" for c in cols
        )
        cur = self._conn.execute(
            f"""
            INSERT INTO fact_copilot_actions_per_person ({col_list})
            VALUES ({placeholders})
            ON CONFLICT(person_id, metric_date) DO UPDATE SET
                {set_clause},
                {source_col} = 1
            """,
            (r['person_id'], r['metric_date'], *(r.get(c) for c in cols), 1),
        )
        return cur.rowcount

    def _upsert_copilot_work_patterns(self, r: dict) -> None:
        pat_cols = _COPILOT_WORK_PATTERN_COLUMNS
        col_list = ", ".join(("person_id", "metric_date") + pat_cols)
        set_clause = ",\n                    ".join(f"{c} = excluded.{c}" for c in pat_cols)
        self._conn.execute(
            f"""
            INSERT INTO fact_copilot_work_patterns ({col_list})
            VALUES ({", ".join(["?"] * (2 + len(pat_cols)))})
            ON CONFLICT(person_id, metric_date) DO UPDATE SET
                {set_clause}
            """,
            (r['person_id'], r['metric_date'], *(r.get(c) for c in pat_cols)),
        )

    def upsert_viva_reports_copilot_adoption(self, rows: list[dict]) -> int:
        """viva_reports_copilot_adoption is a compatibility view over
        fact_copilot_actions_per_person."""
        written = 0
        with self._conn:
            self._begin_import('fact_copilot_actions_per_person', rows, snapshot=False)
            for r in rows:
                written += self._upsert_copilot_actions(r, "in_adoption_report")
        return written

    def fetch_viva_reports_copilot_adoption(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_reports_copilot_adoption ORDER BY metric_date DESC, person_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_reports_copilot_impact(self, rows: list[dict]) -> int:
        """viva_reports_copilot_impact is a compatibility view over
        fact_copilot_work_patterns (Impact-only work-pattern columns) joined to
        fact_copilot_actions_per_person (shared action columns)."""
        written = 0
        with self._conn:
            self._begin_import('fact_copilot_work_patterns', rows, snapshot=False)
            for r in rows:
                written += self._upsert_copilot_actions(r, "in_impact_report")
                self._upsert_copilot_work_patterns(r)
        return written

    def fetch_viva_reports_copilot_impact(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM viva_reports_copilot_impact ORDER BY metric_date DESC, person_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def _prune_zero_copilot_actions(self) -> None:
        """Drop person-weeks with no Copilot activity from
        fact_copilot_actions_per_person (most Adoption/Impact rows for
        licensed-but-idle users). Each person's report date span is folded
        into dim_copilot_person first, so "enabled users" counts survive.
        Runs inside the caller's transaction."""
        self._conn.execute("""
            INSERT INTO dim_copilot_person
                (person_id, organization, adoption_first_date, adoption_last_date,
                 impact_first_date, impact_last_date)
            SELECT person_id, MAX(organization),
                   MIN(CASE WHEN in_adoption_report = 1 THEN metric_date END),
                   MAX(CASE WHEN in_adoption_report = 1 THEN metric_date END),
                   MIN(CASE WHEN in_impact_report = 1 THEN metric_date END),
                   MAX(CASE WHEN in_impact_report = 1 THEN metric_date END)
            FROM fact_copilot_actions_per_person
            WHERE true
            GROUP BY person_id
            ON CONFLICT(person_id) DO UPDATE SET
                organization        = COALESCE(excluded.organization, dim_copilot_person.organization),
                adoption_first_date = MIN(COALESCE(excluded.adoption_first_date, dim_copilot_person.adoption_first_date),
                                          COALESCE(dim_copilot_person.adoption_first_date, excluded.adoption_first_date)),
                adoption_last_date  = MAX(COALESCE(excluded.adoption_last_date, dim_copilot_person.adoption_last_date),
                                          COALESCE(dim_copilot_person.adoption_last_date, excluded.adoption_last_date)),
                impact_first_date   = MIN(COALESCE(excluded.impact_first_date, dim_copilot_person.impact_first_date),
                                          COALESCE(dim_copilot_person.impact_first_date, excluded.impact_first_date)),
                impact_last_date    = MAX(COALESCE(excluded.impact_last_date, dim_copilot_person.impact_last_date),
                                          COALESCE(dim_copilot_person.impact_last_date, excluded.impact_last_date))
        """)
        all_zero = " AND ".join(f"COALESCE({c}, 0) = 0" for c in _ZERO_PRUNE_COLUMNS)
        self._conn.execute(f"DELETE FROM fact_copilot_actions_per_person WHERE {all_zero}")

    def fetch_copilot_people(self) -> list[dict]:
        """Per-person Adoption/Impact date spans (see _prune_zero_copilot_actions)."""
        rows = self._conn.execute("SELECT * FROM dim_copilot_person").fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_consumption_people(self, rows: list[dict]) -> int:
        """People dimension shared by the weekly and daily consumption exports.
        Merged, not replaced: the daily export's file has no organization /
        function columns, so it must not blank what the weekly one supplied."""
        written = 0
        with self._conn:
            self._begin_import('viva_consumption_people', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT INTO viva_consumption_people VALUES (?,?,?,?)
                    ON CONFLICT(people_historical_id) DO UPDATE SET
                        organization        = COALESCE(excluded.organization, viva_consumption_people.organization),
                        function_type       = COALESCE(excluded.function_type, viva_consumption_people.function_type),
                        is_copilot_licensed = excluded.is_copilot_licensed""",
                    (
                        r.get('people_historical_id'), r.get('organization') or None,
                        r.get('function_type') or None, r.get('is_copilot_licensed'),
                    ),
                )
                written += cur.rowcount
        return written

    def upsert_viva_consumption_person_service_credits(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('viva_consumption_person_service_credits', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_consumption_person_service_credits VALUES
                    (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        r.get('person_id'), r.get('service_id'), r.get('service_name'),
                        r.get('spending_policy_id'), r.get('metric_date'),
                        r.get('session_count'), r.get('spending_policy_limit'),
                        r.get('total_credits_used'), r.get('user_limit'),
                        r.get('people_historical_id'),
                    ),
                )
                written += cur.rowcount
        return written

    def upsert_viva_consumption_spending_policy(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            # Merged: both consumption exports carry the same policy list.
            self._begin_import('viva_consumption_spending_policy', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_consumption_spending_policy VALUES (?,?,?,?,?)""",
                    (
                        r.get('spending_policy_id'), r.get('name'),
                        r.get('plan_limit'), r.get('user_limit'), r.get('included_services'),
                    ),
                )
                written += cur.rowcount
        return written

    def upsert_viva_consumption_person_daily_credits(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('viva_consumption_person_daily_credits', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_consumption_person_daily_credits VALUES
                    (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        r.get('person_id'), r.get('service_id'), r.get('service_name'),
                        r.get('spending_policy_id'), r.get('metric_date'),
                        r.get('session_count'), r.get('spending_policy_limit'),
                        r.get('total_credits_used'), r.get('user_limit'),
                        r.get('people_historical_id'),
                    ),
                )
                written += cur.rowcount
        return written

    def upsert_viva_consumption_github_credits(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('viva_consumption_github_credits', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO viva_consumption_github_credits VALUES (?,?,?,?)""",
                    (r.get('person_id'), r.get('metric_date'),
                     r.get('total_credits_used'), r.get('people_historical_id')),
                )
                written += cur.rowcount
        return written

    def fetch_consumption_daily_totals(self) -> list[dict]:
        """Daily credits by service from the daily export: M365 services
        (Cowork, WorkIQ, …) plus GitHub AI."""
        rows = self._conn.execute("""
            SELECT metric_date, COALESCE(NULLIF(service_name, ''), 'Unknown') AS service,
                   COUNT(DISTINCT person_id) AS people, SUM(session_count) AS sessions,
                   ROUND(SUM(total_credits_used), 2) AS credits
            FROM viva_consumption_person_daily_credits GROUP BY 1, 2
            UNION ALL
            SELECT metric_date, 'GitHub AI', COUNT(DISTINCT person_id), NULL,
                   ROUND(SUM(total_credits_used), 2)
            FROM viva_consumption_github_credits GROUP BY 1
            ORDER BY 1, 2
        """).fetchall()
        return [dict(r) for r in rows]

    def fetch_consumption_weekly_totals(self) -> list[dict]:
        """Weekly (Monday-start) credits and distinct people by service from
        the daily export — people are counted once per week, which summing
        the daily totals can't do."""
        rows = self._conn.execute("""
            WITH d AS (
                SELECT date(metric_date, '-6 days', 'weekday 1') AS week,
                       COALESCE(NULLIF(service_name, ''), 'Unknown') AS service,
                       person_id, total_credits_used, metric_date
                FROM viva_consumption_person_daily_credits
                UNION ALL
                SELECT date(metric_date, '-6 days', 'weekday 1'), 'GitHub AI',
                       person_id, total_credits_used, metric_date
                FROM viva_consumption_github_credits
            )
            SELECT week, service, COUNT(DISTINCT person_id) AS people,
                   COUNT(DISTINCT metric_date) AS days,
                   ROUND(SUM(total_credits_used), 2) AS credits
            FROM d GROUP BY week, service ORDER BY week, service
        """).fetchall()
        return [dict(r) for r in rows]

    def fetch_consumption_daily_detail(self) -> list[dict]:
        """Per-person daily M365 service credits (e.g. Cowork) with licence flag."""
        rows = self._conn.execute("""
            SELECT c.metric_date, c.person_id, c.service_name, c.session_count,
                   c.total_credits_used, c.user_limit, s.name AS spending_policy,
                   p.organization, p.is_copilot_licensed
            FROM viva_consumption_person_daily_credits c
            LEFT JOIN viva_consumption_people p ON p.people_historical_id = c.people_historical_id
            LEFT JOIN viva_consumption_spending_policy s ON s.spending_policy_id = c.spending_policy_id
            ORDER BY c.metric_date DESC, c.total_credits_used DESC
        """).fetchall()
        return [dict(r) for r in rows]

    def fetch_github_credits_by_person(self) -> list[dict]:
        """Per-person GitHub AI credit rollup across all imported days."""
        rows = self._conn.execute("""
            SELECT g.person_id, MAX(p.is_copilot_licensed) AS is_copilot_licensed,
                   MAX(p.organization) AS organization,
                   COUNT(*) AS active_days, ROUND(SUM(g.total_credits_used), 2) AS total_credits,
                   ROUND(AVG(g.total_credits_used), 2) AS avg_credits_per_day,
                   MIN(g.metric_date) AS first_date, MAX(g.metric_date) AS last_date
            FROM viva_consumption_github_credits g
            LEFT JOIN viva_consumption_people p ON p.people_historical_id = g.people_historical_id
            GROUP BY g.person_id
            ORDER BY total_credits DESC
        """).fetchall()
        return [dict(r) for r in rows]

    def fetch_viva_consumption_detail(self) -> list[dict]:
        """Person/service/date credit rows joined with org/function context.
        Feeds both the Tokenomics_Consumption_Detail sheet and the
        'Credits by Service' section of Tokenomics_Summary.
        """
        rows = self._conn.execute(
            """
            SELECT c.*, p.organization, p.function_type, p.is_copilot_licensed
            FROM viva_consumption_person_service_credits c
            LEFT JOIN viva_consumption_people p ON p.people_historical_id = c.people_historical_id
            ORDER BY c.total_credits_used DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

