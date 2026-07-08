#!/usr/bin/env python3
"""Discover timesheet-related fields on product.product."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cap_qa_platform.staging import load_staging_env
import os

load_staging_env()

from cap_qa_platform.rpc.client import OdooRPCClient

url = os.environ.get("ODOO_URL", "http://localhost:8069")
db = os.environ.get("ODOO_DB", "odoo")
user = os.environ.get("ODOO_USER", "admin")
pwd = os.environ.get("ODOO_PASSWORD", "admin")

client = OdooRPCClient(url, db, user, pwd)
client.authenticate()
print(f"Authenticated uid={client.uid}")

# Get fields on product.product
fields = client.call(
    "product.product",
    "fields_get",
    [],
    attributes=["string", "type", "help"],
)

# Filter for timesheet-related fields
timesheet_fields = {
    name: meta
    for name, meta in fields.items()
    if any(kw in name.lower() for kw in ("time", "sheet", "service", "policy", "prepaid", "hour", "track"))
    or any(kw in (meta.get("string", "") or "").lower() for kw in ("time", "sheet", "service", "policy", "prepaid", "hour", "track"))
}

print(f"\nFound {len(timesheet_fields)} timesheet/service related fields:")
print(f"{'Name':<35} | {'Type':<10} | {'Label':<35}")
print("-" * 90)
for name, meta in sorted(timesheet_fields.items()):
    print(f"{name:<35} | {meta.get('type', 'unknown'):<10} | {meta.get('string', '')[:35]:<35}")
