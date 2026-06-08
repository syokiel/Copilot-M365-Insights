from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import os


class AuthMethod(str, Enum):
    SP  = "sp"   # service principal (client_id + client_secret)
    CLI = "cli"  # az login / interactive browser fallback


@dataclass
class DataSourceConfig:
    key: str            # env-var prefix, e.g. "LOG_ANALYTICS"
    label: str          # display name shown in log output
    auth_method: AuthMethod = AuthMethod.SP
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    # Optional: set {PREFIX}_CLI_ACCOUNT=user@domain.com to use a specific account
    # for CLI auth.  Datasources with different cli_account values get independent
    # credentials even within the same tenant — each prompts separately if needed.
    # Datasources sharing the same (tenant_id, cli_account) reuse one credential.
    cli_account: str = ""
    extras: dict = field(default_factory=dict)


# Definition order determines run order within the same auth bucket.
# (label, env_prefix, {extras_field: [env_keys in priority order]})
_DEFS: list[tuple[str, str, dict[str, list[str]]]] = [
    ("Log Analytics",        "LOG_ANALYTICS",      {
        "workspace_id": ["LOG_ANALYTICS_WORKSPACE_ID"],
    }),
    ("Azure Monitor",        "AZURE_MONITOR",       {
        "workspace_id":    ["AZURE_MONITOR_WORKSPACE_ID"],
        "subscription_id": ["AZURE_MONITOR_SUBSCRIPTION_ID"],
    }),
    ("Power Platform Admin", "POWERPLATFORM_ADMIN", {
        "environment_id": ["POWERPLATFORM_ADMIN_ENVIRONMENT_ID", "POWERPLATFORM_ENVIRONMENT_ID"],
        "agent_env_ids":  ["POWERPLATFORM_ADMIN_ENV_IDS", "POWERPLATFORM_AGENT_ENV_IDS"],
    }),
    ("Global Discovery",     "GLOBAL_DISCOVERY",    {}),
    ("Dataverse",            "DATAVERSE",           {
        "url": ["DATAVERSE_URL"],
    }),
    ("Graph",                "GRAPH",               {}),
    ("Viva",                 "VIVA",                {}),
    ("Purview",              "PURVIEW",             {
        "account_name": ["PURVIEW_ACCOUNT_NAME"],
        "endpoint":     ["PURVIEW_ENDPOINT"],
    }),
    ("Defender",             "DEFENDER",            {
        "subscription_id": ["DEFENDER_SUBSCRIPTION_ID", "AZURE_MONITOR_SUBSCRIPTION_ID"],
        "workspace_id":    ["DEFENDER_WORKSPACE_ID"],
    }),
]


def load_datasource_configs() -> list[DataSourceConfig]:
    """
    Build one DataSourceConfig per data source from environment variables.

    Each source inherits the global AZURE_TENANT_ID / AZURE_CLIENT_ID /
    AZURE_CLIENT_SECRET unless overridden with a {PREFIX}_* variant.

    Auth method defaults:
      - "sp"  if global AZURE_CLIENT_ID + AZURE_CLIENT_SECRET are both set
      - "cli" otherwise (az login / interactive browser)

    Override per source with {PREFIX}_AUTH=sp|cli.
    """
    global_tenant = os.getenv("AZURE_TENANT_ID", "")
    global_client = os.getenv("AZURE_CLIENT_ID", "")
    global_secret = os.getenv("AZURE_CLIENT_SECRET", "")
    default_auth = AuthMethod.SP if (global_client and global_secret) else AuthMethod.CLI

    configs: list[DataSourceConfig] = []
    for label, prefix, extras_map in _DEFS:
        raw = os.getenv(f"{prefix}_AUTH", default_auth.value)
        try:
            auth = AuthMethod(raw.lower())
        except ValueError:
            auth = default_auth

        tenant      = os.getenv(f"{prefix}_TENANT_ID",   global_tenant)
        client      = os.getenv(f"{prefix}_CLIENT_ID",   global_client)
        secret      = os.getenv(f"{prefix}_CLIENT_SECRET", global_secret)
        cli_account = os.getenv(f"{prefix}_CLI_ACCOUNT", "")

        extras: dict[str, str] = {}
        for field_name, env_keys in extras_map.items():
            for key in env_keys:
                val = os.getenv(key, "")
                if val:
                    extras[field_name] = val
                    break

        configs.append(DataSourceConfig(
            key=prefix,
            label=label,
            auth_method=auth,
            tenant_id=tenant,
            client_id=client,
            client_secret=secret,
            cli_account=cli_account,
            extras=extras,
        ))
    return configs


def get_datasource(configs: list[DataSourceConfig], key: str) -> DataSourceConfig | None:
    return next((c for c in configs if c.key == key), None)
