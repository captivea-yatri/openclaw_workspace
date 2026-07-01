#!/usr/bin/env python3
"""
Standalone Odoo 19 RPC test for partner status transition on sale order
confirmation and cancellation.

Scenario:
1. Create a company partner.
2. Find an assistance offer (type='assistance').
3. Find two service products linked to that offer.
4. Create a sale order with the two lines and the offer.
5. Confirm the sale order → partner status should become 'customer'.
6. Run the "Create/Link Project" wizard (operation='create') → a project is
   created and linked to the sale order lines.
7. Cancel the sale order → partner status should become 'old_customer'.
8. Verify that no ``quality.issue.log`` records exist for the created project.

The script uses the ``OdooRpcClient`` helper (XML‑RPC by default, JSON‑RPC if
available) which is part of the existing test suite.  It follows the pattern of
``cap_quality_issue_log/scripts/test_quality_issue_approval_rpc.py``.

Running:
    python3 test_so_cancel_old_customer_status_rpc.py [--no-cleanup]

Environment variables (or CLI args) are read automatically by ``OdooRpcClient``:
    ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD, ODOO_RPC
"""

import sys
import argparse
import datetime
import logging
from typing import List, Tuple, Dict, Any

# Assuming the helper module exists in the workspace root or PYTHONPATH.
# It provides OdooRpcClient with ``search``, ``search_read``, ``read``, ``create``,
# ``call`` and ``search_count`` methods similar to the existing RPC test scripts.
from test_quality_issue_approval_rpc import OdooRpcClient, RpcError  # type: ignore

LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


def unique_suffix() -> str:
    """Return a short unique suffix based on current timestamp."""
    return datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S%f")[:15]


class TestSaleOrderCancelOldCustomerStatus:
    def __init__(self, client: OdooRpcClient, no_cleanup: bool = False):
        self.rpc = client
        self.cleanup_tracker: List[Tuple[str, int]] = []  # (model, record_id)
        self.no_cleanup = no_cleanup
        self.suffix = unique_suffix()

    def _track(self, model: str, record_id: int):
        if not self.no_cleanup:
            self.cleanup_tracker.append((model, record_id))

    def _cleanup(self):
        # Reverse order cleanup: delete sale order → project → partner
        for model, record_id in reversed(self.cleanup_tracker):
            try:
                self.rpc.unlink(model, [record_id])
                LOGGER.info("[CLEANUP] Deleted %s %s", model, record_id)
            except Exception as exc:  # pragma: no cover
                LOGGER.warning("[CLEANUP] Failed to delete %s %s: %s", model, record_id, exc)

    def run(self):
        try:
            self.authenticate()
            partner_id = self.create_partner()
            offer = self.find_assistance_offer()
            product_ids = self.find_two_service_products(offer["id"])  # type: ignore
            so_id = self.create_sale_order(partner_id, offer, product_ids)
            self.confirm_sale_order(so_id)
            self.assert_partner_status(partner_id, "customer")
            project_id = self.create_link_project(so_id)
            self.cancel_sale_order(so_id)
            self.assert_partner_status(partner_id, "old_customer")
            self.assert_no_quality_logs(project_id)
            LOGGER.info("[PASS] All assertions succeeded.")
        finally:
            if not self.no_cleanup:
                self._cleanup()

    def authenticate(self):
        # Authentication is performed inside OdooRpcClient construction.
        # This method exists for parity with other scripts.
        LOGGER.info("[INFO] Authenticated to Odoo instance.")

    def create_partner(self) -> int:
        name = f"TestPartner_{self.suffix}"
        vals = {
            "name": name,
            "company_type": "company",
            "is_company": True,
        }
        partner_id = self.rpc.create("res.partner", vals)
        self._track("res.partner", partner_id)
        LOGGER.info("[PASS] Created partner %s (id=%s)", name, partner_id)
        return partner_id

    def find_assistance_offer(self) -> Dict[str, Any]:
        # Primary search by the explicit 'type' field, fallback by name.
        offers = self.rpc.search_read(
            "offer.offer",
            [["type", "=", "assistance"]],
            ["id", "business_unit_ids", "business_localisation_ids"],
            limit=1,
        )
        if not offers:
            offers = self.rpc.search_read(
                "offer.offer",
                [["name", "ilike", "assistance"]],
                ["id", "business_unit_ids", "business_localisation_ids"],
                limit=1,
            )
        if not offers:
            raise RpcError("Assistance offer not found.")
        offer = offers[0]
        LOGGER.info("[PASS] Found assistance offer id=%s", offer["id"])
        return offer

    def find_two_service_products(self, offer_id: int) -> List[int]:
        domain = [
            ["offer_ids", "in", [offer_id]],
            ["type", "=", "service"],
            ["sale_ok", "=", True],
        ]
        fields = ["id"]
        products = self.rpc.search_read("product.product", domain, fields, limit=2)
        if len(products) < 2:
            raise RpcError("Could not find two service products linked to the offer.")
        product_ids = [p["id"] for p in products]
        LOGGER.info("[PASS] Selected service products %s", product_ids)
        return product_ids

    def create_sale_order(
        self,
        partner_id: int,
        offer: Dict[str, Any],
        product_ids: List[int],
    ) -> int:
        # Derive business unit and localisation from the offer (first records).
        bu_id = offer.get("business_unit_ids")
        loc_id = offer.get("business_localisation_ids")
        if isinstance(bu_id, list):
            bu_id = bu_id[0] if bu_id else None
        if isinstance(loc_id, list):
            loc_id = loc_id[0] if loc_id else None
        if not (bu_id and loc_id):
            raise RpcError("Offer missing business unit or localisation.")
        order_vals = {
            "partner_id": partner_id,
            "business_unit_id": bu_id,
            "business_localisation_id": loc_id,
            "offer_id": offer["id"],
            "order_line": [
                (0, 0, {"product_id": product_ids[0], "product_uom_qty": 1.0}),
                (0, 0, {"product_id": product_ids[1], "product_uom_qty": 1.0}),
            ],
        }
        so_id = self.rpc.create("sale.order", order_vals)
        self._track("sale.order", so_id)
        LOGGER.info("[PASS] Created sale.order id=%s", so_id)
        return so_id

    def confirm_sale_order(self, so_id: int):
        self.rpc.call("sale.order", "action_confirm", [so_id])
        LOGGER.info("[PASS] Sale order %s confirmed.", so_id)

    def cancel_sale_order(self, so_id: int):
        self.rpc.call("sale.order", "action_cancel", [so_id])
        LOGGER.info("[PASS] Sale order %s cancelled.", so_id)

    def assert_partner_status(self, partner_id: int, expected_status: str):
        partner = self.rpc.read("res.partner", [partner_id], ["status"])[0]
        actual = partner.get("status")
        if actual != expected_status:
            raise AssertionError(
                f"Partner status is '{actual}', expected '{expected_status}'."
            )
        LOGGER.info(
            "[PASS] Partner %s status == '%s'",
            partner_id,
            expected_status,
        )

    def create_link_project(self, so_id: int) -> int:
        # Create wizard with operation='create'
        wiz_id = self.rpc.create("link.so.project.wizard", {"operation": "create"})
        self._track("link.so.project.wizard", wiz_id)
        # Call wizard method with appropriate active context.
        context = {
            "active_model": "sale.order",
            "active_id": so_id,
            "active_ids": [so_id],
        }
        self.rpc.call(
            "link.so.project.wizard",
            "link_so_project",
            [wiz_id],
            context=context,
        )
        LOGGER.info("[PASS] link_so_project wizard executed (wizard id=%s).", wiz_id)
        # Retrieve project_id from sale order lines.
        lines = self.rpc.search_read(
            "sale.order.line",
            [["order_id", "=", so_id]],
            ["project_id"],
            limit=1,
        )
        if not lines:
            raise AssertionError("No sale.order.line found for the sale order.")
        proj_field = lines[0].get("project_id")
        if not proj_field:
            raise AssertionError("Project not linked to sale order line.")
        # project_id is a many2one represented as [id, name]
        project_id = proj_field[0] if isinstance(proj_field, list) else proj_field
        self._track("project.project", project_id)
        LOGGER.info("[PASS] Project created with id=%s", project_id)
        return project_id

    def assert_no_quality_logs(self, project_id: int):
        count = self.rpc.search_count(
            "quality.issue.log", [("project_id", "=", project_id)]
        )
        if count != 0:
            raise AssertionError(
                f"Expected 0 quality.issue.log records for project {project_id}, found {count}."
            )
        LOGGER.info(
            "[PASS] No quality.issue.log records for project %s (count=%s)",
            project_id,
            count,
        )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Odoo RPC test: partner status after SO cancel",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Do not delete created records after the test.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    import os
client = connect(
    os.getenv("ODOO_URL"),
    os.getenv("ODOO_DB"),
    os.getenv("ODOO_USER"),
    os.getenv("ODOO_PASSWORD"),
)
    test = TestSaleOrderCancelOldCustomerStatus(client, no_cleanup=args.no_cleanup)
    try:
        test.run()
    except RpcError as e:
        LOGGER.error("[FAIL] RPC error: %s", e)
        sys.exit(1)
    except AssertionError as e:
        LOGGER.error("[FAIL] Assertion failed: %s", e)
        sys.exit(1)
    except Exception as e:  # pragma: no cover
        LOGGER.exception("[FAIL] Unexpected error: %s", e)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
