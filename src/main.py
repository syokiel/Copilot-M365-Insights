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
from src.crossref import build_crossref
from src.fetchers.azure_monitor_fetcher import AzureMonitorFetcher
from src.fetchers.graph_fetcher import GraphFetcher
from src.fetchers.viva_fetcher import VivaFetcher
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

    if settings.azure_monitor_workspace_id:
        print("Fetching Azure Monitor data...")
        az_fetcher = AzureMonitorFetcher(
            client=get_logs_client(),
            workspace_id=settings.azure_monitor_workspace_id,
        )
        az_store = SqliteStore(settings.db_path)
        hours_back = settings.lookback_days * 24
        for label, fetch_fn, upsert_fn in [
            ("dependency failures", az_fetcher.fetch_dependency_failures, az_store.upsert_az_dependency_failures),
            ("exceptions",          az_fetcher.fetch_exceptions,          az_store.upsert_az_exceptions),
        ]:
            try:
                items = fetch_fn(hours_back)
                written = upsert_fn(items)
                print(f"  {label}: {len(items)} fetched, {written} written")
            except Exception as e:
                print(f"  WARNING: {label} fetch failed: {e}")
        try:
            alerts = az_fetcher.fetch_alerts(
                hours_back=hours_back,
                subscription_id=settings.azure_monitor_subscription_id,
            )
            written = az_store.upsert_az_alerts(alerts)
            print(f"  alerts: {len(alerts)} fetched, {written} written")
        except Exception as e:
            print(f"  WARNING: alerts fetch failed: {e}")
        az_store.close()
    else:
        print("Skipping Azure Monitor sync (AZURE_MONITOR_WORKSPACE_ID not set)")

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

        # Environments + DLP — tenant-wide, not per-env
        for label, fetch_fn, upsert_fn in [
            ("environments", pp_fetcher.fetch_environments,  pp_store.upsert_environments),
            ("publishers",   pp_fetcher.fetch_publishers,    pp_store.upsert_publishers),
            ("DLP policies", pp_fetcher.fetch_dlp_policies,  pp_store.upsert_dlp_policies),
        ]:
            try:
                items = fetch_fn()
                written = upsert_fn(items)
                print(f"  {label}: {len(items)} fetched, {written} written")
            except Exception as e:
                print(f"  WARNING: {label} fetch failed: {e}")

        # Bots + solutions — iterate over every environment with a Dataverse URL
        all_bots: list[dict] = []
        all_solutions: list[dict] = []
        envs = pp_store.fetch_environments()
        for env in envs:
            dv_url = env.get("dataverse_url", "")
            env_id = env.get("environment_id", "")
            env_name = env.get("display_name") or env_id
            if not dv_url:
                continue
            try:
                bots = pp_fetcher.fetch_bots_from(dv_url, env_id)
                all_bots.extend(bots)
                sols = pp_fetcher.fetch_bot_solutions_from(dv_url)
                all_solutions.extend(sols)
                print(f"  {env_name}: {len(bots)} bots, {len(sols)} solution links")
            except Exception as e:
                print(f"  {env_name}: WARNING — {e}")

        written = pp_store.upsert_bots(all_bots)
        print(f"  bots total: {len(all_bots)} fetched, {written} written")
        written = pp_store.upsert_bot_solutions(all_solutions)
        print(f"  bot solutions total: {len(all_solutions)} fetched, {written} written")

        pp_store.close()

    print("Fetching Microsoft Graph data...")
    graph_fetcher = GraphFetcher(
        tenant_id=settings.azure_tenant_id,
        client_id=settings.azure_client_id,
        client_secret=settings.azure_client_secret,
    )
    graph_store = SqliteStore(settings.db_path)
    for label, fetch_fn, upsert_fn in [
        ("M365 Copilot usage", lambda: graph_fetcher.fetch_copilot_usage(settings.lookback_days), graph_store.upsert_copilot_usage),
        ("Teams activity",     lambda: graph_fetcher.fetch_teams_activity(settings.lookback_days), graph_store.upsert_teams_usage),
    ]:
        try:
            items = fetch_fn()
            written = upsert_fn(items)
            print(f"  {label}: {len(items)} fetched, {written} written")
        except Exception as e:
            print(f"  WARNING: {label} fetch failed: {e}")
    graph_store.close()

    print("Fetching Viva Insights data...")
    viva_fetcher = VivaFetcher(
        tenant_id=settings.azure_tenant_id,
        client_id=settings.azure_client_id,
        client_secret=settings.azure_client_secret,
    )
    viva_store = SqliteStore(settings.db_path)

    # Collect user IDs from existing conversation data to scope the per-user fetch
    known_user_ids = [
        r["user_id"] for r in viva_store.fetch_viva_person_insights()
    ] if False else []  # bootstrap: pull from conversation_events on first run
    known_user_ids = list({
        row["user_id"]
        for row in viva_store._conn.execute(
            "SELECT DISTINCT user_id FROM conversation_events "
            "WHERE user_id IS NOT NULL AND user_id != '' AND design_mode = 0"
        ).fetchall()
    })

    for label, fetch_fn, upsert_fn in [
        ("person insights",
         lambda: viva_fetcher.fetch_person_insights(known_user_ids),
         viva_store.upsert_viva_person_insights),
        ("org insights",
         viva_fetcher.fetch_org_insights,
         viva_store.upsert_viva_org_insights),
    ]:
        try:
            items = fetch_fn()
            written = upsert_fn(items)
            print(f"  {label}: {len(items)} fetched, {written} written")
        except Exception as e:
            print(f"  WARNING: {label} fetch failed: {e}")
    viva_store.close()

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
    bot_solutions = store.fetch_bot_solutions()
    az_dep_failures = store.fetch_az_dependency_failures()
    az_exceptions = store.fetch_az_exceptions()
    az_alerts = store.fetch_az_alerts()
    copilot_usage = store.fetch_copilot_usage()
    teams_usage = store.fetch_teams_usage()
    store.close()

    health_detail, crossref_summary = build_crossref(
        otel_events=events,
        otel_connector_calls=connector_calls,
        az_dependency_failures=az_dep_failures,
        az_exceptions=az_exceptions,
        az_alerts=az_alerts,
    )

    print(f"Exporting run {run_id[:8]} (last {settings.lookback_days} days)...")
    print(f"  {len(events)} events, {len(connector_calls)} connector calls")
    print(f"  {len(bots)} agents, {len(environments)} environments, {len(publishers)} publishers, {len(dlp_policies)} DLP policies, {len(bot_solutions)} bot-solution links")
    print(f"  {len(health_detail)} health rows, {len(crossref_summary)} flagged conversations")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    p = Path(settings.output_path)
    output_path = str(p.parent / f"{p.stem}_{ts}{p.suffix}")
    build_workbook(events, connector_calls, output_path,
                   bots=bots, environments=environments,
                   publishers=publishers, dlp_policies=dlp_policies,
                   bot_solutions=bot_solutions,
                   health_detail=health_detail, crossref_summary=crossref_summary,
                   copilot_usage=copilot_usage, teams_usage=teams_usage)


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
