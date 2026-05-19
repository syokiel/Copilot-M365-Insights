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
    # Power Platform / Dataverse
    dataverse_url: str = ""
    powerplatform_environment_id: str = ""
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
        self.dataverse_url = os.getenv("DATAVERSE_URL", self.dataverse_url)
        self.powerplatform_environment_id = os.getenv("POWERPLATFORM_ENVIRONMENT_ID", self.powerplatform_environment_id)
        self.mcp_tenant_id = os.getenv("MCP_TENANT_ID", self.mcp_tenant_id)
        self.mcp_app_id_uri = os.getenv("MCP_APP_ID_URI", self.mcp_app_id_uri)
        self.mcp_api_key = os.getenv("MCP_API_KEY", self.mcp_api_key)
        self.port = int(os.getenv("PORT", str(self.port)))

    @property
    def lookback(self) -> timedelta:
        return timedelta(days=self.lookback_days)

    def validate(self) -> None:
        if not self.log_analytics_workspace_id:
            raise EnvironmentError("Missing required env var: LOG_ANALYTICS_WORKSPACE_ID")


settings = Settings()
