from __future__ import annotations

from azure.core.credentials import TokenCredential
from azure.identity import (
    AzureCliCredential,
    ChainedTokenCredential,
    ClientSecretCredential,
    InteractiveBrowserCredential,
)
from azure.monitor.query import LogsQueryClient
from msgraph import GraphServiceClient

from config.datasources import AuthMethod, DataSourceConfig


class AuthManager:
    """
    Provides credentials per datasource with deduplication.

    SP credentials are keyed by (tenant_id, client_id, client_secret) — one
    ClientSecretCredential object is reused across all datasources that share
    the same principal.

    CLI credentials are keyed by tenant_id — one ChainedTokenCredential
    (az login → interactive browser) is created per unique tenant so the
    user is prompted at most once per tenant regardless of how many datasources
    share it.
    """

    def __init__(self) -> None:
        self._sp:  dict[tuple[str, str, str], TokenCredential] = {}
        self._cli: dict[str, TokenCredential] = {}

    def get_credential(self, ds: DataSourceConfig) -> TokenCredential:
        if ds.auth_method == AuthMethod.SP:
            key = (ds.tenant_id, ds.client_id, ds.client_secret)
            if key not in self._sp:
                self._sp[key] = ClientSecretCredential(
                    tenant_id=ds.tenant_id,
                    client_id=ds.client_id,
                    client_secret=ds.client_secret,
                )
            return self._sp[key]

        tid = ds.tenant_id or ""
        if tid not in self._cli:
            self._cli[tid] = ChainedTokenCredential(
                AzureCliCredential(tenant_id=tid or None),
                InteractiveBrowserCredential(tenant_id=tid or None),
            )
        return self._cli[tid]

    def logs_client(self, ds: DataSourceConfig) -> LogsQueryClient:
        return LogsQueryClient(self.get_credential(ds))

    def graph_client(self, ds: DataSourceConfig) -> GraphServiceClient:
        return GraphServiceClient(
            credentials=self.get_credential(ds),
            scopes=["https://graph.microsoft.com/.default"],
        )

    @staticmethod
    def fetch_order(configs: list[DataSourceConfig]) -> list[DataSourceConfig]:
        """
        Return configs in execution order:
          1. SP-authenticated first — no user interaction required.
          2. CLI-authenticated grouped by tenant_id — sources sharing a tenant
             run consecutively so az login is prompted at most once per tenant.

        Within each group, definition order from datasources._DEFS is preserved.
        """
        sp = [c for c in configs if c.auth_method == AuthMethod.SP]
        cli_by_tenant: dict[str, list[DataSourceConfig]] = {}
        for c in configs:
            if c.auth_method == AuthMethod.CLI:
                cli_by_tenant.setdefault(c.tenant_id, []).append(c)
        cli = [cfg for grp in cli_by_tenant.values() for cfg in grp]
        return sp + cli


# ---------------------------------------------------------------------------
# Backward-compat module-level API (used by mcp_server, configure_agent_telemetry, etc.)
# Backed by a lazily-initialised singleton AuthManager.
# ---------------------------------------------------------------------------

_manager: AuthManager | None = None


def _default_manager() -> AuthManager:
    global _manager
    if _manager is None:
        _manager = AuthManager()
    return _manager


def _default_ds() -> DataSourceConfig:
    from config.settings import settings
    return DataSourceConfig(
        key="_default",
        label="_default",
        auth_method=AuthMethod.SP if (settings.azure_client_id and settings.azure_client_secret) else AuthMethod.CLI,
        tenant_id=settings.azure_tenant_id,
        client_id=settings.azure_client_id,
        client_secret=settings.azure_client_secret,
    )


def get_credential() -> TokenCredential:
    return _default_manager().get_credential(_default_ds())


def get_logs_client() -> LogsQueryClient:
    return LogsQueryClient(get_credential())


def get_graph_client() -> GraphServiceClient:
    return GraphServiceClient(
        credentials=get_credential(),
        scopes=["https://graph.microsoft.com/.default"],
    )


def get_power_platform_token() -> str:
    return get_credential().get_token("https://api.powerplatform.com/.default").token
