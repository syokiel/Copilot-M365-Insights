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
        self.azure_monitor_workspace_id = os.getenv("AZURE_MONITOR_WORKSPACE_ID", self.azure_monitor_workspace_id)
        self.azure_monitor_subscription_id = os.getenv("AZURE_MONITOR_SUBSCRIPTION_ID", self.azure_monitor_subscription_id)
        dv = os.getenv("DATAVERSE_URL", self.dataverse_url).strip()
        if dv and not dv.startswith("http"):
            dv = f"https://{dv}"
        self.dataverse_url = dv
        self.powerplatform_environment_id = os.getenv("POWERPLATFORM_ENVIRONMENT_ID", self.powerplatform_environment_id)
        raw_ids = os.getenv("POWERPLATFORM_AGENT_ENV_IDS", "")
        self.agent_env_ids = {i.strip() for i in raw_ids.split(",") if i.strip()} if raw_ids else set()
        self.total_licenses = int(os.getenv("TOTAL_LICENSES", str(self.total_licenses)))
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
