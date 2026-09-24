"""Agent dimension (dim_agent), Power Platform environments/publishers/DLP/solutions, Entra users, and the journey/persona experience model."""
import json


class AgentsMixin:
    def upsert_agents(self, agents: list[dict]) -> int:
        """Insert or update dim_agent from Dataverse/PP-Admin agent records
        (pva_agents is a compatibility view over dim_agent). Multiple callers
        of this method supply different column subsets (dataverse.py vs.
        powerplatform_admin.py) — COALESCE preserves whichever source already
        populated a column instead of the previous full-row REPLACE, which
        would null out one source's columns when the other ran afterward.
        Returns count of rows written."""
        _known = {
            "id", "botId", "name", "displayName", "schemaName",
            "environmentId", "createdDateTime", "modifiedDateTime",
            "publishedDateTime", "createdBy", "ownerId", "createdIn",
            "aiModel",
        }
        written = 0
        with self._conn:
            self._begin_import('dim_agent', agents, snapshot=False)
            for b in agents:
                cur = self._conn.execute(
                    """
                    INSERT INTO dim_agent
                    (agent_id, display_name, schema_name, environment_id,
                     created_at, modified_at, published_at,
                     created_by, owner_id, created_in, ai_model, properties)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(agent_id) DO UPDATE SET
                        display_name   = COALESCE(excluded.display_name,   dim_agent.display_name),
                        schema_name    = COALESCE(excluded.schema_name,    dim_agent.schema_name),
                        environment_id = COALESCE(excluded.environment_id, dim_agent.environment_id),
                        created_at     = COALESCE(excluded.created_at,     dim_agent.created_at),
                        modified_at    = COALESCE(excluded.modified_at,    dim_agent.modified_at),
                        published_at   = COALESCE(excluded.published_at,   dim_agent.published_at),
                        created_by     = COALESCE(excluded.created_by,     dim_agent.created_by),
                        owner_id       = COALESCE(excluded.owner_id,       dim_agent.owner_id),
                        created_in     = COALESCE(excluded.created_in,     dim_agent.created_in),
                        ai_model       = COALESCE(excluded.ai_model,       dim_agent.ai_model),
                        properties     = COALESCE(excluded.properties,     dim_agent.properties)
                    """,
                    (
                        b.get("id") or b.get("botId") or None,
                        b.get("name") or b.get("displayName") or None,
                        b.get("schemaName") or None,
                        b.get("environmentId") or None,
                        b.get("createdDateTime") or None,
                        b.get("modifiedDateTime") or None,
                        b.get("publishedDateTime") or None,
                        b.get("createdBy") or None,
                        b.get("ownerId") or None,
                        b.get("createdIn") or None,
                        b.get("aiModel") or None,
                        json.dumps({k: v for k, v in b.items() if k not in _known}),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_agents(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT agent_id, display_name, schema_name, environment_id, "
            "created_at, modified_at, published_at, created_by, owner_id, created_in, ai_model "
            "FROM dim_agent ORDER BY display_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_viva_reports_cs_copilot_agents(self, rows: list[dict]) -> int:
        """Insert or update dim_agent's Viva-report-derived columns
        (viva_reports_cs_copilot_agents is a compatibility view over
        dim_agent, filtered to in_viva_report=1). in_viva_report is treated as
        a snapshot: agents missing from the latest report lose the flag (their
        descriptive columns are kept). Returns rows written."""
        written = 0
        with self._conn:
            self._begin_import('dim_agent', rows, snapshot=False, params=('viva_cs',))
            if rows:
                self._conn.execute("UPDATE dim_agent SET in_viva_report = 0 WHERE in_viva_report = 1")
            for r in rows:
                cur = self._conn.execute(
                    """
                    INSERT INTO dim_agent
                    (agent_id, display_name, description, surface, mode,
                     categories, agent_type, is_included, excluded_reason, in_viva_report)
                    VALUES (?,?,?,?,?,?,?,?,?,1)
                    ON CONFLICT(agent_id) DO UPDATE SET
                        display_name    = COALESCE(excluded.display_name,    dim_agent.display_name),
                        description     = COALESCE(excluded.description,     dim_agent.description),
                        surface         = COALESCE(excluded.surface,         dim_agent.surface),
                        mode            = COALESCE(excluded.mode,            dim_agent.mode),
                        categories      = COALESCE(excluded.categories,      dim_agent.categories),
                        agent_type      = COALESCE(excluded.agent_type,      dim_agent.agent_type),
                        is_included     = COALESCE(excluded.is_included,     dim_agent.is_included),
                        excluded_reason = COALESCE(excluded.excluded_reason, dim_agent.excluded_reason),
                        in_viva_report  = 1
                    """,
                    (r['agent_id'], r.get('agent_name') or None, r.get('description') or None,
                     r.get('surface') or None, r.get('mode') or None, r.get('categories') or None,
                     r.get('agent_type') or None, r.get('is_included', 1), r.get('excluded_reason') or None),
                )
                written += cur.rowcount
        return written

    def fetch_viva_reports_cs_copilot_agents(self) -> dict[str, dict]:
        """Returns {agent_id: row_dict} for O(1) lookup in sheet writers."""
        rows = self._conn.execute(
            "SELECT agent_id, display_name AS agent_name, description, surface, mode, "
            "categories, agent_type, is_included FROM dim_agent WHERE in_viva_report = 1"
        ).fetchall()
        return {r['agent_id']: dict(r) for r in rows}

    def upsert_environments(self, envs: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('pva_environments', envs, snapshot=True)
            for e in envs:
                cur = self._conn.execute(
                    "INSERT OR REPLACE INTO pva_environments VALUES (?,?,?,?,?,?,?,?,?)",
                    (e.get("environment_id", ""), e.get("display_name", ""), e.get("type", ""),
                     e.get("region", ""), e.get("state", ""), e.get("created_at", ""),
                     e.get("modified_at", ""), e.get("sku", ""), e.get("dataverse_url", "")),
                )
                written += cur.rowcount
        return written

    def fetch_environments(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM pva_environments ORDER BY display_name").fetchall()
        return [dict(r) for r in rows]

    def upsert_publishers(self, publishers: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('pva_publishers', publishers, snapshot=True)
            for p in publishers:
                cur = self._conn.execute(
                    "INSERT OR REPLACE INTO pva_publishers VALUES (?,?,?,?,?,?,?)",
                    (p.get("publisher_id", ""), p.get("display_name", ""), p.get("unique_name", ""),
                     p.get("email", ""), p.get("phone", ""), p.get("custom_prefix", ""),
                     p.get("solution_count")),
                )
                written += cur.rowcount
        return written

    def fetch_publishers(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM pva_publishers ORDER BY display_name").fetchall()
        return [dict(r) for r in rows]

    def upsert_dlp_policies(self, policies: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('pva_dlp_policies', policies, snapshot=True)
            for p in policies:
                cur = self._conn.execute(
                    "INSERT OR REPLACE INTO pva_dlp_policies VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (p.get("policy_id", ""), p.get("display_name", ""), p.get("environment_type", ""),
                     p.get("created_by", ""), p.get("created_at", ""), p.get("modified_at", ""),
                     p.get("enforcement_mode", ""), p.get("blocked_connectors", ""),
                     p.get("business_connectors", ""), p.get("non_business_connectors", "")),
                )
                written += cur.rowcount
        return written

    def fetch_dlp_policies(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM pva_dlp_policies ORDER BY display_name").fetchall()
        return [dict(r) for r in rows]

    def upsert_agent_solutions(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('pva_agent_solutions', rows, snapshot=True)
            for r in rows:
                cur = self._conn.execute(
                    "INSERT OR REPLACE INTO pva_agent_solutions VALUES (?,?,?,?,?,?)",
                    (r.get("agent_id", ""), r.get("solution_id", ""), r.get("solution_name", ""),
                     r.get("solution_unique", ""), r.get("version", ""),
                     1 if r.get("is_managed") else 0),
                )
                written += cur.rowcount
        return written

    def fetch_agent_solutions(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM pva_agent_solutions ORDER BY solution_name").fetchall()
        return [dict(r) for r in rows]

    def upsert_aad_users(self, users: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('aad_users', users, snapshot=False)
            for u in users:
                cur = self._conn.execute(
                    "INSERT OR REPLACE INTO aad_users VALUES (?,?,?,?,?,?)",
                    (u.get("user_id", ""), u.get("display_name", ""), u.get("upn", ""),
                     u.get("department", ""), u.get("job_title", ""),
                     1 if u.get("found", True) else 0),
                )
                written += cur.rowcount
        return written

    def fetch_aad_users(self) -> dict[str, dict]:
        """Returns {user_id: row_dict} for O(1) lookup in the sheet writers."""
        rows = self._conn.execute("SELECT * FROM aad_users").fetchall()
        return {row["user_id"]: dict(row) for row in rows}

    def fetch_known_user_ids(self) -> list[str]:
        """
        Return distinct Azure AD user object IDs from all available local sources:
          1. Non-design-mode conversation events (OTel)
          2. Already-resolved AAD user cache (agent owner lookups, etc.)
        """
        ids: set[str] = set()
        for sql in [
            "SELECT DISTINCT user_id FROM conversation_events "
            "WHERE user_id IS NOT NULL AND user_id != '' AND design_mode = 0",
            "SELECT DISTINCT user_id FROM aad_users "
            "WHERE user_id IS NOT NULL AND user_id != ''",
        ]:
            try:
                ids.update(row["user_id"] for row in self._conn.execute(sql).fetchall())
            except Exception:
                pass
        return list(ids)

    def upsert_dim_agent_journey_persona(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('dim_agent_journey_persona', rows, snapshot=True)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO dim_agent_journey_persona VALUES (?,?,?,?)""",
                    (
                        r.get('agent_id'), r.get('journey_name'),
                        r.get('persona_type'), r.get('agent_name'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_xla_by_persona_journey(self) -> list[dict]:
        """Aggregate session metrics grouped by persona + journey via the mapping dimension."""
        rows = self._conn.execute("""
            SELECT
                m.persona_type,
                m.journey_name,
                COUNT(DISTINCT s.agent_id)                                           AS agent_count,
                SUM(s.total_sessions)                                                AS total_sessions,
                SUM(s.resolved_sessions)                                             AS resolved_sessions,
                SUM(s.escalated_sessions)                                            AS escalated_sessions,
                SUM(s.abandoned_sessions)                                            AS abandoned_sessions,
                SUM(s.engaged_sessions)                                              AS engaged_sessions,
                ROUND(SUM(s.resolved_sessions)  * 100.0 / NULLIF(SUM(s.total_sessions), 0), 1) AS completion_rate_pct,
                ROUND(SUM(s.escalated_sessions) * 100.0 / NULLIF(SUM(s.total_sessions), 0), 1) AS escalation_rate_pct,
                ROUND(SUM(s.abandoned_sessions) * 100.0 / NULLIF(SUM(s.total_sessions), 0), 1) AS abandonment_rate_pct,
                ROUND(
                    (
                        COALESCE(SUM(s.resolved_sessions) * 100.0 / NULLIF(SUM(s.total_sessions), 0), 0) * 0.6 +
                        (100.0 - COALESCE(SUM(s.escalated_sessions) * 100.0 / NULLIF(SUM(s.total_sessions), 0), 0)) * 0.2 +
                        (100.0 - COALESCE(SUM(s.abandoned_sessions) * 100.0 / NULLIF(SUM(s.total_sessions), 0), 0)) * 0.2
                    ), 1
                )                                                                    AS xla_score
            FROM viva_reports_cs_session_metrics s
            JOIN dim_agent_journey_persona m ON m.agent_id = s.agent_id
            GROUP BY m.persona_type, m.journey_name
            ORDER BY m.persona_type, m.journey_name
        """).fetchall()
        return [dict(r) for r in rows]

    def fetch_agent_contribution_by_persona_journey(self) -> list[dict]:
        """Per-agent breakdown: which personas/journeys each agent serves and its session outcomes."""
        rows = self._conn.execute("""
            SELECT
                COALESCE(a.agent_name, m.agent_name, s.agent_id)  AS agent_name,
                m.persona_type,
                m.journey_name,
                SUM(s.total_sessions)                              AS total_sessions,
                ROUND(SUM(s.resolved_sessions)  * 100.0 / NULLIF(SUM(s.total_sessions), 0), 1) AS completion_rate_pct,
                ROUND(SUM(s.escalated_sessions) * 100.0 / NULLIF(SUM(s.total_sessions), 0), 1) AS escalation_rate_pct,
                ROUND(SUM(s.abandoned_sessions) * 100.0 / NULLIF(SUM(s.total_sessions), 0), 1) AS abandonment_rate_pct
            FROM viva_reports_cs_session_metrics s
            JOIN dim_agent_journey_persona m ON m.agent_id = s.agent_id
            LEFT JOIN viva_reports_cs_copilot_agents a ON a.agent_id = s.agent_id
            GROUP BY s.agent_id, m.persona_type, m.journey_name
            ORDER BY total_sessions DESC
        """).fetchall()
        return [dict(r) for r in rows]

