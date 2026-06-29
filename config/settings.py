import os
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# Build a combined CA bundle: certifi standard certs + corporate proxy CA (if present)
def _setup_ssl() -> None:
    proxy_ca = Path(__file__).parent / "proxy-ca.pem"
    if not proxy_ca.exists():
        return
    try:
        import certifi
        combined = tempfile.NamedTemporaryFile(
            delete=False, suffix=".pem", prefix="ca-bundle-"
        )
        combined.write(Path(certifi.where()).read_bytes())
        combined.write(proxy_ca.read_bytes())
        combined.flush()
        os.environ.setdefault("REQUESTS_CA_BUNDLE", combined.name)
        os.environ.setdefault("SSL_CERT_FILE", combined.name)
    except Exception:
        pass

_setup_ssl()


@dataclass
class Settings:
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    log_analytics_workspace_id: str = ""
    lookback_days: int = 30
    output_path: str = "agent_telemetry.xlsx"
    db_path: str = "agent_telemetry.db"
    # Blob storage (sync upload + MCP server download)
    azure_storage_account: str = ""
    azure_storage_container: str = "telemetry-data"
    azure_storage_db_blob: str = "agent_telemetry.db"
    azure_storage_cli_account: str = ""
    # Optional dedicated service principal for blob storage (overrides global SP)
    azure_storage_tenant_id: str = ""
    azure_storage_client_id: str = ""
    azure_storage_client_secret: str = ""
    # Azure Monitor (optional — cross-reference sheet)
    azure_monitor_workspace_id: str = ""
    azure_monitor_subscription_id: str = ""
    # Power Platform / Dataverse
    dataverse_url: str = ""
    powerplatform_environment_id: str = ""
    # Comma-separated list of environment IDs to fetch agents from.
    # When set, only these environments are iterated (useful in large tenants).
    # Leave blank to iterate all discovered environments.
    agent_env_ids: set = None  # populated in __post_init__
    # Optional: total Copilot license count for activation rate KPI.
    # Not derivable from usage data — set from your admin centre licence count.
    total_licenses: int = 0
    # Viva CS (Copilot Studio) analytics CSV export folder.
    # Set VIVA_REPORT_CS_DIR (or VIVA_REPROT_CS_DIR) to the folder containing
    # the agent CSV exports — imported automatically on every sync/all run.
    viva_reports_cs_report_dir: str = ""
    # Direct file paths for Copilot Adoption and Impact reports.
    viva_report_adoption: str = ""
    viva_report_impact: str = ""
    # Agent → Journey → Persona mapping (static CSV seed for XLA experience model)
    agent_journey_map: str = ""
    # M365 Admin Center CSV exports
    m365_admin_agent_inventory: str = ""
    # M365 Usage reports
    m365_usage_report_agents: str = ""
    m365_usage_report_agent_users: str = ""
    m365_usage_report_users: str = ""
    # Power Platform Admin Center — Copilot credit consumption CSV exports (Tokenomics_* tables)
    ppadmin_licenses_cs_consumption_manageagents: str = ""
    ppadmin_licenses_cs_consumption_env: str = ""
    ppadmin_licenses_cs_consumption_agent: str = ""
    ppadmin_licenses_cs_consumption_user: str = ""
    # M365 Admin Center — Office 365 / Microsoft 365 Apps usage CSV exports
    m365_usage_activations_users: str = ""
    m365_usage_active_users_services: str = ""
    m365_usage_active_users_activity: str = ""
    m365_usage_active_users_counts: str = ""
    m365_usage_active_users_detail: str = ""
    m365_usage_proplus_platforms: str = ""
    m365_usage_proplus_counts: str = ""
    m365_usage_proplus_detail: str = ""
    # License inventory (M365 Admin Center → Billing → Licenses → Export)
    billing_licences: str = ""
    # MCP server (HTTP deployment)
    mcp_tenant_id: str = ""
    mcp_app_id_uri: str = ""
    mcp_api_key: str = ""
    port: int = 8000

    def __post_init__(self) -> None:
        self.azure_tenant_id = os.getenv("AZURE_TENANT_ID", self.azure_tenant_id)
        self.azure_client_id = os.getenv("AZURE_CLIENT_ID", self.azure_client_id)
        self.azure_client_secret = os.getenv("AZURE_CLIENT_SECRET", self.azure_client_secret)
        self.log_analytics_workspace_id = os.getenv(
            "LOG_ANALYTICS_WORKSPACE_ID", self.log_analytics_workspace_id
        )
        self.lookback_days = int(os.getenv("LOOKBACK_DAYS", str(self.lookback_days)))
        self.output_path = os.getenv("OUTPUT_PATH", self.output_path)
        self.db_path = os.getenv("DB_PATH", self.db_path)
        self.azure_storage_account = os.getenv("AZURE_STORAGE_ACCOUNT", self.azure_storage_account)
        self.azure_storage_container = os.getenv("AZURE_STORAGE_CONTAINER", self.azure_storage_container)
        self.azure_storage_db_blob = os.getenv("AZURE_STORAGE_DB_BLOB", self.azure_storage_db_blob)
        self.azure_storage_cli_account = os.getenv("AZURE_STORAGE_CLI_ACCOUNT", self.azure_storage_cli_account)
        self.azure_storage_tenant_id = os.getenv("AZURE_STORAGE_TENANT_ID") or os.getenv("AZURE_STORAGE_Tenant", self.azure_storage_tenant_id)
        self.azure_storage_client_id = os.getenv("AZURE_STORAGE_CLIENT_ID", self.azure_storage_client_id)
        self.azure_storage_client_secret = os.getenv("AZURE_STORAGE_CLIENT_SECRET", self.azure_storage_client_secret)
        self.azure_monitor_workspace_id = os.getenv("AZURE_MONITOR_WORKSPACE_ID", self.azure_monitor_workspace_id)
        self.azure_monitor_subscription_id = os.getenv("AZURE_MONITOR_SUBSCRIPTION_ID", self.azure_monitor_subscription_id)
        dv = os.getenv("DATAVERSE_URL", self.dataverse_url).strip()
        if dv and not dv.startswith("http"):
            dv = f"https://{dv}"
        self.dataverse_url = dv
        self.powerplatform_environment_id = os.getenv("POWERPLATFORM_ENVIRONMENT_ID", self.powerplatform_environment_id)
        raw_ids = (
            os.getenv("POWERPLATFORM_ADMIN_ENV_IDS")
            or os.getenv("POWERPLATFORM_AGENT_ENV_IDS", "")
        )
        self.agent_env_ids = {i.strip() for i in raw_ids.split(",") if i.strip()} if raw_ids else set()
        self.total_licenses = int(os.getenv("TOTAL_LICENSES", str(self.total_licenses)))
        self.viva_reports_cs_report_dir = (
            os.getenv("VIVA_REPORT_CS_DIR") or
            os.getenv("VIVA_REPROT_CS_DIR") or   # accept common typo
            os.getenv("VIVA_CS_REPORT_DIR", self.viva_reports_cs_report_dir)
        ).strip()
        self.viva_report_adoption = os.getenv("VIVA_REPORT_ADOPTION", self.viva_report_adoption).strip()
        self.viva_report_impact   = os.getenv("VIVA_REPORT_IMPACT",   self.viva_report_impact).strip()
        self.agent_journey_map = os.getenv("AGENT_JOURNEY_MAP", self.agent_journey_map).strip()
        self.m365_admin_agent_inventory   = os.getenv("M365ADMIN_AGENT_INVENTORY",   self.m365_admin_agent_inventory).strip()
        self.m365_usage_report_agents     = (
            os.getenv("M365ADMIN_USAGE_REPORT_AGENTS") or
            os.getenv("M365USAGE_REPORT_Agents") or
            os.getenv("M365Usage_REPORT_Agents", self.m365_usage_report_agents)
        ).strip()
        self.m365_usage_report_agent_users = (
            os.getenv("M365ADMIN_USAGE_REPORT_AGENTUSERS") or
            os.getenv("M365USAGE_REPORT_AgentUser") or
            os.getenv("M365Usage_REPORT_AgentUser", self.m365_usage_report_agent_users)
        ).strip()
        self.m365_usage_report_users = os.getenv(
            "M365ADMIN_USAGE_REPORT_USERS", self.m365_usage_report_users
        ).strip()
        self.ppadmin_licenses_cs_consumption_manageagents = (
            os.getenv("PPADMIN_LICENSES_CS_CONSUMPTION_MANAGEAGENTS") or
            os.getenv("PPADMIN_CAPACITY_CONSUMPTION", self.ppadmin_licenses_cs_consumption_manageagents)
        ).strip()
        self.ppadmin_licenses_cs_consumption_env = (
            os.getenv("PPADMIN_LICENSES_CS_CONSUMPTION_ENV") or
            os.getenv("PPADMIN_ENTITLEMENT_CONSUMPTION", self.ppadmin_licenses_cs_consumption_env)
        ).strip()
        self.ppadmin_licenses_cs_consumption_agent = os.getenv(
            "PPADMIN_LICENSES_CS_CONSUMPTION_AGENT", self.ppadmin_licenses_cs_consumption_agent
        ).strip()
        self.ppadmin_licenses_cs_consumption_user = os.getenv(
            "PPADMIN_LICENSES_CS_CONSUMPTION_USER", self.ppadmin_licenses_cs_consumption_user
        ).strip()
        self.m365_usage_activations_users    = os.getenv("M365USAGE_ACTIVATIONS_USERS",    self.m365_usage_activations_users).strip()
        self.m365_usage_active_users_services = os.getenv("M365USAGE_ACTIVE_USERS_SERVICES", self.m365_usage_active_users_services).strip()
        self.m365_usage_active_users_activity = os.getenv("M365USAGE_ACTIVE_USERS_ACTIVITY", self.m365_usage_active_users_activity).strip()
        self.m365_usage_active_users_counts  = os.getenv("M365USAGE_ACTIVE_USERS_COUNTS",  self.m365_usage_active_users_counts).strip()
        self.m365_usage_active_users_detail  = os.getenv("M365USAGE_ACTIVE_USERS_DETAIL",  self.m365_usage_active_users_detail).strip()
        self.m365_usage_proplus_platforms    = os.getenv("M365USAGE_PROPLUS_PLATFORMS",    self.m365_usage_proplus_platforms).strip()
        self.m365_usage_proplus_counts       = os.getenv("M365USAGE_PROPLUS_COUNTS",       self.m365_usage_proplus_counts).strip()
        self.m365_usage_proplus_detail       = os.getenv("M365USAGE_PROPLUS_DETAIL",       self.m365_usage_proplus_detail).strip()
        self.billing_licences                = os.getenv("BILLING_LICENCES",               self.billing_licences).strip()
        self.mcp_tenant_id = os.getenv("MCP_TENANT_ID", self.mcp_tenant_id)
        self.mcp_app_id_uri = os.getenv("MCP_APP_ID_URI", self.mcp_app_id_uri)
        self.mcp_api_key = os.getenv("MCP_API_KEY", self.mcp_api_key)
        self.port = int(os.getenv("PORT", str(self.port)))

    @property
    def lookback(self) -> timedelta:
        return timedelta(days=self.lookback_days)

    def validate(self) -> None:
        if not self.azure_tenant_id:
            raise EnvironmentError("Missing required env var: AZURE_TENANT_ID")
        # Global SP credentials must be fully set or fully absent.
        # Per-datasource overrides ({PREFIX}_CLIENT_ID / {PREFIX}_CLIENT_SECRET)
        # are validated independently by config.datasources.
        if bool(self.azure_client_id) != bool(self.azure_client_secret):
            missing = "AZURE_CLIENT_SECRET" if self.azure_client_id else "AZURE_CLIENT_ID"
            raise EnvironmentError(
                f"Partial global service principal config — set {missing} "
                "or remove both to use CLI auth (or set per-datasource credentials instead)"
            )


settings = Settings()
