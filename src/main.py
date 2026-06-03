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
from src.auth import get_credential, get_logs_client
from src.crossref import build_crossref
from src.fetchers.azure_monitor_fetcher import AzureMonitorFetcher
from src.fetchers.graph_fetcher import GraphFetcher
from src.fetchers.viva_fetcher import VivaFetcher
from src.fetchers.otel_fetcher import OtelFetcher
from src.fetchers.powerplatform_fetcher import PowerPlatformFetcher
from src.store.sqlite_store import SqliteStore
from src.writers.workbook_writer import build_workbook


def cmd_sync() -> str:
    """Fetch from all configured services and upsert into SQLite. Returns the run_id."""
    settings.validate()

    events: list[dict] = []
    connector_calls: list[dict] = []
    model_calls: list[dict] = []

    if settings.log_analytics_workspace_id:
        try:
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
            print("Fetching AI model calls...")
            model_calls = fetcher.fetch_model_calls()
            print(f"  {len(model_calls)} AI model calls")
        except Exception as e:
            print(f"  WARNING: Log Analytics fetch failed: {e}")
    else:
        print("Skipping Log Analytics sync (LOG_ANALYTICS_WORKSPACE_ID not set)")

    store = SqliteStore(settings.db_path)
    events_new, calls_new = store.upsert(events, connector_calls)
    if model_calls:
        mc_written = store.upsert_gen_ai_model_calls(model_calls)
        print(f"  AI model calls: {len(model_calls)} fetched, {mc_written} written")
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
            credential=get_credential(),
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

        # Agents + solutions — iterate environments with a Dataverse URL.
        # POWERPLATFORM_AGENT_ENV_IDS (comma-separated) limits which environments are
        # iterated; useful in large tenants where most environments are inaccessible.
        all_agents: list[dict] = []
        all_solutions: list[dict] = []
        envs = pp_store.fetch_environments()
        if settings.agent_env_ids:
            envs = [e for e in envs if e.get("environment_id") in settings.agent_env_ids]
        for env in envs:
            dv_url = env.get("dataverse_url", "")
            env_id = env.get("environment_id", "")
            env_name = env.get("display_name") or env_id
            if not dv_url:
                continue
            try:
                agents = pp_fetcher.fetch_agents_from(dv_url, env_id)
                all_agents.extend(agents)
                sols = pp_fetcher.fetch_agent_solutions_from(dv_url)
                all_solutions.extend(sols)
                print(f"  {env_name}: {len(agents)} agents, {len(sols)} solution links")
            except Exception as e:
                print(f"  {env_name}: WARNING — {e}")

        written = pp_store.upsert_agents(all_agents)
        print(f"  agents total: {len(all_agents)} fetched, {written} written")
        written = pp_store.upsert_agent_solutions(all_solutions)
        print(f"  agent solutions total: {len(all_solutions)} fetched, {written} written")

        # Inventory API — tenant-wide V2 agents with createdBy / ownerId / createdIn
        try:
            inventory_agents = pp_fetcher.fetch_inventory_agents()
            written = pp_store.upsert_agents(inventory_agents)
            print(f"  inventory agents: {len(inventory_agents)} fetched, {written} written")
        except Exception as e:
            print(f"  WARNING: inventory agents fetch failed: {e}")

        pp_store.close()

    print("Fetching Microsoft Graph data...")
    graph_fetcher = GraphFetcher(credential=get_credential())
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

    # Resolve agent owner IDs to AAD user profiles (skip IDs already cached)
    try:
        existing_ids = set(graph_store.fetch_aad_users().keys())
        owner_ids = [
            uid for uid in {
                a.get("owner_id", "") for a in graph_store.fetch_agents()
                if a.get("owner_id")
            }
            if uid not in existing_ids
        ]
        if owner_ids:
            resolved = graph_fetcher.resolve_users(owner_ids)
            written = graph_store.upsert_aad_users(resolved)
            found = sum(1 for u in resolved if u.get("found"))
            print(f"  user directory: {len(owner_ids)} looked up, {found} found, {written} written")
    except Exception as e:
        print(f"  WARNING: user directory lookup failed: {e}")

    graph_store.close()

    print("Fetching Viva Insights data...")
    viva_fetcher = VivaFetcher(credential=get_credential())
    viva_store = SqliteStore(settings.db_path)

    known_user_ids = viva_store.fetch_known_user_ids()

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
    agents = store.fetch_agents()
    environments = store.fetch_environments()
    publishers = store.fetch_publishers()
    dlp_policies = store.fetch_dlp_policies()
    agent_solutions = store.fetch_agent_solutions()
    aad_users = store.fetch_aad_users()
    model_calls = store.fetch_gen_ai_model_calls()
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
    print(f"  {len(agents)} agents, {len(environments)} environments, {len(publishers)} publishers, {len(dlp_policies)} DLP policies, {len(agent_solutions)} agent-solution links")
    print(f"  {len(model_calls)} AI model calls")
    print(f"  {len(health_detail)} health rows, {len(crossref_summary)} flagged conversations")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    p = Path(settings.output_path)
    output_path = str(p.parent / f"{p.stem}_{ts}{p.suffix}")
    build_workbook(events, connector_calls, output_path,
                   agents=agents, environments=environments,
                   publishers=publishers, dlp_policies=dlp_policies,
                   agent_solutions=agent_solutions, aad_users=aad_users,
                   model_calls=model_calls,
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
