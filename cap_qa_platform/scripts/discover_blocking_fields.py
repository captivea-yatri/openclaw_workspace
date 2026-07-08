"""Discover project, sale.order, and timesheet fields relevant to color computation."""
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
print(f"Authenticated uid={client.uid}\n")

models = ["project.project", "sale.order", "account.move", "project.task", "account.analytic.line"]
KEYWORDS = ("block", "time", "sheet", "late", "follow", "allow", "authoriz", "prepaid", "x_studio")

for model in models:
    try:
        fields = client.call(model, "fields_get", [], attributes=["string", "type"])
    except Exception as exc:
        print(f"{model}: SKIP ({exc})")
        continue
    matches = {
        name: meta
        for name, meta in fields.items()
        if any(kw in name.lower() for kw in KEYWORDS)
    }
    if not matches:
        print(f"{model}: no relevant fields")
        continue
    print(f"\n{model} - {len(matches)} relevant fields:")
    for name, meta in sorted(matches.items()):
        label = (meta.get("string") or "")[:50]
        print(f"  {name:<45} | {meta.get('type', ''):<10} | {label}")
