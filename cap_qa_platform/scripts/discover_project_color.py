"""Discover project color fields on project.project."""
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

fields = client.call(
    "project.project",
    "fields_get",
    [],
    attributes=["string", "type", "help"],
)

# Filter for color-related fields
color_fields = {
    name: meta
    for name, meta in fields.items()
    if "color" in name.lower()
    or "color" in (meta.get("string", "") or "").lower()
    or "status" in name.lower()
    or "alert" in (meta.get("string", "") or "").lower()
    or "warning" in name.lower()
}

print(f"\nFound {len(color_fields)} color/status related fields:")
print(f"{'Name':<50} | {'Type':<12} | {'Label':<35}")
print("-" * 100)
for name, meta in sorted(color_fields.items()):
    label = meta.get("string", "") or ""
    sel = ""
    if meta.get("type") == "selection":
        sel = str(meta.get("selection", "") or "")[:60]
    print(f"{name:<50} | {meta.get('type', ''):<12} | {label[:35]:<35}")
    if sel:
        print(f"  └─ options: {sel}")
