import sys
from datetime import datetime, timezone
from pathlib import Path

# --env <file> must be handled before any settings / datasource modules are imported
_args = sys.argv[1:]
if len(_args) >= 2 and _args[0] == "--env":
    from dotenv import load_dotenv
    load_dotenv(Path(_args[1]), override=True)
    sys.argv = [sys.argv[0]] + _args[2:]

from config.datasources import DataSourceConfig, get_datasource, load_datasource_configs
from config.settings import settings
from src.auth import AuthManager
from src.crossref import build_crossref
from src.store.sqlite_store import SqliteStore
from src.writers.workbook_writer import build_workbook


def cmd_import_viva(report_dir: str) -> None:
    """Import Copilot Studio analytics CSV reports into the local SQLite DB."""
    settings.validate()
    from src.fetchers.viva_report import VivaReportImporter
    importer = VivaReportImporter(report_dir)
    store    = SqliteStore(settings.db_path)

    print(f"Importing Viva reports from: {report_dir}")
    for label, fetch_fn, upsert_fn in [
        ("session metrics",          importer.fetch_session_metrics,           store.upsert_viva_reports_cs_session_metrics),
        ("topic metrics",            importer.fetch_topic_metrics,             store.upsert_viva_reports_cs_topic_metrics),
        ("knowledge source metrics", importer.fetch_knowledge_source_metrics,  store.upsert_viva_reports_cs_knowledge_source_metrics),
        ("autonomous metrics",       importer.fetch_autonomous_metrics,        store.upsert_viva_reports_cs_autonomous_metrics),
        ("autonomous trigger metrics", importer.fetch_autonomous_trigger_metrics, store.upsert_viva_reports_cs_autonomous_trigger_metrics),
        ("action metrics",           importer.fetch_action_metrics,            store.upsert_viva_reports_cs_action_metrics),
        ("copilot agents",           importer.fetch_copilot_agents,            store.upsert_viva_reports_cs_copilot_agents),
        ("weekly active users",      importer.fetch_weekly_active_users,       store.upsert_viva_reports_cs_weekly_active_users),
        ("extended metadata",        importer.fetch_extended_metadata,         store.upsert_viva_reports_cs_extended_metadata),
        ("copilot adoption",         lambda: importer.fetch_copilot_adoption(settings.viva_report_adoption),  store.upsert_viva_reports_copilot_adoption),
        ("copilot impact",           lambda: importer.fetch_copilot_impact(settings.viva_report_impact),       store.upsert_viva_reports_copilot_impact),
    ]:
        try:
            items = fetch_fn()
            if items:
                written = upsert_fn(items)
                print(f"  {label}: {len(items)} rows, {written} written")
            else:
                print(f"  {label}: file not found, skipped")
        except Exception as e:
            print(f"  WARNING: {label} failed: {e}")

    store.close()
    print(f"Done. DB: {settings.db_path}")


def cmd_sync() -> str:
    """Fetch from all configured datasources and upsert into SQLite. Returns run_id."""
    settings.validate()

    ds_configs = load_datasource_configs()
    auth       = AuthManager()
    ordered    = AuthManager.fetch_order(ds_configs)

    store = SqliteStore(settings.db_path)

    # Tracks whether environments were already fetched (PP Admin → Global Discovery fallback)
    envs_fetched = False

    for ds in ordered:
        if not ds.enabled:
            print(f"\n[{ds.label}] SKIPPED ({ds.key}_ENABLED=false)")
            continue
        print(f"\n[{ds.label}] auth={ds.auth_method.value}")
        credential = auth.get_credential(ds)

        # ── Log Analytics ────────────────────────────────────────────────────
        if ds.key == "LOG_ANALYTICS":
            workspace_id = ds.extras.get("workspace_id", "")
            if not workspace_id:
                print("  Skipping (LOG_ANALYTICS_WORKSPACE_ID not set)")
                continue
            from src.fetchers.log_analytics import LogAnalyticsFetcher
            fetcher = LogAnalyticsFetcher(
                client=auth.logs_client(ds),
                workspace_id=workspace_id,
                lookback=settings.lookback,
            )
            events, connector_calls, model_calls = [], [], []
            for label, method, target in [
                ("conversation events", fetcher.fetch_conversation_events, "events"),
                ("connector calls",     fetcher.fetch_connector_calls,     "connector_calls"),
                ("AI model calls",      fetcher.fetch_model_calls,         "model_calls"),
            ]:
                try:
                    result = method()
                    print(f"  {label}: {len(result)}")
                    if target == "events":           events = result
                    elif target == "connector_calls": connector_calls = result
                    elif target == "model_calls":     model_calls = result
                except Exception as e:
                    print(f"  WARNING: {label} failed: {e}")
            events_new, calls_new = store.upsert(events, connector_calls)
            print(f"  Upserted: {events_new} new events, {calls_new} new connector calls")
            if model_calls:
                written = store.upsert_gen_ai_model_calls(model_calls)
                print(f"  AI model calls: {len(model_calls)} fetched, {written} written")

        # ── Azure Monitor ────────────────────────────────────────────────────
        elif ds.key == "AZURE_MONITOR":
            workspace_id = ds.extras.get("workspace_id", "")
            if not workspace_id:
                print("  Skipping (AZURE_MONITOR_WORKSPACE_ID not set)")
                continue
            from src.fetchers.azure_monitor import AzureMonitorFetcher
            fetcher = AzureMonitorFetcher(
                client=auth.logs_client(ds),
                workspace_id=workspace_id,
                credential=credential,
            )
            hours_back = settings.lookback_days * 24
            for label, fetch_fn, upsert_fn in [
                ("dependency failures",
                 lambda hb=hours_back: fetcher.fetch_dependency_failures(hb),
                 store.upsert_az_dependency_failures),
                ("exceptions",
                 lambda hb=hours_back: fetcher.fetch_exceptions(hb),
                 store.upsert_az_exceptions),
            ]:
                try:
                    items   = fetch_fn()
                    written = upsert_fn(items)
                    print(f"  {label}: {len(items)} fetched, {written} written")
                except Exception as e:
                    print(f"  WARNING: {label} failed: {e}")
            try:
                alerts  = fetcher.fetch_alerts(
                    hours_back=hours_back,
                    subscription_id=ds.extras.get("subscription_id", ""),
                )
                written = store.upsert_az_alerts(alerts)
                print(f"  alerts: {len(alerts)} fetched, {written} written")
            except Exception as e:
                print(f"  WARNING: alerts failed: {e}")

        # ── Power Platform Admin API ─────────────────────────────────────────
        elif ds.key == "POWERPLATFORM_ADMIN":
            from src.fetchers.powerplatform_admin import PowerPlatformAdminFetcher
            fetcher = PowerPlatformAdminFetcher(credential=credential)
            try:
                envs    = fetcher.fetch_environments()
                written = store.upsert_environments(envs)
                print(f"  environments: {len(envs)} fetched, {written} written")
                envs_fetched = bool(envs)
            except Exception as e:
                print(f"  WARNING: environments failed: {e}")
            for label, fetch_fn, upsert_fn in [
                ("DLP policies",    fetcher.fetch_dlp_policies,    store.upsert_dlp_policies),
                ("inventory agents", fetcher.fetch_inventory_agents, store.upsert_agents),
            ]:
                try:
                    items   = fetch_fn()
                    written = upsert_fn(items)
                    print(f"  {label}: {len(items)} fetched, {written} written")
                except Exception as e:
                    print(f"  WARNING: {label} failed: {e}")

            # ── PP Analytics (bot sessions + topic analytics) ────────────────
            from src.fetchers.pp_analytics import PPAnalyticsFetcher
            pp_analytics = PPAnalyticsFetcher(credential=credential)
            known_agents = store.fetch_agents()
            if settings.agent_env_ids:
                known_agents = [
                    a for a in known_agents
                    if a.get("environment_id") in settings.agent_env_ids
                ]
            for label, fetch_fn, upsert_fn in [
                ("bot sessions",
                 lambda: pp_analytics.fetch_all_sessions(known_agents, settings.lookback_days),
                 store.upsert_pp_bot_sessions),
                ("bot topic analytics",
                 lambda: pp_analytics.fetch_all_topic_analytics(known_agents, settings.lookback_days),
                 store.upsert_pp_bot_topic_analytics),
            ]:
                try:
                    items   = fetch_fn()
                    written = upsert_fn(items)
                    print(f"  {label}: {len(items)} fetched, {written} written")
                except Exception as e:
                    print(f"  WARNING: {label} failed: {e}")

        # ── Global Discovery (fallback if PP Admin failed / unavailable) ─────
        elif ds.key == "GLOBAL_DISCOVERY":
            if envs_fetched:
                print("  Skipping (environments already fetched from Power Platform Admin)")
                continue
            from src.fetchers.global_discovery import GlobalDiscoveryFetcher
            fetcher = GlobalDiscoveryFetcher(credential=credential)
            try:
                envs    = fetcher.fetch_instances()
                written = store.upsert_environments(envs)
                print(f"  instances: {len(envs)} fetched, {written} written")
                envs_fetched = bool(envs)
            except Exception as e:
                print(f"  WARNING: Global Discovery failed: {e}")

        # ── Dataverse Web API ────────────────────────────────────────────────
        elif ds.key == "DATAVERSE":
            url = ds.extras.get("url", "")
            if not url:
                print("  Skipping (DATAVERSE_URL not set)")
                continue
            if not url.startswith("http"):
                url = f"https://{url}"
            from src.fetchers.dataverse import DataverseFetcher
            fetcher = DataverseFetcher(credential=credential, dataverse_url=url)

            try:
                pubs    = fetcher.fetch_publishers()
                written = store.upsert_publishers(pubs)
                print(f"  publishers: {len(pubs)} fetched, {written} written")
            except Exception as e:
                print(f"  WARNING: publishers failed: {e}")

            # Agents + solutions — iterate all known environments
            all_agents, all_solutions = [], []
            envs = store.fetch_environments()
            if settings.agent_env_ids:
                envs = [e for e in envs if e.get("environment_id") in settings.agent_env_ids]
            if not envs:
                # Config fallback: single env from DATAVERSE_URL + POWERPLATFORM_ENVIRONMENT_ID
                env_id = settings.powerplatform_environment_id
                envs = [{"environment_id": env_id, "dataverse_url": url, "display_name": ""}]

            for env in envs:
                dv_url   = env.get("dataverse_url", "")
                env_id   = env.get("environment_id", "")
                env_name = env.get("display_name") or env_id
                if not dv_url:
                    continue
                try:
                    agents = fetcher.fetch_agents(dv_url, env_id)
                    all_agents.extend(agents)
                    sols   = fetcher.fetch_agent_solutions(dv_url)
                    all_solutions.extend(sols)
                    print(f"  {env_name}: {len(agents)} agents, {len(sols)} solution links")
                except Exception as e:
                    print(f"  {env_name}: WARNING — {e}")

            written = store.upsert_agents(all_agents)
            print(f"  agents total: {len(all_agents)} fetched, {written} written")
            written = store.upsert_agent_solutions(all_solutions)
            print(f"  solutions total: {len(all_solutions)} fetched, {written} written")

        # ── Microsoft Graph Reports API ──────────────────────────────────────
        elif ds.key == "GRAPH":
            from src.fetchers.graph import GraphFetcher
            fetcher = GraphFetcher(credential=credential)
            for label, fetch_fn, upsert_fn in [
                ("M365 Copilot usage",
                 lambda: fetcher.fetch_copilot_usage(settings.lookback_days),
                 store.upsert_copilot_usage),
                ("Teams activity",
                 lambda: fetcher.fetch_teams_activity(settings.lookback_days),
                 store.upsert_teams_usage),
                ("Copilot user count summary",
                 lambda: fetcher.fetch_copilot_user_count_summary(settings.lookback_days),
                 store.upsert_copilot_count_summary),
                ("Copilot user count trend",
                 lambda: fetcher.fetch_copilot_user_count_trend(settings.lookback_days),
                 store.upsert_copilot_count_trend),
                ("Copilot packages",
                 fetcher.fetch_copilot_packages,
                 store.upsert_copilot_packages),
                ("O365 active user detail",
                 lambda: fetcher.fetch_o365_active_user_detail(settings.lookback_days),
                 store.upsert_o365_active_users),
                ("M365 app user detail",
                 lambda: fetcher.fetch_m365_app_user_detail(settings.lookback_days),
                 store.upsert_m365_app_users),
                ("Graph request usage",
                 lambda: fetcher.fetch_graph_request_usage(settings.lookback_days),
                 store.upsert_graph_request_usage),
            ]:
                try:
                    items   = fetch_fn()
                    written = upsert_fn(items)
                    print(f"  {label}: {len(items)} fetched, {written} written")
                except Exception as e:
                    print(f"  WARNING: {label} failed: {e}")
            try:
                existing_ids = set(store.fetch_aad_users().keys())
                owner_ids = [
                    uid for uid in {
                        a.get("owner_id", "") for a in store.fetch_agents()
                        if a.get("owner_id")
                    }
                    if uid not in existing_ids
                ]
                if owner_ids:
                    resolved = fetcher.resolve_users(owner_ids)
                    written  = store.upsert_aad_users(resolved)
                    found    = sum(1 for u in resolved if u.get("found"))
                    print(f"  user directory: {len(owner_ids)} looked up, {found} found, {written} written")
            except Exception as e:
                print(f"  WARNING: user directory failed: {e}")

        # ── Microsoft Viva ───────────────────────────────────────────────────
        elif ds.key == "VIVA":
            from src.fetchers.viva import VivaFetcher
            fetcher        = VivaFetcher(credential=credential)
            known_user_ids = store.fetch_known_user_ids()
            if not known_user_ids:
                # No user IDs from conversation events or AAD cache — fall back
                # to a full tenant user listing from Graph.
                graph_ds = get_datasource(ds_configs, "GRAPH")
                if graph_ds:
                    from src.fetchers.graph import GraphFetcher
                    try:
                        known_user_ids = GraphFetcher(
                            credential=auth.get_credential(graph_ds)
                        ).fetch_all_user_ids()
                        print(f"  resolved {len(known_user_ids)} user IDs from Graph directory")
                    except Exception as e:
                        print(f"  WARNING: Graph user listing failed: {e}")
            for label, fetch_fn, upsert_fn in [
                ("person insights",
                 lambda: fetcher.fetch_person_insights(known_user_ids),
                 store.upsert_viva_person_insights),
                ("org insights",
                 fetcher.fetch_org_insights,
                 store.upsert_viva_org_insights),
            ]:
                try:
                    items   = fetch_fn()
                    written = upsert_fn(items)
                    print(f"  {label}: {len(items)} fetched, {written} written")
                except Exception as e:
                    print(f"  WARNING: {label} failed: {e}")

        # ── Purview ──────────────────────────────────────────────────────────
        elif ds.key == "PURVIEW":
            account_name = ds.extras.get("account_name", "")
            if not account_name and not ds.extras.get("endpoint", ""):
                print("  Skipping (PURVIEW_ACCOUNT_NAME not set)")
                continue
            from src.fetchers.purview import PurviewFetcher
            fetcher = PurviewFetcher(
                credential=credential,
                account_name=account_name,
                endpoint=ds.extras.get("endpoint", ""),
            )
            try:
                assets = fetcher.fetch_assets()
                print(f"  catalog assets: {len(assets)} fetched")
                # TODO: wire store.upsert_purview_assets() once schema is defined
            except Exception as e:
                print(f"  WARNING: catalog search failed: {e}")

        # ── Microsoft Defender ───────────────────────────────────────────────
        elif ds.key == "DEFENDER":
            subscription_id = ds.extras.get("subscription_id", "")
            if not subscription_id:
                print("  Skipping (DEFENDER_SUBSCRIPTION_ID not set)")
                continue
            from src.fetchers.defender import DefenderFetcher
            fetcher = DefenderFetcher(credential=credential, subscription_id=subscription_id)
            try:
                alerts  = fetcher.fetch_alerts()
                print(f"  security alerts: {len(alerts)} fetched")
                # TODO: wire store.upsert_defender_alerts() once schema is defined
            except Exception as e:
                print(f"  WARNING: security alerts failed: {e}")
            try:
                scores = fetcher.fetch_secure_score()
                print(f"  secure score entries: {len(scores)} fetched")
            except Exception as e:
                print(f"  WARNING: secure score failed: {e}")

    # ── Viva CS auto-import ───────────────────────────────────────────────────
    if settings.viva_reports_cs_report_dir:
        print(f"\n[Viva CS] importing from {settings.viva_reports_cs_report_dir}")
        from src.fetchers.viva_report import VivaReportImporter
        importer = VivaReportImporter(settings.viva_reports_cs_report_dir)
        for label, fetch_fn, upsert_fn in [
            ("session metrics",            importer.fetch_session_metrics,             store.upsert_viva_reports_cs_session_metrics),
            ("topic metrics",              importer.fetch_topic_metrics,               store.upsert_viva_reports_cs_topic_metrics),
            ("knowledge source metrics",   importer.fetch_knowledge_source_metrics,    store.upsert_viva_reports_cs_knowledge_source_metrics),
            ("autonomous metrics",         importer.fetch_autonomous_metrics,          store.upsert_viva_reports_cs_autonomous_metrics),
            ("autonomous trigger metrics", importer.fetch_autonomous_trigger_metrics,  store.upsert_viva_reports_cs_autonomous_trigger_metrics),
            ("action metrics",             importer.fetch_action_metrics,              store.upsert_viva_reports_cs_action_metrics),
            ("copilot agents",             importer.fetch_copilot_agents,              store.upsert_viva_reports_cs_copilot_agents),
            ("weekly active users",        importer.fetch_weekly_active_users,         store.upsert_viva_reports_cs_weekly_active_users),
            ("extended metadata",          importer.fetch_extended_metadata,           store.upsert_viva_reports_cs_extended_metadata),
            ("copilot adoption",           lambda: importer.fetch_copilot_adoption(settings.viva_report_adoption),  store.upsert_viva_reports_copilot_adoption),
            ("copilot impact",             lambda: importer.fetch_copilot_impact(settings.viva_report_impact),       store.upsert_viva_reports_copilot_impact),
        ]:
            try:
                items = fetch_fn()
                if items:
                    written = upsert_fn(items)
                    print(f"  {label}: {len(items)} rows, {written} written")
                else:
                    print(f"  {label}: file not found, skipped")
            except Exception as e:
                print(f"  WARNING: {label} failed: {e}")

    # ── M365 Admin / Usage auto-import ───────────────────────────────────────
    if any([
        settings.m365_admin_agent_inventory,
        settings.m365_usage_report_agents,
        settings.m365_usage_report_agent_users,
        settings.m365_usage_report_users,
    ]):
        print("\n[M365 Admin/Usage] importing CSV reports")
        from src.fetchers.m365_admin_report import M365AdminReportImporter
        m365 = M365AdminReportImporter(
            inventory_path=settings.m365_admin_agent_inventory,
            agents_path=settings.m365_usage_report_agents,
            agent_users_path=settings.m365_usage_report_agent_users,
            users_path=settings.m365_usage_report_users,
        )
        for label, fetch_fn, upsert_fn in [
            ("agent inventory",   m365.fetch_agent_inventory,   store.upsert_m365_admin_agent_inventory),
            ("usage agents",      m365.fetch_usage_agents,       store.upsert_m365_usage_agents),
            ("usage agent users", m365.fetch_usage_agent_users,  store.upsert_m365_usage_agent_users),
            ("usage users",       m365.fetch_usage_users,        store.upsert_m365_usage_users),
        ]:
            try:
                items = fetch_fn()
                if items:
                    written = upsert_fn(items)
                    print(f"  {label}: {len(items)} rows, {written} written")
                else:
                    print(f"  {label}: file not found or not configured, skipped")
            except Exception as e:
                print(f"  WARNING: {label} failed: {e}")

    # ── Tokenomics (PP Admin capacity/entitlement consumption) auto-import ──
    if any([
        settings.ppadmin_licenses_cs_consumption_manageagents,
        settings.ppadmin_licenses_cs_consumption_env,
        settings.ppadmin_licenses_cs_consumption_agent,
        settings.ppadmin_licenses_cs_consumption_user,
    ]):
        print("\n[Tokenomics] importing PP Admin consumption CSV reports")
        from src.fetchers.ppadmin_consumption import PPAdminConsumptionImporter
        ppadmin = PPAdminConsumptionImporter(
            capacity_path=settings.ppadmin_licenses_cs_consumption_manageagents,
            entitlement_path=settings.ppadmin_licenses_cs_consumption_env,
            entitlement_per_agent_path=settings.ppadmin_licenses_cs_consumption_agent,
            entitlement_per_user_path=settings.ppadmin_licenses_cs_consumption_user,
        )
        for label, fetch_fn, upsert_fn in [
            ("capacity consumption",        ppadmin.fetch_capacity_consumption,    store.upsert_tokenomics_capacity_consumption),
            ("entitlement consumption",     ppadmin.fetch_entitlement_consumption, store.upsert_tokenomics_entitlement_consumption),
            ("entitlement per-agent",       ppadmin.fetch_entitlement_per_agent,   store.upsert_tokenomics_entitlement_per_agent),
            ("entitlement per-user",        ppadmin.fetch_entitlement_per_user,    store.upsert_tokenomics_entitlement_per_user),
        ]:
            try:
                items = fetch_fn()
                if items:
                    written = upsert_fn(items)
                    print(f"  {label}: {len(items)} rows, {written} written")
                else:
                    print(f"  {label}: file not found or not configured, skipped")
            except Exception as e:
                print(f"  WARNING: {label} failed: {e}")

    # ── KPI snapshot ─────────────────────────────────────────────────────────
    print("\n[KPI Snapshot]")
    try:
        snap    = store.compute_kpi_snapshot(settings.lookback_days, settings.total_licenses)
        store.upsert_kpi_snapshot(snap)
        print(f"  saved ({snap['snapshot_date'][:10]})")
    except Exception as e:
        print(f"  WARNING: KPI snapshot failed: {e}")

    run_id = store.get_last_run_id() or ""
    store.close()

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
    """Read data within the lookback window from SQLite and write an Excel workbook."""
    store              = SqliteStore(settings.db_path)
    events             = store.fetch_events_since(settings.lookback)
    connector_calls    = store.fetch_calls_since(settings.lookback)
    agents             = store.fetch_agents()
    environments       = store.fetch_environments()
    publishers         = store.fetch_publishers()
    dlp_policies       = store.fetch_dlp_policies()
    agent_solutions    = store.fetch_agent_solutions()
    aad_users          = store.fetch_aad_users()
    model_calls        = store.fetch_gen_ai_model_calls()
    kpi_snapshots      = store.fetch_kpi_snapshots()
    az_dep_failures    = store.fetch_az_dependency_failures()
    az_exceptions      = store.fetch_az_exceptions()
    az_alerts          = store.fetch_az_alerts()
    copilot_usage           = store.fetch_copilot_usage()
    teams_usage             = store.fetch_teams_usage()
    viva_person_insights       = store.fetch_viva_person_insights()
    viva_reports_cs_session_metrics       = store.fetch_viva_reports_cs_session_metrics()
    viva_reports_cs_topic_metrics         = store.fetch_viva_reports_cs_topic_metrics()
    viva_reports_cs_weekly_active_users   = store.fetch_viva_reports_cs_weekly_active_users()
    viva_reports_cs_autonomous_metrics    = store.fetch_viva_reports_cs_autonomous_metrics()
    viva_reports_cs_copilot_agents        = store.fetch_viva_reports_cs_copilot_agents()
    copilot_count_summary         = store.fetch_copilot_count_summary()
    copilot_count_trend           = store.fetch_copilot_count_trend()
    copilot_packages              = store.fetch_copilot_packages()
    o365_active_users             = store.fetch_o365_active_users()
    m365_app_users                = store.fetch_m365_app_users()
    viva_reports_copilot_adoption = store.fetch_viva_reports_copilot_adoption()
    viva_reports_copilot_impact   = store.fetch_viva_reports_copilot_impact()
    m365_admin_agent_inventory          = store.fetch_m365_admin_agent_inventory()
    m365_usage_agents                   = store.fetch_m365_usage_agents()
    m365_usage_agent_users              = store.fetch_m365_usage_agent_users()
    m365_usage_users                    = store.fetch_m365_usage_users()
    viva_reports_cs_action_metrics      = store.fetch_viva_reports_cs_action_metrics()
    tokenomics_capacity_consumption     = store.fetch_tokenomics_capacity_consumption()
    tokenomics_entitlement_consumption  = store.fetch_tokenomics_entitlement_consumption()
    tokenomics_entitlement_per_agent    = store.fetch_tokenomics_entitlement_per_agent()
    tokenomics_entitlement_per_user     = store.fetch_tokenomics_entitlement_per_user()
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
    print(f"  {len(agents)} agents, {len(environments)} environments, "
          f"{len(publishers)} publishers, {len(dlp_policies)} DLP policies, "
          f"{len(agent_solutions)} agent-solution links")
    print(f"  {len(model_calls)} AI model calls")
    print(f"  {len(viva_person_insights)} Viva person insight rows")
    print(f"  {len(viva_reports_cs_session_metrics)} Viva session metric rows, "
          f"{len(viva_reports_cs_topic_metrics)} topic rows, "
          f"{len(viva_reports_cs_weekly_active_users)} WAU rows, "
          f"{len(viva_reports_cs_autonomous_metrics)} autonomous rows")
    print(f"  {len(health_detail)} health rows, {len(crossref_summary)} flagged conversations")
    print(f"  {len(tokenomics_capacity_consumption)} Tokenomics capacity rows, "
          f"{len(tokenomics_entitlement_consumption)} entitlement rows, "
          f"{len(tokenomics_entitlement_per_agent)} per-agent rows, "
          f"{len(tokenomics_entitlement_per_user)} per-user rows")
    print(f"  {len(m365_usage_users)} M365 usage user rows")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    p  = Path(settings.output_path)
    output_path = str(p.parent / f"{p.stem}_{ts}{p.suffix}")
    build_workbook(
        events, connector_calls, output_path,
        agents=agents, environments=environments,
        publishers=publishers, dlp_policies=dlp_policies,
        agent_solutions=agent_solutions, aad_users=aad_users,
        model_calls=model_calls,
        health_detail=health_detail, crossref_summary=crossref_summary,
        copilot_usage=copilot_usage, teams_usage=teams_usage,
        kpi_snapshots=kpi_snapshots,
        viva_person_insights=viva_person_insights,
        viva_reports_cs_session_metrics=viva_reports_cs_session_metrics,
        viva_reports_cs_topic_metrics=viva_reports_cs_topic_metrics,
        viva_reports_cs_weekly_active_users=viva_reports_cs_weekly_active_users,
        viva_reports_cs_autonomous_metrics=viva_reports_cs_autonomous_metrics,
        viva_reports_cs_copilot_agents=viva_reports_cs_copilot_agents,
        copilot_count_summary=copilot_count_summary,
        copilot_count_trend=copilot_count_trend,
        copilot_packages=copilot_packages,
        o365_active_users=o365_active_users,
        m365_app_users=m365_app_users,
        viva_reports_copilot_adoption=viva_reports_copilot_adoption,
        viva_reports_copilot_impact=viva_reports_copilot_impact,
        m365_admin_agent_inventory=m365_admin_agent_inventory,
        m365_usage_agents=m365_usage_agents,
        m365_usage_agent_users=m365_usage_agent_users,
        m365_usage_users=m365_usage_users,
        viva_reports_cs_action_metrics=viva_reports_cs_action_metrics,
        tokenomics_capacity_consumption=tokenomics_capacity_consumption,
        tokenomics_entitlement_consumption=tokenomics_entitlement_consumption,
        tokenomics_entitlement_per_agent=tokenomics_entitlement_per_agent,
        tokenomics_entitlement_per_user=tokenomics_entitlement_per_user,
    )


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "all"

    if command == "sync":
        cmd_sync()
    elif command == "export":
        store  = SqliteStore(settings.db_path)
        run_id = store.get_last_run_id()
        store.close()
        if not run_id:
            print("No sync runs found — run 'sync' first.")
            sys.exit(1)
        cmd_export(run_id)
    elif command == "all":
        run_id = cmd_sync()
        print()
        cmd_export(run_id)
    elif command == "import-viva":
        report_dir = sys.argv[2] if len(sys.argv) > 2 else "."
        cmd_import_viva(report_dir)
    else:
        print(f"Unknown command: {command}")
        print("Usage: python -m src.main [sync|export|all|import-viva <dir>]")
        sys.exit(1)


if __name__ == "__main__":
    main()
