"""M365 usage reporting: Copilot/Teams/O365/app usage (Graph + CSV) and Office 365 / Microsoft 365 Apps usage exports."""

from src.store._base import _upn
from src.store._schema import (
    _SERVICE_NAMES,
    _APP_USERS_COLUMNS,
    _PROPLUS_APP_COLUMNS,
)


class M365UsageMixin:
    def upsert_copilot_usage(self, rows: list[dict]) -> int:
        """Graph Copilot usage snapshot → m365_copilot_usage_graph (recombined
        with the CSV export by the m365_copilot_usage view)."""
        written = 0
        with self._conn:
            self._begin_import('m365_copilot_usage_graph', rows, snapshot=True)
            for r in rows:
                self._upsert_dim_user(r["user_principal_name"], r.get("display_name"))
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_copilot_usage_graph (
                        user_principal_name, last_activity_date, teams_chats, teams_meetings,
                        word, excel, powerpoint, outlook, onenote, loop, copilot_chat,
                        report_refresh_date, report_period
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (_upn(r["user_principal_name"]),
                     r.get("last_activity_date", ""), r.get("teams_chats"),
                     r.get("teams_meetings"), r.get("word"), r.get("excel"),
                     r.get("powerpoint"), r.get("outlook"), r.get("onenote"),
                     r.get("loop"), r.get("copilot_chat"),
                     r.get("report_refresh_date", ""), r.get("report_period", "")),
                )
                written += cur.rowcount
        return written

    def upsert_m365_usage_copilot_detail(self, rows: list[dict]) -> int:
        """FastCopilotActivityUserDetail CSV snapshot (M365ADMIN_USAGE_COPILOT)
        → m365_copilot_usage_csv (recombined with the Graph pull by the
        m365_copilot_usage view)."""
        written = 0
        with self._conn:
            self._begin_import('m365_copilot_usage_csv', rows, snapshot=True)
            for r in rows:
                self._upsert_dim_user(r["user_principal_name"], r.get("display_name"))
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_copilot_usage_csv (
                        user_principal_name, last_activity_date, report_refresh_date, report_period,
                        prompts_all_apps, prompts_copilot_chat_work, prompts_copilot_chat_web,
                        active_usage_days_all_apps, last_activity_copilot_chat_work,
                        last_activity_copilot_chat_web, last_activity_teams_copilot,
                        last_activity_word_copilot, last_activity_excel_copilot,
                        last_activity_powerpoint_copilot, last_activity_outlook_copilot,
                        last_activity_onenote_copilot, last_activity_loop_copilot,
                        last_activity_m365_copilot_app, last_activity_edge
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        _upn(r["user_principal_name"]), r.get("last_activity_date", ""),
                        r.get("report_refresh_date", ""), r.get("report_period", ""),
                        r.get("prompts_all_apps"), r.get("prompts_copilot_chat_work"),
                        r.get("prompts_copilot_chat_web"), r.get("active_usage_days_all_apps"),
                        r.get("last_activity_copilot_chat_work", ""), r.get("last_activity_copilot_chat_web", ""),
                        r.get("last_activity_teams_copilot", ""), r.get("last_activity_word_copilot", ""),
                        r.get("last_activity_excel_copilot", ""), r.get("last_activity_powerpoint_copilot", ""),
                        r.get("last_activity_outlook_copilot", ""), r.get("last_activity_onenote_copilot", ""),
                        r.get("last_activity_loop_copilot", ""), r.get("last_activity_m365_copilot_app", ""),
                        r.get("last_activity_edge", ""),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_copilot_usage(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT m.*, u.display_name
            FROM m365_copilot_usage m
            LEFT JOIN dim_user u ON u.user_principal_name = m.user_principal_name
            ORDER BY m.user_principal_name
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_teams_usage(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('teams_usage', rows, snapshot=True)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO teams_usage VALUES
                    (?,?,?,?,?,?,?,?,?,?)""",
                    (_upn(r["user_principal_name"]), r.get("last_activity_date", ""),
                     r.get("team_chat_messages"), r.get("private_chat_messages"),
                     r.get("calls"), r.get("meetings"),
                     r.get("meetings_organized"), r.get("meetings_attended"),
                     r.get("report_refresh_date", ""), r.get("report_period", "")),
                )
                written += cur.rowcount
        return written

    def fetch_teams_usage(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM teams_usage ORDER BY user_principal_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_copilot_count_summary(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('m365_copilot_count_summary', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_copilot_count_summary VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r.get("report_refresh_date"), r.get("report_period"),
                     r.get("enabled_users"), r.get("active_users"),
                     r.get("chat_active"), r.get("teams_active"), r.get("teams_meetings_active"),
                     r.get("word_active"), r.get("excel_active"), r.get("powerpoint_active"),
                     r.get("outlook_active"), r.get("onenote_active"), r.get("loop_active"),
                     r.get("windows_active"), r.get("web_active"), r.get("mobile_active")),
                )
                written += cur.rowcount
        return written

    def fetch_copilot_count_summary(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_copilot_count_summary ORDER BY report_refresh_date DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_copilot_count_trend(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('m365_copilot_count_trend', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_copilot_count_trend VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r.get("report_date"), r.get("report_refresh_date"), r.get("report_period"),
                     r.get("active_users"), r.get("chat_active"), r.get("teams_active"),
                     r.get("teams_meetings_active"), r.get("word_active"), r.get("excel_active"),
                     r.get("powerpoint_active"), r.get("outlook_active"),
                     r.get("onenote_active"), r.get("loop_active")),
                )
                written += cur.rowcount
        return written

    def fetch_copilot_count_trend(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_copilot_count_trend ORDER BY report_date"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_copilot_packages(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('m365_copilot_packages', rows, snapshot=True)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_copilot_packages VALUES
                    (?,?,?,?,?,?,?,?)""",
                    (r.get("package_id"), r.get("display_name"), r.get("description"),
                     r.get("type"), r.get("state"), r.get("publisher_name"),
                     r.get("app_id"), r.get("properties")),
                )
                written += cur.rowcount
        return written

    def fetch_copilot_packages(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_copilot_packages ORDER BY display_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_o365_active_users(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('m365_o365_active_users', rows, snapshot=True)
            for r in rows:
                self._upsert_dim_user(r.get("user_principal_name"), r.get("display_name"))
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_o365_active_users VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (_upn(r.get("user_principal_name")), r.get("is_deleted", 0),
                     r.get("exchange_last_activity"), r.get("onedrive_last_activity"),
                     r.get("sharepoint_last_activity"), r.get("teams_last_activity"),
                     r.get("yammer_last_activity"),
                     r.get("has_exchange_license", 0), r.get("has_onedrive_license", 0),
                     r.get("has_sharepoint_license", 0), r.get("has_teams_license", 0),
                     r.get("has_yammer_license", 0),
                     r.get("report_refresh_date"), r.get("report_period")),
                )
                written += cur.rowcount
        return written

    def fetch_o365_active_users(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT m.*, u.display_name
            FROM m365_o365_active_users m
            LEFT JOIN dim_user u ON u.user_principal_name = m.user_principal_name
            ORDER BY m.user_principal_name
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def _upsert_app_activity_row(self, upn, app_name, source, is_active, report_period, report_refresh_date) -> int:
        cur = self._conn.execute(
            """INSERT OR REPLACE INTO fact_user_app_activity
               (user_principal_name, app_name, source, is_active, report_period, report_refresh_date)
               VALUES (?,?,?,?,?,?)""",
            (upn, app_name, source, is_active, report_period, report_refresh_date),
        )
        return cur.rowcount

    def upsert_m365_app_users(self, rows: list[dict]) -> int:
        """outlook/word/excel/ppt/onenote/teams _active flags now live in
        fact_user_app_activity (overlap with m365_usage_proplus_detail);
        m365_app_users keeps only its own sharepoint/onedrive flags."""
        written = 0
        with self._conn:
            self._begin_import('m365_app_users', rows, snapshot=True)
            self._begin_import('fact_user_app_activity', rows, snapshot=True, where='WHERE source = ?', params=('m365_app_users',))
            for r in rows:
                upn = _upn(r.get("user_principal_name"))
                for app, col in _APP_USERS_COLUMNS.items():
                    written += self._upsert_app_activity_row(
                        upn, app, "m365_app_users", r.get(col),
                        r.get("report_period"), r.get("report_refresh_date"),
                    )
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_app_users VALUES
                    (?,?,?,?,?,?,?)""",
                    (upn, r.get("last_activation_date"),
                     r.get("last_activity_date"), r.get("report_refresh_date"), r.get("report_period"),
                     r.get("sharepoint_active"), r.get("onedrive_active")),
                )
                written += cur.rowcount
        return written

    def fetch_m365_app_users(self) -> list[dict]:
        app_cols = ", ".join(
            f"MAX(CASE WHEN f.app_name='{app}' THEN f.is_active END) AS {col}"
            for app, col in _APP_USERS_COLUMNS.items()
        )
        rows = self._conn.execute(
            f"""
            SELECT m.user_principal_name, m.last_activation_date, m.last_activity_date,
                   m.report_refresh_date, m.report_period, m.sharepoint_active, m.onedrive_active,
                   {app_cols}
            FROM m365_app_users m
            LEFT JOIN fact_user_app_activity f
                ON f.user_principal_name = m.user_principal_name AND f.source = 'm365_app_users'
            GROUP BY m.user_principal_name
            ORDER BY m.user_principal_name
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_usage_activations_users(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('m365_usage_activations_users', rows, snapshot=True)
            for r in rows:
                self._upsert_dim_user(r.get('user_principal_name'), r.get('display_name'))
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_usage_activations_users VALUES
                    (?,?,?,?,?,?,?,?,?,?)""",
                    (_upn(r.get('user_principal_name')), r.get('product_type'),
                     r.get('report_refresh_date'),
                     r.get('last_activated_date'), r.get('windows'), r.get('mac'),
                     r.get('windows_10_mobile'), r.get('ios'), r.get('android'),
                     r.get('shared_computer')),
                )
                written += cur.rowcount
        return written

    def fetch_m365_usage_activations_users(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT m.*, u.display_name
            FROM m365_usage_activations_users m
            LEFT JOIN dim_user u ON u.user_principal_name = m.user_principal_name
            ORDER BY m.user_principal_name, m.product_type
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def _upsert_service_usage_row(
        self, metric_date, report_period, service_name, metric_source,
        active_count, inactive_count, report_refresh_date,
    ) -> int:
        cur = self._conn.execute(
            """INSERT OR REPLACE INTO fact_service_usage
               (metric_date, report_period, service_name, metric_source,
                active_count, inactive_count, report_refresh_date)
               VALUES (?,?,?,?,?,?,?)""",
            (metric_date, report_period, service_name, metric_source,
             active_count, inactive_count, report_refresh_date),
        )
        return cur.rowcount

    def upsert_m365_usage_active_users_services(self, rows: list[dict]) -> int:
        """m365_usage_active_users_services is a compatibility view
        pivoting fact_service_usage back to its original wide shape."""
        written = 0
        with self._conn:
            self._begin_import('fact_service_usage', rows, snapshot=False, params=('services',))
            for r in rows:
                for svc in _SERVICE_NAMES + ("office365",):
                    written += self._upsert_service_usage_row(
                        r.get('report_refresh_date'), r.get('report_period'), svc, 'services',
                        r.get(f'{svc}_active'), r.get(f'{svc}_inactive'), r.get('report_refresh_date'),
                    )
        return written

    def fetch_m365_usage_active_users_services(self) -> list[dict]:
        case_cols = ", ".join(
            f"MAX(CASE WHEN service_name='{s}' THEN active_count END) AS {s}_active, "
            f"MAX(CASE WHEN service_name='{s}' THEN inactive_count END) AS {s}_inactive"
            for s in _SERVICE_NAMES + ("office365",)
        )
        rows = self._conn.execute(
            f"""
            SELECT metric_date AS report_refresh_date, report_period, {case_cols}
            FROM fact_service_usage
            WHERE metric_source = 'services'
            GROUP BY metric_date, report_period
            ORDER BY metric_date DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_usage_active_users_activity(self, rows: list[dict]) -> int:
        """m365_usage_active_users_activity is a compatibility view
        pivoting fact_service_usage back to its original wide shape."""
        written = 0
        with self._conn:
            self._begin_import('fact_service_usage', rows, snapshot=False, params=('activity',))
            for r in rows:
                for svc in _SERVICE_NAMES:
                    written += self._upsert_service_usage_row(
                        r.get('report_date'), r.get('report_period'), svc, 'activity',
                        r.get(svc), None, r.get('report_refresh_date'),
                    )
        return written

    def fetch_m365_usage_active_users_activity(self) -> list[dict]:
        case_cols = ", ".join(
            f"MAX(CASE WHEN service_name='{s}' THEN active_count END) AS {s}" for s in _SERVICE_NAMES
        )
        rows = self._conn.execute(
            f"""
            SELECT metric_date AS report_date, report_period,
                   MAX(report_refresh_date) AS report_refresh_date, {case_cols}
            FROM fact_service_usage
            WHERE metric_source = 'activity'
            GROUP BY metric_date, report_period
            ORDER BY metric_date DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_usage_active_user_counts(self, rows: list[dict]) -> int:
        """m365_usage_active_user_counts is a compatibility view
        pivoting fact_service_usage back to its original wide shape."""
        written = 0
        with self._conn:
            self._begin_import('fact_service_usage', rows, snapshot=False, params=('counts',))
            for r in rows:
                for svc in _SERVICE_NAMES + ("office365",):
                    written += self._upsert_service_usage_row(
                        r.get('report_date'), r.get('report_period'), svc, 'counts',
                        r.get(svc), None, r.get('report_refresh_date'),
                    )
        return written

    def fetch_m365_usage_active_user_counts(self) -> list[dict]:
        case_cols = ", ".join(
            f"MAX(CASE WHEN service_name='{s}' THEN active_count END) AS {s}"
            for s in _SERVICE_NAMES + ("office365",)
        )
        rows = self._conn.execute(
            f"""
            SELECT metric_date AS report_date, report_period,
                   MAX(report_refresh_date) AS report_refresh_date, {case_cols}
            FROM fact_service_usage
            WHERE metric_source = 'counts'
            GROUP BY metric_date, report_period
            ORDER BY metric_date DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_usage_active_users_detail(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('m365_usage_active_users_detail', rows, snapshot=True)
            for r in rows:
                self._upsert_dim_user(r.get('user_principal_name'), r.get('display_name'))
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_usage_active_users_detail VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (_upn(r.get('user_principal_name')), r.get('report_refresh_date'),
                     r.get('is_deleted'), r.get('deleted_date'),
                     r.get('has_exchange'), r.get('has_onedrive'), r.get('has_sharepoint'),
                     r.get('has_skype'), r.get('has_yammer'), r.get('has_teams'),
                     r.get('exchange_last_activity'), r.get('onedrive_last_activity'),
                     r.get('sharepoint_last_activity'), r.get('skype_last_activity'),
                     r.get('yammer_last_activity'), r.get('teams_last_activity'),
                     r.get('exchange_license_date'), r.get('onedrive_license_date'),
                     r.get('sharepoint_license_date'), r.get('skype_license_date'),
                     r.get('yammer_license_date'), r.get('teams_license_date'),
                     r.get('assigned_products')),
                )
                written += cur.rowcount
        return written

    def fetch_m365_usage_active_users_detail(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT m.*, u.display_name
            FROM m365_usage_active_users_detail m
            LEFT JOIN dim_user u ON u.user_principal_name = m.user_principal_name
            ORDER BY m.user_principal_name
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_usage_proplus_platforms(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('m365_usage_proplus_platforms', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_usage_proplus_platforms VALUES
                    (?,?,?,?,?,?,?)""",
                    (r.get('report_date'), r.get('report_period'),
                     r.get('report_refresh_date'), r.get('windows'),
                     r.get('mac'), r.get('mobile'), r.get('web')),
                )
                written += cur.rowcount
        return written

    def fetch_m365_usage_proplus_platforms(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_usage_proplus_platforms ORDER BY report_date DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_usage_proplus_counts(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('m365_usage_proplus_counts', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_usage_proplus_counts VALUES
                    (?,?,?,?,?,?,?,?,?)""",
                    (r.get('report_date'), r.get('report_period'),
                     r.get('report_refresh_date'), r.get('outlook'),
                     r.get('word'), r.get('excel'), r.get('powerpoint'),
                     r.get('onenote'), r.get('teams')),
                )
                written += cur.rowcount
        return written

    def fetch_m365_usage_proplus_counts(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM m365_usage_proplus_counts ORDER BY report_date DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_m365_usage_proplus_detail(self, rows: list[dict]) -> int:
        """outlook/word/excel/powerpoint/onenote/teams flags now live in
        fact_user_app_activity (overlap with m365_app_users);
        m365_usage_proplus_detail keeps only its own platform flags."""
        written = 0
        with self._conn:
            self._begin_import('m365_usage_proplus_detail', rows, snapshot=True)
            self._begin_import('fact_user_app_activity', rows, snapshot=True, where='WHERE source = ?', params=('m365_usage_proplus_detail',))
            for r in rows:
                upn = _upn(r.get('user_principal_name'))
                for app, col in _PROPLUS_APP_COLUMNS.items():
                    written += self._upsert_app_activity_row(
                        upn, app, "m365_usage_proplus_detail", r.get(col),
                        r.get('report_period'), r.get('report_refresh_date'),
                    )
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO m365_usage_proplus_detail VALUES
                    (?,?,?,?,?,?,?,?,?)""",
                    (upn, r.get('report_refresh_date'),
                     r.get('last_activation_date'), r.get('last_activity_date'),
                     r.get('report_period'), r.get('windows'), r.get('mac'),
                     r.get('mobile'), r.get('web')),
                )
                written += cur.rowcount
        return written

    def fetch_m365_usage_proplus_detail(self) -> list[dict]:
        app_cols = ", ".join(
            f"MAX(CASE WHEN f.app_name='{app}' THEN f.is_active END) AS {col}"
            for app, col in _PROPLUS_APP_COLUMNS.items()
        )
        rows = self._conn.execute(
            f"""
            SELECT m.user_principal_name, m.report_refresh_date, m.last_activation_date,
                   m.last_activity_date, m.report_period, m.windows, m.mac, m.mobile, m.web,
                   {app_cols}
            FROM m365_usage_proplus_detail m
            LEFT JOIN fact_user_app_activity f
                ON f.user_principal_name = m.user_principal_name AND f.source = 'm365_usage_proplus_detail'
            GROUP BY m.user_principal_name
            ORDER BY m.user_principal_name
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_billing_licences(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('billing_licences', rows, snapshot=True)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO billing_licences VALUES (?,?,?,?,?)""",
                    (r.get('product_title'), r.get('total_licenses'),
                     r.get('expired_licenses'), r.get('assigned_licenses'),
                     r.get('status_message')),
                )
                written += cur.rowcount
        return written

    def fetch_billing_licences(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM billing_licences ORDER BY product_title"
        ).fetchall()
        return [dict(r) for r in rows]

