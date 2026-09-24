"""One-time upgrade of existing databases to the current schema.

New databases are created directly in the current shape (see _schema.py) and
never run this. Existing databases run migrate_to_v2 once, in a single
transaction; if any step fails the whole upgrade rolls back and is retried
on the next start.
"""
from src.store._schema import (
    _COPILOT_USAGE_CSV_COLUMNS,
    _COPILOT_USAGE_GRAPH_COUNT_COLUMNS,
    _VIEW_NAMES,
)

# The five table-consolidation migrations that produced the dim_*/fact_*
# layout. Their code was retired in schema_v2; a database must already have
# applied all of them to be upgraded in place.
LEGACY_MIGRATIONS = (
    "dim_agent_v1", "copilot_actions_v1", "service_usage_v1", "dim_user_v1", "app_activity_v1",
)
SCHEMA_VERSION = "schema_v2"

# (table, UPN column) pairs lower-cased by the upgrade. dim_user and the
# m365_copilot_usage split are handled separately (they need merging).
_UPN_KEYED = (
    ("teams_usage", "user_principal_name"),
    ("m365_o365_active_users", "user_principal_name"),
    ("m365_app_users", "user_principal_name"),
    ("fact_user_app_activity", "user_principal_name"),
    ("m365_usage_users", "user_principal_name"),
    ("m365_usage_agent_users", "user_principal_name"),
    ("m365_cowork_usage", "user_principal_name"),
    ("m365_copilot_chat_usage", "user_principal_name"),
    ("m365_connectors_users", "user_principal_name"),
    ("m365_usage_activations_users", "user_principal_name"),
    ("m365_usage_active_users_detail", "user_principal_name"),
    ("m365_usage_proplus_detail", "user_principal_name"),
)

# Indexes whose column is already the leading column of the table's
# primary key, so SQLite already has an equivalent index.
_REDUNDANT_INDEXES = (
    "idx_copilot_actions_person", "idx_viva_reports_cs_sess_agent", "idx_viva_reports_cs_topic_agent",
    "idx_viva_reports_cs_wau_agent", "idx_viva_reports_cs_auto_agent", "idx_m365_activations_upn",
    "idx_pp_topic_bot",
)


def _columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def migrate_to_v2(store) -> None:
    conn = store._conn
    conn.commit()
    conn.execute("BEGIN")
    try:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        # Views are recreated from _POST after migrating; several of them
        # reference columns/tables changed below.
        views = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall()
        }
        for view in _VIEW_NAMES:
            if view in views:
                conn.execute(f"DROP VIEW {view}")

        # dim_agent.icon — base64 image (~35 KB/agent) nothing reads.
        if "icon" in _columns(conn, "dim_agent"):
            conn.execute("ALTER TABLE dim_agent DROP COLUMN icon")

        # m365_copilot_usage → m365_copilot_usage_graph + m365_copilot_usage_csv.
        # A row belongs to a source if it has any of that source's own columns.
        if "m365_copilot_usage" in tables:
            graph_cols = ("last_activity_date",) + _COPILOT_USAGE_GRAPH_COUNT_COLUMNS + (
                "report_refresh_date", "report_period")
            has_graph = " OR ".join(f"{c} IS NOT NULL" for c in _COPILOT_USAGE_GRAPH_COUNT_COLUMNS)
            conn.execute(f"""
                INSERT OR REPLACE INTO m365_copilot_usage_graph (user_principal_name, {", ".join(graph_cols)})
                SELECT lower(trim(user_principal_name)), {", ".join(graph_cols)}
                FROM m365_copilot_usage WHERE {has_graph}
            """)
            csv_cols = ("last_activity_date", "report_refresh_date", "report_period") + _COPILOT_USAGE_CSV_COLUMNS
            has_csv = " OR ".join(f"{c} IS NOT NULL" for c in _COPILOT_USAGE_CSV_COLUMNS)
            conn.execute(f"""
                INSERT OR REPLACE INTO m365_copilot_usage_csv (user_principal_name, {", ".join(csv_cols)})
                SELECT lower(trim(user_principal_name)), {", ".join(csv_cols)}
                FROM m365_copilot_usage WHERE {has_csv}
            """)
            conn.execute("DROP TABLE m365_copilot_usage")

        # username → user_principal_name (same value; consistent naming).
        for table in ("m365_usage_users", "m365_usage_agent_users"):
            if "username" in _columns(conn, table):
                conn.execute(f"ALTER TABLE {table} RENAME COLUMN username TO user_principal_name")

        # m365_usage_activations_users.display_name → dim_user.
        if "display_name" in _columns(conn, "m365_usage_activations_users"):
            conn.execute("""
                INSERT INTO dim_user (user_principal_name, display_name)
                SELECT lower(trim(user_principal_name)), MAX(NULLIF(display_name, ''))
                FROM m365_usage_activations_users
                WHERE user_principal_name IS NOT NULL AND user_principal_name != ''
                GROUP BY lower(trim(user_principal_name))
                ON CONFLICT(user_principal_name) DO UPDATE SET
                    display_name = COALESCE(dim_user.display_name, excluded.display_name)
            """)
            conn.execute("ALTER TABLE m365_usage_activations_users DROP COLUMN display_name")

        # Lower-case every UPN key. OR REPLACE resolves the rare case where
        # two casings of one user were stored as separate rows.
        for table, col in _UPN_KEYED:
            conn.execute(
                f"UPDATE OR REPLACE {table} SET {col} = lower(trim({col})) WHERE {col} != lower(trim({col}))"
            )
        conn.execute("""
            INSERT INTO dim_user (user_principal_name, display_name)
            SELECT lower(trim(user_principal_name)), MAX(display_name)
            FROM dim_user
            WHERE user_principal_name != lower(trim(user_principal_name))
            GROUP BY lower(trim(user_principal_name))
            ON CONFLICT(user_principal_name) DO UPDATE SET
                display_name = COALESCE(dim_user.display_name, excluded.display_name)
        """)
        conn.execute("DELETE FROM dim_user WHERE user_principal_name != lower(trim(user_principal_name))")

        for index in _REDUNDANT_INDEXES:
            conn.execute(f"DROP INDEX IF EXISTS {index}")

        store._prune_zero_copilot_actions()
        store.rebuild_agent_xref()

        store._mark_migration_applied(SCHEMA_VERSION)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    # Reclaim the space freed above (must run outside a transaction).
    conn.execute("VACUUM")
