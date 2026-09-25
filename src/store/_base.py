"""Connection lifecycle, schema bootstrap/migrations and shared helpers."""
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.store._migrations import LEGACY_MIGRATIONS, MIGRATIONS
from src.store._schema import _DDL, _POST


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _upn(value):
    """Canonical user principal name: trimmed and lower-cased. Entra treats
    UPNs case-insensitively but SQLite text comparison doesn't, and the M365
    exports disagree on casing for the same user — so every UPN is
    normalised on write and cross-source joins line up."""
    if not value:
        return value
    return str(value).strip().lower()


class StoreBase:
    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._run_id: str | None = None
        is_new = self._conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0
        self._conn.executescript(_DDL)
        if is_new:
            for migration_id, _ in MIGRATIONS:
                self._mark_migration_applied(migration_id)
        else:
            self._migrate()
        # Indexes + compatibility views run after migrations so they see the
        # current column names.
        self._conn.executescript(_POST)
        self._conn.commit()

    def _migrate(self) -> None:
        pending = [(mid, fn) for mid, fn in MIGRATIONS if not self._migration_applied(mid)]
        if not pending:
            return
        if not self._migration_applied("schema_v2"):
            missing = [m for m in LEGACY_MIGRATIONS if not self._migration_applied(m)]
            if missing:
                raise RuntimeError(
                    f"Database predates the consolidated schema (missing migrations: {', '.join(missing)}). "
                    "Their upgrade code has been retired — rebuild the database with a fresh sync."
                )
        for _, migrate in pending:
            migrate(self)

    # ------------------------------------------------------------------
    # Migration sentinel helpers
    # ------------------------------------------------------------------

    def _migration_applied(self, migration_id: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM _schema_migrations WHERE id = ?", (migration_id,)
        ).fetchone() is not None

    def _mark_migration_applied(self, migration_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO _schema_migrations (id, applied_at) VALUES (?, ?)",
            (migration_id, _now()),
        )

    # ------------------------------------------------------------------
    # Sync runs + import bookkeeping
    # ------------------------------------------------------------------

    def begin_run(self) -> str:
        """Start a sync run. Every sync gets a sync_runs row (not only those
        with Log Analytics data), so `export` works on CSV-only databases."""
        self._run_id = str(uuid.uuid4())
        with self._conn:
            self._conn.execute(
                "INSERT INTO sync_runs (run_id, started_at, events_new, calls_new) VALUES (?,?,0,0)",
                (self._run_id, _now()),
            )
        return self._run_id

    def finish_run(self) -> None:
        """Post-import maintenance, run once after all sources have loaded:
        prune zero-activity Copilot person-weeks (after both Adoption and
        Impact are in, so neither report's flags are lost) and rebuild the
        agent ID crosswalk against the freshly loaded inventories."""
        with self._conn:
            self._prune_zero_copilot_actions()
            self.rebuild_agent_xref()
        # Pruning can free a large share of the file; reclaim it so the DB
        # uploaded to blob storage stays small. Skipped when there's little
        # to gain (VACUUM rewrites the whole file).
        free = self._conn.execute("PRAGMA freelist_count").fetchone()[0]
        total = self._conn.execute("PRAGMA page_count").fetchone()[0]
        if total and free / total > 0.25:
            self._conn.execute("VACUUM")

    def _begin_import(self, table: str, rows: list, snapshot: bool,
                      where: str = "", params: tuple = ()) -> None:
        """Call first inside an upsert's transaction.

        snapshot=True is for point-in-time datasets (e.g. 30-day usage
        exports, inventories): the table — or the `where` partition of it —
        is cleared so rows missing from the new load don't linger. An empty
        load is treated as "nothing fetched" and leaves the existing snapshot
        alone. snapshot=False is for date-keyed history, upserted by key.
        Either way the load is recorded in import_log.
        """
        if not rows:
            return
        if snapshot:
            self._conn.execute(f"DELETE FROM {table} {where}", params)
        label = f"{table} [{', '.join(str(p) for p in params)}]" if params else table
        self._conn.execute(
            "INSERT INTO import_log (run_id, table_name, mode, row_count, imported_at) VALUES (?,?,?,?,?)",
            (self._run_id, label, "snapshot" if snapshot else "merge", len(rows), _now()),
        )

    def fetch_import_log(self, limit: int = 200) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM import_log ORDER BY import_id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Shared dimensions
    # ------------------------------------------------------------------

    def _upsert_dim_user(self, upn: str, display_name: str | None) -> None:
        """COALESCE-upsert a user's display_name into dim_user. Called from
        every fetch source that observes a user, so whichever source runs
        first doesn't get overwritten with a blank name by one that doesn't
        carry it."""
        upn = _upn(upn)
        if not upn:
            return
        self._conn.execute(
            """
            INSERT INTO dim_user (user_principal_name, display_name)
            VALUES (?, ?)
            ON CONFLICT(user_principal_name) DO UPDATE SET
                display_name = COALESCE(excluded.display_name, dim_user.display_name)
            """,
            (upn, display_name or None),
        )

    def close(self) -> None:
        self._conn.close()
