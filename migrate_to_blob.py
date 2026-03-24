import os
import sqlite3
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient

load_dotenv(override=True)

DB_PATH = "gadaoromo.db"
UPLOAD_DIR = "static/uploads"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
container_name = os.environ.get("AZURE_STORAGE_CONTAINER")

blob_service = BlobServiceClient.from_connection_string(conn_str)
container = blob_service.get_container_client(container_name)

rows = c.execute("SELECT id, file_path FROM generated_tts_audio").fetchall()

uploaded = 0
missing = 0

for row_id, file_path in rows:
    if not file_path:
    continue

# Skip hvis allerede blob
if file_path.startswith("http"):
    continue

    filename = os.path.basename(file_path)
   local_path = os.path.join("static/uploads", filename)

    if not os.path.exists(local_path):
        missing += 1
        continue

    blob_name = filename

    with open(local_path, "rb") as data:
        container.upload_blob(blob_name, data, overwrite=True)

    blob_url = f"https://{blob_service.account_name}.blob.core.windows.net/{container_name}/{blob_name}"

    c.execute(
        "UPDATE generated_tts_audio SET file_path=? WHERE id=?",
        (blob_url, row_id),
    )

    uploaded += 1

conn.commit()
conn.close()

print("Uploaded:", uploaded)
print("Missing:", missing)