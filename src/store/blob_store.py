from pathlib import Path

from azure.identity import (
    AzureCliCredential,
    ChainedTokenCredential,
    ClientSecretCredential,
    InteractiveBrowserCredential,
    ManagedIdentityCredential,
)
from azure.storage.blob import BlobServiceClient


def _blob_client(account: str, container: str, blob: str, use_managed_identity: bool = False):
    """Returns a BlobClient.

    Auth priority:
      1. Managed identity  (use_managed_identity=True — Azure-hosted deployments)
      2. Service principal (AZURE_CLIENT_ID + AZURE_CLIENT_SECRET both set)
      3. Azure CLI         (az login), optionally scoped to AZURE_STORAGE_CLI_ACCOUNT
    """
    url = f"https://{account}.blob.core.windows.net"
    if use_managed_identity:
        credential = ManagedIdentityCredential()
    else:
        from config.settings import settings
        if settings.azure_client_id and settings.azure_client_secret:
            credential = ClientSecretCredential(
                tenant_id=settings.azure_tenant_id,
                client_id=settings.azure_client_id,
                client_secret=settings.azure_client_secret,
            )
        else:
            cli_account = settings.azure_storage_cli_account or None
            credential = ChainedTokenCredential(
                AzureCliCredential(tenant_id=settings.azure_tenant_id or None),
                InteractiveBrowserCredential(
                    tenant_id=settings.azure_tenant_id or None,
                    login_hint=cli_account,
                ),
            )
    return BlobServiceClient(account_url=url, credential=credential).get_blob_client(
        container=container, blob=blob
    )


def upload_db(db_path: str, account: str, container: str, blob: str) -> None:
    client = _blob_client(account, container, blob)
    with open(db_path, "rb") as f:
        client.upload_blob(f, overwrite=True)
    print(f"Uploaded {db_path} → blob://{account}/{container}/{blob}")


def download_db(db_path: str, account: str, container: str, blob: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    client = _blob_client(account, container, blob, use_managed_identity=True)
    with open(db_path, "wb") as f:
        f.write(client.download_blob().readall())
    print(f"Downloaded blob://{account}/{container}/{blob} → {db_path}")
