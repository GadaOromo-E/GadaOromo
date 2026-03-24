import os

try:
    from azure.storage.blob import BlobServiceClient, ContentSettings
except Exception:
    BlobServiceClient = None
    ContentSettings = None


def upload_file(local_path: str, blob_name: str) -> str:
    """
    Upload local file to Azure Blob and return public blob URL.
    Returns empty string on failure/missing config.
    """
    conn_str = (os.environ.get("AZURE_BLOB_CONNECTION_STRING") or "").strip()
    container_name = (os.environ.get("AZURE_BLOB_CONTAINER") or "").strip()
    prefix = (os.environ.get("AZURE_BLOB_PREFIX") or "tts").strip().strip("/")
    if (not conn_str) or (not container_name) or (not BlobServiceClient):
        return ""
    if (not local_path) or (not os.path.isfile(local_path)):
        return ""

    blob_key = f"{prefix}/{blob_name}" if prefix else blob_name
    try:
        svc = BlobServiceClient.from_connection_string(conn_str)
        container = svc.get_container_client(container_name)
        try:
            container.create_container()
        except Exception:
            pass
        blob = container.get_blob_client(blob_key)
        content_settings = ContentSettings(content_type="audio/mpeg") if ContentSettings else None
        with open(local_path, "rb") as fh:
            blob.upload_blob(fh, overwrite=True, content_settings=content_settings)
        return blob.url or ""
    except Exception:
        return ""
