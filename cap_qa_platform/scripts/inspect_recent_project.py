"""Read a specific project to see what colors are actually populated."""
import sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cap_qa_platform.staging import load_staging_env
load_staging_env()
from cap_qa_platform.rpc.client import OdooRPCClient

client = OdooRPCClient(
    os.environ["ODOO_URL"],
    os.environ["ODOO_DB"],
    os.environ["ODOO_USER"],
    os.environ["ODOO_PASSWORD"],
)
client.authenticate()
print(f"Authenticated uid={client.uid}")

# Get the most recent project
projects = client.search_read(
    "project.project",
    [],
    ["id", "name", "color", "last_update_color", "last_update_status"],
    order="id desc",
    limit=5,
)

print(f"\nMost recent projects:")
print(f"{'ID':<10} | {'Name':<40} | {'Color':<6} | {'Upd.color':<10} | {'Update status':<20}")
print("-" * 95)
for p in projects:
    print(f"{p.get('id', ''):<10} | {p.get('name', '')[:40]:<40} | {p.get('color', '')!s:<6} | {p.get('last_update_color', '')!s:<10} | {p.get('last_update_status', '')!s:<20}")

print("\nlast_update_status options:")
fs = client.fields_get("project.project", attributes=["string", "selection"])
sel = fs.get("last_update_status", {}).get("selection", [])
print(sel)
