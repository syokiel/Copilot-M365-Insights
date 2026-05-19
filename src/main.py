import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow --env <file> as first two args to load a different .env before settings init
# e.g. python -m src.main --env .env.mwc sync
_args = sys.argv[1:]
if len(_args) >= 2 and _args[0] == "--env":
    from dotenv import load_dotenv
    load_dotenv(Path(_args[1]), override=True)
    sys.argv = [sys.argv[0]] + _args[2:]

from config.settings import settings
from src.auth import get_logs_client
from src.fetchers.otel_fetcher import OtelFetcher
from src.fetchers.powerplatform_fetcher import PowerPlatformFetcher
from src.store.sqlite_store import SqliteStore
from src.writers.workbook_writer import build_workbook


def cmd_sync() -> str:
    """Fetch from Log Analytics and upsert into SQLite. Returns the run_id."""
    settings.validate()

    fetcher = OtelFetcher(
        client=get_logs_client(),
        workspace_id=settings.log_analytics_workspace_id,
        lookback=settings.lookback,
    )

    print("Fetching conversation events...")
    events = fetcher.fetch_conversation_events()
    print(f"  {len(events)} events")

    print("Fetching connector calls...")
    connector_calls = fetcher.fetch_connector_calls()
    print(f"  {len(connector_calls)} connector calls")

    store = SqliteStore(settings.db_path)
    events_new, calls_new = store.upsert(events, connector_calls)
    run_id = store.get_last_run_id()
    store.close()

    print(f"Synced to {settings.db_path}")
    print(f"  New events: {events_new}  (skipped: {len(events) - events_new})")
    print(f"  New calls:  {calls_new}  (skipped: {len(connector_calls) - calls_new})")

    if settings.dataverse_url:
        print("Fetching Power Platform data...")
        pp_fetcher = PowerPlatformFetcher(
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
            dataverse_url=settings.dataverse_url,
            environment_id=settings.powerplatform_environment_id,
        )
        pp_store = SqliteStore(settings.db_path)
        for label, fetch_fn, upsert_fn in [
            ("bots",        pp_fetcher.fetch_bots,         pp_store.upsert_bots),
            ("environments",pp_fetcher.fetch_environments, pp_store.upsert_environments),
            ("publishers",  pp_fetcher.fetch_publishers,   pp_store.upsert_publishers),
            ("DLP policies",pp_fetcher.fetch_dlp_policies, pp_store.upsert_dlp_policies),
        ]:
            try:
                items = fetch_fn()
                written = upsert_fn(items)
                print(f"  {label}: {len(items)} fetched, {written} written")
            except Exception as e:
                print(f"  WARNING: {label} fetch failed: {e}")
        pp_store.close()

    if settings.azure_storage_account:
        from src.store.blob_store import upload_db
        upload_db(
            settings.db_path,
            settings.azure_storage_account,
            settings.azure_storage_container,
            settings.azure_storage_db_blob,
        )

    return run_id


def cmd_export(run_id: str) -> None:
    """Read data within the lookback window from SQLite and write Excel."""
    store = SqliteStore(settings.db_path)
    events = store.fetch_events_since(settings.lookback)
    connector_calls = store.fetch_calls_since(settings.lookback)
    bots = store.fetch_bots()
    environments = store.fetch_environments()
    publishers = store.fetch_publishers()
    dlp_policies = store.fetch_dlp_policies()
    store.close()

    print(f"Exporting run {run_id[:8]} (last {settings.lookback_days} days)...")
    print(f"  {len(events)} events, {len(connector_calls)} connector calls")
    print(f"  {len(bots)} agents, {len(environments)} environments, {len(publishers)} publishers, {len(dlp_policies)} DLP policies")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    p = Path(settings.output_path)
    output_path = str(p.parent / f"{p.stem}_{ts}{p.suffix}")
    build_workbook(events, connector_calls, output_path,
                   bots=bots, environments=environments,
                   publishers=publishers, dlp_policies=dlp_policies)


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "all"

    if command == "sync":
        cmd_sync()
    elif command == "export":
        store = SqliteStore(settings.db_path)
        run_id = store.get_last_run_id()
        store.close()
        if not run_id:
            print("No sync runs found. Run 'sync' first.")
            sys.exit(1)
        cmd_export(run_id)
    elif command == "all":
        run_id = cmd_sync()
        print()
        cmd_export(run_id)
    else:
        print(f"Unknown command: {command}")
        print("Usage: python -m src.main [sync|export|all]")
        sys.exit(1)


if __name__ == "__main__":
    main()
