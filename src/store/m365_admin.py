"""M365 Admin Center CSV exports: agent inventory, agent usage, Cowork, Copilot Chat and connectors."""
from src.store._base import _upn


class M365AdminMixin:
    def upsert_m365_admin_agent_inventory(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('m365_admin_agent_inventory', rows, snapshot=True)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_admin_agent_inventory VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        r.get('title_id'), r.get('name'), r.get('status'), r.get('channel'),
                        r.get('date_created'), r.get('last_modified'), r.get('publisher'),
                        r.get('publisher_type'), r.get('version'), r.get('owner'),
                        r.get('description'), r.get('platform'), r.get('creator_id'),
                        r.get('environment_id'), r.get('bot_id'), r.get('custom_actions'),
                        r.get('custom_action_list'), r.get('sensitivity'),
                        r.get('can_read_od_sp'), r.get('od_sp_items'),
                        r.get('can_read_od_files'), r.get('od_files'), r.get('od_sites'),
                        r.get('can_read_sp_sites'), r.get('sp_files'), r.get('sp_sites'),
                        r.get('can_extend_graph'), r.get('graph_connector_details'),
                        r.get('can_generate_images'), r.get('can_use_code_interpreter'),
                        r.get('contains_uploaded_files'), r.get('uploaded_files'),
                        r.get('instructions'), r.get('groups_shared'), r.get('users_shared'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_m365_admin_agent_inventory(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_admin_agent_inventory ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_usage_agent_id_overrides(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('usage_agent_id_overrides', rows, snapshot=True)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO usage_agent_id_overrides VALUES (?,?)""",
                    (r.get('agent_name'), r.get('bot_id')),
                )
                written += cur.rowcount
        return written

    def upsert_m365_usage_agents(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('m365_usage_agents', rows, snapshot=True)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_usage_agents
                    (agent_id, agent_name, creator_type, active_users_licensed,
                     active_users_unlicensed, responses_sent, last_activity_date)
                    VALUES (?,?,?,?,?,?,?)""",
                    (
                        r.get('agent_id'), r.get('agent_name'), r.get('creator_type'),
                        r.get('active_users_licensed'), r.get('active_users_unlicensed'),
                        r.get('responses_sent'), r.get('last_activity_date'),
                    ),
                )
                written += cur.rowcount
            self.rebuild_agent_xref()
        return written

    def rebuild_agent_xref(self) -> None:
        """Rebuild dim_agent_xref and m365_usage_agents.resolved_agent_id.

        M365 usage-report agents resolve, in order: manual override (by
        name) → exact inventory match on title_id → an inventory name that
        maps to exactly one bot_id. Viva Copilot Studio report agents resolve
        to their own GUID when dim_agent already has them from Power
        Platform/Dataverse, else an exact inventory bot_id, else a unique
        name. Ambiguous or unmatched agents stay 'unresolved' rather than
        guessed. Runs inside the caller's transaction."""
        self._conn.execute("DELETE FROM dim_agent_xref")
        inv_name_cte = """
            inv_name AS (
                SELECT lower(trim(name)) AS name_key, MAX(bot_id) AS bot_id, MAX(title_id) AS title_id
                FROM m365_admin_agent_inventory
                WHERE COALESCE(bot_id, '') != ''
                GROUP BY lower(trim(name))
                HAVING COUNT(DISTINCT bot_id) = 1
            )"""
        self._conn.execute(f"""
            WITH {inv_name_cte}
            INSERT INTO dim_agent_xref (source, source_agent_id, agent_name, title_id, bot_id, match_method)
            SELECT 'm365_usage', u.agent_id, u.agent_name,
                   COALESCE(i.title_id, n.title_id),
                   COALESCE(NULLIF(o.bot_id, ''), NULLIF(i.bot_id, ''), n.bot_id),
                   CASE WHEN COALESCE(o.bot_id, '') != '' THEN 'override'
                        WHEN COALESCE(i.bot_id, '') != '' THEN 'exact_id'
                        WHEN n.bot_id IS NOT NULL THEN 'name_unique'
                        ELSE 'unresolved' END
            FROM m365_usage_agents u
            LEFT JOIN usage_agent_id_overrides o ON o.agent_name = u.agent_name
            LEFT JOIN m365_admin_agent_inventory i ON i.title_id = u.agent_id
            LEFT JOIN inv_name n ON n.name_key = lower(trim(u.agent_name))
        """)
        self._conn.execute(f"""
            WITH {inv_name_cte},
            inv_bot AS (
                SELECT bot_id, MAX(title_id) AS title_id
                FROM m365_admin_agent_inventory
                WHERE COALESCE(bot_id, '') != ''
                GROUP BY bot_id
            )
            INSERT INTO dim_agent_xref (source, source_agent_id, agent_name, title_id, bot_id, match_method)
            SELECT 'viva_cs', d.agent_id, d.display_name,
                   COALESCE(b.title_id, n.title_id),
                   CASE WHEN d.environment_id IS NOT NULL OR b.bot_id IS NOT NULL THEN d.agent_id
                        ELSE n.bot_id END,
                   CASE WHEN d.environment_id IS NOT NULL OR b.bot_id IS NOT NULL THEN 'exact_id'
                        WHEN n.bot_id IS NOT NULL THEN 'name_unique'
                        ELSE 'unresolved' END
            FROM dim_agent d
            LEFT JOIN inv_bot b ON b.bot_id = d.agent_id
            LEFT JOIN inv_name n ON n.name_key = lower(trim(d.display_name))
            WHERE d.in_viva_report = 1
        """)
        self._conn.execute("""
            UPDATE m365_usage_agents
            SET resolved_agent_id = (
                SELECT x.bot_id FROM dim_agent_xref x
                WHERE x.source = 'm365_usage' AND x.source_agent_id = m365_usage_agents.agent_id
            )
        """)

    def fetch_agent_xref(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM dim_agent_xref ORDER BY source, match_method, agent_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def fetch_m365_usage_agents(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_usage_agents ORDER BY responses_sent DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def fetch_m365_usage_agents_unresolved(self) -> list[dict]:
        """Agent names with no resolved Copilot Studio GUID — either no inventory
        match or an ambiguous one (same name, multiple bot_ids). Use this list to
        populate imports/usage_agent_id_overrides.csv."""
        rows = self._conn.execute(
            """SELECT agent_id, agent_name, responses_sent, last_activity_date
               FROM m365_usage_agents
               WHERE resolved_agent_id IS NULL
               ORDER BY responses_sent DESC"""
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_usage_agent_users(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('m365_usage_agent_users', rows, snapshot=True)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_usage_agent_users VALUES (?,?,?,?,?,?)""",
                    (
                        r.get('agent_id'), _upn(r.get('user_principal_name')), r.get('agent_name'),
                        r.get('creator_type'), r.get('responses_sent'),
                        r.get('last_activity_date'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_m365_usage_agent_users(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_usage_agent_users ORDER BY agent_id, responses_sent DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_usage_users(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('m365_usage_users', rows, snapshot=True)
            for r in rows:
                self._upsert_dim_user(r.get('user_principal_name'), r.get('display_name'))
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_usage_users VALUES (?,?,?,?)""",
                    (
                        _upn(r.get('user_principal_name')), r.get('agents_used'),
                        r.get('agent_responses_received'), r.get('last_activity_date'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_m365_usage_users(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT m.*, u.display_name
            FROM m365_usage_users m
            LEFT JOIN dim_user u ON u.user_principal_name = m.user_principal_name
            ORDER BY m.agent_responses_received DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_cowork_usage(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('m365_cowork_usage', rows, snapshot=True)
            for r in rows:
                self._upsert_dim_user(r.get('user_principal_name'), r.get('display_name'))
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_cowork_usage VALUES (?,?,?,?,?,?)""",
                    (
                        _upn(r.get('user_principal_name')), r.get('total_tasks'),
                        r.get('scheduled_tasks'), r.get('user_initiated_tasks'),
                        r.get('active_days'), r.get('last_activity_date'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_m365_cowork_usage(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT m.*, u.display_name
            FROM m365_cowork_usage m
            LEFT JOIN dim_user u ON u.user_principal_name = m.user_principal_name
            ORDER BY m.total_tasks DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_copilot_chat_usage(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('m365_copilot_chat_usage', rows, snapshot=True)
            for r in rows:
                self._upsert_dim_user(r.get('user_principal_name'), r.get('display_name'))
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_copilot_chat_usage VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        _upn(r.get('user_principal_name')), r.get('user_guid'),
                        r.get('last_activity_date'), r.get('report_period'),
                        r.get('report_refresh_date'), r.get('prompts_submitted'),
                        r.get('active_usage_days'), r.get('last_activity_m365_copilot_app'),
                        r.get('last_activity_word'), r.get('last_activity_excel'),
                        r.get('last_activity_powerpoint'), r.get('last_activity_onenote'),
                        r.get('last_activity_edge'), r.get('last_activity_teams'),
                        r.get('last_activity_outlook'), r.get('last_activity_copilot_cloud'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_m365_copilot_chat_usage(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT m.*, u.display_name
            FROM m365_copilot_chat_usage m
            LEFT JOIN dim_user u ON u.user_principal_name = m.user_principal_name
            ORDER BY m.prompts_submitted DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_connectors_usage(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('m365_connectors_usage', rows, snapshot=True)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_connectors_usage VALUES (?,?,?,?)""",
                    (
                        r.get('connection_id'), r.get('active_users'),
                        r.get('responses_provided'), r.get('last_activity_date'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_m365_connectors_usage(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_connectors_usage ORDER BY responses_provided DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_connectors_users(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('m365_connectors_users', rows, snapshot=True)
            for r in rows:
                self._upsert_dim_user(r.get('user_principal_name'), r.get('display_name'))
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_connectors_users VALUES (?,?,?,?)""",
                    (
                        _upn(r.get('user_principal_name')), r.get('connections_used'),
                        r.get('responses_received'), r.get('last_activity_date'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_m365_connectors_users(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT m.*, u.display_name
            FROM m365_connectors_users m
            LEFT JOIN dim_user u ON u.user_principal_name = m.user_principal_name
            ORDER BY m.responses_received DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

