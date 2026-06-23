#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone RPC test for cap_single_employee_for_multi_company (Odoo 19).

No odoo-bin / shell required. Run with plain Python 3:

    python3 models/test_cap_single_employee_for_multi_company_rpc.py
    python3 models/test_cap_single_employee_for_multi_company_rpc.py --protocol xmlrpc
    python3 models/test_cap_single_employee_for_multi_company_rpc.py \\
        --url http://localhost:8069 --db odoo --user admin --password admin

Tests custom logic via public RPC APIs using exact model/field names from:
  - models/hr_leave.py
  - models/hr_leave_allocation.py
  - models/res_users.py
  - wizard/hr_leave_allocation_generate_multi_wizard.py
  - views/ir_rule_views.xml (record rules deactivated)
"""
from __future__ import annotations

import argparse
import json
import sys
import xmlrpc.client
from datetime import date
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Configuration (override via CLI args)
# ---------------------------------------------------------------------------
DEFAULT_URL = "http://localhost:8069"
DEFAULT_DB = "odoo"
DEFAULT_USER = "admin"
DEFAULT_PASSWORD = "admin"
DEFAULT_PROTOCOL = "jsonrpc"  # jsonrpc | xmlrpc

MODULE_NAME = "cap_single_employee_for_multi_company"

# Odoo x2many command tuples (same as odoo.fields.Command)
CMD_CREATE = 0
CMD_SET = 6

# ---------------------------------------------------------------------------
# Technical names from models/hr_leave.py
# ---------------------------------------------------------------------------
MODEL_HR_LEAVE = "hr.leave"
FIELD_LEAVE_HOLIDAY_STATUS = "holiday_status_id"
FIELD_LEAVE_EMPLOYEE = "employee_id"
METHOD_LEAVE_CHECK_STATUS = "check_holiday_status_id"

# ---------------------------------------------------------------------------
# Technical names from models/hr_leave_allocation.py
# ---------------------------------------------------------------------------
MODEL_HR_LEAVE_ALLOCATION = "hr.leave.allocation"
FIELD_ALLOC_HOLIDAY_TYPE = "holiday_type"
FIELD_ALLOC_HOLIDAY_STATUS = "holiday_status_id"
FIELD_ALLOC_EMPLOYEE = "employee_id"
FIELD_ALLOC_MODE_COMPANY = "mode_company_id"
FIELD_ALLOC_NUMBER_OF_DAYS = "number_of_days"
METHOD_ALLOC_GET_HOLIDAY_TYPE = "_get_new_holiday_type"

# ---------------------------------------------------------------------------
# Technical names from models/res_users.py
# ---------------------------------------------------------------------------
MODEL_RES_USERS = "res.users"
MODEL_HR_EMPLOYEE = "hr.employee"
FIELD_USER_EMPLOYEE = "employee_id"

# ---------------------------------------------------------------------------
# Technical names from wizard/hr_leave_allocation_generate_multi_wizard.py
# ---------------------------------------------------------------------------
MODEL_ALLOC_MULTI_WIZARD = "hr.leave.allocation.generate.multi.wizard"
FIELD_WIZARD_ALLOCATION_MODE = "allocation_mode"
METHOD_WIZARD_GET_HOLIDAY_TYPE = "_get_custom_holiday_type"

# ---------------------------------------------------------------------------
# Supporting models
# ---------------------------------------------------------------------------
MODEL_RES_COMPANY = "res.company"
MODEL_HR_LEAVE_TYPE = "hr.leave.type"
MODEL_IR_RULE = "ir.rule"

# Record rules deactivated by views/ir_rule_views.xml
RULE_XML_IDS = [
    "hr.hr_employee_public_comp_rule",
    "hr.hr_employee_comp_rule",
    "hr.ir_rule_hr_contract_multi_company",
    "hr_appraisal.hr_appraisal_comp_rule",
]

EXPECTED_HOLIDAY_TYPE_KEYS = {"employee", "company"}


class OdooRPCClient:
    """Thin Odoo 19 RPC client (JSON-RPC or XML-RPC)."""

    def __init__(self, url: str, db: str, username: str, password: str, protocol: str = "jsonrpc"):
        self.url = url.rstrip("/")
        self.db = db
        self.username = username
        self.password = password
        self.protocol = protocol.lower()
        self.uid: int | None = None
        self._json_id = 0
        self._xml_common = None
        self._xml_models = None

    def authenticate(self) -> int:
        if self.protocol == "xmlrpc":
            self._xml_common = xmlrpc.client.ServerProxy(
                f"{self.url}/xmlrpc/2/common", allow_none=True
            )
            self._xml_models = xmlrpc.client.ServerProxy(
                f"{self.url}/xmlrpc/2/object", allow_none=True
            )
            uid = self._xml_common.authenticate(self.db, self.username, self.password, {})
            if not uid:
                raise RuntimeError(
                    "Authentication failed. Check URL, database, username, and password."
                )
            self.uid = uid
            return uid

        uid = self._jsonrpc(
            "common", "authenticate", [self.db, self.username, self.password, {}]
        )
        if not uid:
            raise RuntimeError(
                "Authentication failed. Check URL, database, username, and password."
            )
        self.uid = uid
        return uid

    def _jsonrpc(self, service: str, method: str, args: list) -> Any:
        self._json_id += 1
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": self._json_id,
        }
        req = Request(
            f"{self.url}/jsonrpc",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"HTTP error {exc.code}: {exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"Cannot reach Odoo at {self.url}: {exc}") from exc

        if body.get("error"):
            err = body["error"]
            msg = err.get("data", {}).get("message") or err.get("message") or str(err)
            raise RuntimeError(f"Odoo RPC error: {msg}")
        return body.get("result")

    def execute_kw(
        self,
        model: str,
        method: str,
        args: list | None = None,
        kwargs: dict | None = None,
    ) -> Any:
        if self.uid is None:
            raise RuntimeError("Not authenticated. Call authenticate() first.")
        args = args or []
        kwargs = kwargs or {}
        if self.protocol == "xmlrpc":
            return self._xml_models.execute_kw(
                self.db, self.uid, self.password, model, method, args, kwargs
            )
        return self._jsonrpc(
            "object",
            "execute_kw",
            [self.db, self.uid, self.password, model, method, args, kwargs],
        )

    def search(
        self,
        model: str,
        domain: list,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[int]:
        kwargs: dict[str, Any] = {}
        if limit is not None:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
        return self.execute_kw(model, "search", [domain], kwargs)

    def read(
        self,
        model: str,
        ids: list[int],
        fields: list[str],
        context: dict | None = None,
    ) -> list[dict]:
        kwargs = {"context": context} if context else {}
        return self.execute_kw(model, "read", [ids, fields], kwargs)

    def create(self, model: str, vals: dict, context: dict | None = None) -> int:
        kwargs = {"context": context} if context else {}
        return self.execute_kw(model, "create", [vals], kwargs)

    def write(
        self,
        model: str,
        ids: list[int],
        vals: dict,
        context: dict | None = None,
    ) -> bool:
        kwargs = {"context": context} if context else {}
        return self.execute_kw(model, "write", [ids, vals], kwargs)

    def unlink(self, model: str, ids: list[int]) -> bool:
        return self.execute_kw(model, "unlink", [ids])

    def fields_get(self, model: str, fields: list[str] | None = None) -> dict:
        return self.execute_kw(model, "fields_get", [fields or []], {})


class CapSingleEmployeeMultiCompanyRPCTest:
    """End-to-end cap_single_employee_for_multi_company workflow test via RPC."""

    def __init__(self, client: OdooRPCClient):
        self.client = client
        self.passed = 0
        self.failed = 0
        self._cleanup_ids: dict[str, list[int]] = {
            MODEL_HR_LEAVE: [],
            MODEL_HR_LEAVE_ALLOCATION: [],
            MODEL_HR_EMPLOYEE: [],
            MODEL_RES_USERS: [],
            MODEL_HR_LEAVE_TYPE: [],
            MODEL_RES_COMPANY: [],
        }

    def _ok(self, label: str, condition: bool, detail: str = "") -> bool:
        status = "PASS" if condition else "FAIL"
        msg = f"[{status}] {label}"
        if detail:
            msg += f" -> {detail}"
        print(msg)
        if condition:
            self.passed += 1
        else:
            self.failed += 1
        return condition

    def _m2o_id(self, value: Any) -> int | None:
        if not value:
            return None
        return value[0] if isinstance(value, (list, tuple)) else value

    def _ctx(self, company_id: int, **extra) -> dict:
        ctx = {"allowed_company_ids": [company_id], "default_company_id": company_id}
        ctx.update(extra)
        return ctx

    def _track(self, model: str, record_id: int) -> None:
        if model in self._cleanup_ids:
            self._cleanup_ids[model].append(record_id)

    def _expect_rpc_error(self, label: str, fn) -> bool:
        try:
            fn()
        except RuntimeError as exc:
            return self._ok(label, True, str(exc)[:200])
        return self._ok(label, False, "expected ValidationError but RPC call succeeded")

    def _module_installed(self) -> bool:
        module_ids = self.client.search(
            "ir.module.module",
            [("name", "=", MODULE_NAME), ("state", "=", "installed")],
        )
        return bool(module_ids)

    def _selection_keys(self, model: str, field_name: str) -> set[str]:
        fields = self.client.fields_get(model, [field_name])
        selection = fields.get(field_name, {}).get("selection") or []
        return {key for key, _label in selection}

    def _get_or_create_company(self, name: str) -> int:
        existing = self.client.search(MODEL_RES_COMPANY, [("name", "=", name)], limit=1)
        if existing:
            return existing[0]
        company_id = self.client.create(MODEL_RES_COMPANY, {"name": name})
        self._track(MODEL_RES_COMPANY, company_id)
        return company_id

    def _create_leave_type(self, name: str, company_id: int) -> int:
        leave_type_id = self.client.create(
            MODEL_HR_LEAVE_TYPE,
            {
                "name": name,
                "company_id": company_id,
                "requires_allocation": "no",
                "employee_requests": "yes",
            },
            context=self._ctx(company_id),
        )
        self._track(MODEL_HR_LEAVE_TYPE, leave_type_id)
        return leave_type_id

    def _create_employee(self, name: str, company_id: int, user_id: int | None = None) -> int:
        vals: dict[str, Any] = {"name": name, "company_id": company_id}
        if user_id:
            vals["user_id"] = user_id
        employee_id = self.client.create(
            MODEL_HR_EMPLOYEE,
            vals,
            context=self._ctx(company_id),
        )
        self._track(MODEL_HR_EMPLOYEE, employee_id)
        return employee_id

    def _create_test_user(self, login: str) -> int:
        existing = self.client.search(MODEL_RES_USERS, [("login", "=", login)], limit=1)
        if existing:
            return existing[0]
        user_id = self.client.create(
            MODEL_RES_USERS,
            {
                "name": "CAP Multi-Company RPC Tester",
                "login": login,
                "email": f"{login}@example.com",
                "groups_id": [(CMD_SET, 0, [])],
            },
        )
        self._track(MODEL_RES_USERS, user_id)
        return user_id

    def _leave_vals(
        self,
        employee_id: int,
        leave_type_id: int,
        company_id: int,
    ) -> dict:
        today = str(date.today())
        return {
            FIELD_LEAVE_EMPLOYEE: employee_id,
            FIELD_LEAVE_HOLIDAY_STATUS: leave_type_id,
            "request_date_from": today,
            "request_date_to": today,
            "date_from": f"{today} 08:00:00",
            "date_to": f"{today} 17:00:00",
        }

    def _allocation_vals(
        self,
        leave_type_id: int,
        company_id: int,
        *,
        holiday_type: str = "employee",
        employee_id: int | None = None,
        mode_company_id: int | None = None,
    ) -> dict:
        vals: dict[str, Any] = {
            "name": "CAP RPC Allocation",
            FIELD_ALLOC_HOLIDAY_TYPE: holiday_type,
            FIELD_ALLOC_HOLIDAY_STATUS: leave_type_id,
            FIELD_ALLOC_NUMBER_OF_DAYS: 1.0,
        }
        if holiday_type == "employee" and employee_id:
            vals[FIELD_ALLOC_EMPLOYEE] = employee_id
        if holiday_type == "company" and mode_company_id:
            vals[FIELD_ALLOC_MODE_COMPANY] = mode_company_id
        return vals

    def _rule_is_deactivated(self, xml_id: str) -> bool:
        module, name = xml_id.split(".", 1)
        data_ids = self.client.search(
            "ir.model.data",
            [("module", "=", module), ("name", "=", name)],
            limit=1,
        )
        if not data_ids:
            return False
        data = self.client.read("ir.model.data", data_ids, ["res_id", "model"])[0]
        if data.get("model") != MODEL_IR_RULE or not data.get("res_id"):
            return False
        rule = self.client.read(MODEL_IR_RULE, [data["res_id"]], ["active"])[0]
        return rule.get("active") is False

    def _test_record_rules(self) -> None:
        for xml_id in RULE_XML_IDS:
            self._ok(
                f"ir.rule {xml_id!r} deactivated",
                self._rule_is_deactivated(xml_id),
            )

    def _test_holiday_type_selections(self) -> None:
        alloc_keys = self._selection_keys(MODEL_HR_LEAVE_ALLOCATION, FIELD_ALLOC_HOLIDAY_TYPE)
        self._ok(
            f"{MODEL_HR_LEAVE_ALLOCATION}.{FIELD_ALLOC_HOLIDAY_TYPE} limited selection",
            alloc_keys == EXPECTED_HOLIDAY_TYPE_KEYS,
            f"got {sorted(alloc_keys)}",
        )

        wizard_keys = self._selection_keys(MODEL_ALLOC_MULTI_WIZARD, FIELD_WIZARD_ALLOCATION_MODE)
        self._ok(
            f"{MODEL_ALLOC_MULTI_WIZARD}.{FIELD_WIZARD_ALLOCATION_MODE} limited selection",
            wizard_keys == EXPECTED_HOLIDAY_TYPE_KEYS,
            f"got {sorted(wizard_keys)}",
        )

    def _test_hr_leave_constraints(
        self,
        company_a_id: int,
        company_b_id: int,
        employee_a_id: int,
        leave_type_a_id: int,
        leave_type_b_id: int,
    ) -> None:
        self._expect_rpc_error(
            f"{MODEL_HR_LEAVE} blocks mismatched {FIELD_LEAVE_HOLIDAY_STATUS} company",
            lambda: self.client.create(
                MODEL_HR_LEAVE,
                self._leave_vals(employee_a_id, leave_type_b_id, company_a_id),
                context=self._ctx(company_a_id),
            ),
        )

        leave_id = self.client.create(
            MODEL_HR_LEAVE,
            self._leave_vals(employee_a_id, leave_type_a_id, company_a_id),
            context=self._ctx(company_a_id),
        )
        self._track(MODEL_HR_LEAVE, leave_id)
        leave_data = self.client.read(
            MODEL_HR_LEAVE,
            [leave_id],
            [FIELD_LEAVE_EMPLOYEE, FIELD_LEAVE_HOLIDAY_STATUS],
            context=self._ctx(company_a_id),
        )[0]
        self._ok(
            f"{MODEL_HR_LEAVE} allows matching employee/leave-type companies",
            self._m2o_id(leave_data[FIELD_LEAVE_EMPLOYEE]) == employee_a_id
            and self._m2o_id(leave_data[FIELD_LEAVE_HOLIDAY_STATUS]) == leave_type_a_id,
            f"leave_id={leave_id}",
        )

        self._expect_rpc_error(
            f"{MODEL_HR_LEAVE} blocks write with mismatched {FIELD_LEAVE_HOLIDAY_STATUS}",
            lambda: self.client.write(
                MODEL_HR_LEAVE,
                [leave_id],
                {FIELD_LEAVE_HOLIDAY_STATUS: leave_type_b_id},
                context=self._ctx(company_a_id),
            ),
        )

    def _test_hr_leave_allocation_constraints(
        self,
        company_a_id: int,
        company_b_id: int,
        employee_a_id: int,
        leave_type_a_id: int,
        leave_type_b_id: int,
    ) -> None:
        self._expect_rpc_error(
            f"{MODEL_HR_LEAVE_ALLOCATION} employee mode blocks company mismatch",
            lambda: self.client.create(
                MODEL_HR_LEAVE_ALLOCATION,
                self._allocation_vals(
                    leave_type_b_id,
                    company_a_id,
                    holiday_type="employee",
                    employee_id=employee_a_id,
                ),
                context=self._ctx(company_a_id),
            ),
        )

        alloc_employee_id = self.client.create(
            MODEL_HR_LEAVE_ALLOCATION,
            self._allocation_vals(
                leave_type_a_id,
                company_a_id,
                holiday_type="employee",
                employee_id=employee_a_id,
            ),
            context=self._ctx(company_a_id),
        )
        self._track(MODEL_HR_LEAVE_ALLOCATION, alloc_employee_id)
        alloc_data = self.client.read(
            MODEL_HR_LEAVE_ALLOCATION,
            [alloc_employee_id],
            [FIELD_ALLOC_HOLIDAY_TYPE, FIELD_ALLOC_EMPLOYEE, FIELD_ALLOC_HOLIDAY_STATUS],
            context=self._ctx(company_a_id),
        )[0]
        self._ok(
            f"{MODEL_HR_LEAVE_ALLOCATION} employee mode allows matching companies",
            alloc_data[FIELD_ALLOC_HOLIDAY_TYPE] == "employee"
            and self._m2o_id(alloc_data[FIELD_ALLOC_EMPLOYEE]) == employee_a_id
            and self._m2o_id(alloc_data[FIELD_ALLOC_HOLIDAY_STATUS]) == leave_type_a_id,
            f"allocation_id={alloc_employee_id}",
        )

        self._expect_rpc_error(
            f"{MODEL_HR_LEAVE_ALLOCATION} company mode blocks leave-type company mismatch",
            lambda: self.client.create(
                MODEL_HR_LEAVE_ALLOCATION,
                self._allocation_vals(
                    leave_type_b_id,
                    company_a_id,
                    holiday_type="company",
                    mode_company_id=company_a_id,
                ),
                context=self._ctx(company_a_id),
            ),
        )

        alloc_company_id = self.client.create(
            MODEL_HR_LEAVE_ALLOCATION,
            self._allocation_vals(
                leave_type_a_id,
                company_a_id,
                holiday_type="company",
                mode_company_id=company_a_id,
            ),
            context=self._ctx(company_a_id),
        )
        self._track(MODEL_HR_LEAVE_ALLOCATION, alloc_company_id)
        company_alloc = self.client.read(
            MODEL_HR_LEAVE_ALLOCATION,
            [alloc_company_id],
            [FIELD_ALLOC_HOLIDAY_TYPE, FIELD_ALLOC_MODE_COMPANY, FIELD_ALLOC_HOLIDAY_STATUS],
            context=self._ctx(company_a_id),
        )[0]
        self._ok(
            f"{MODEL_HR_LEAVE_ALLOCATION} company mode allows matching companies",
            company_alloc[FIELD_ALLOC_HOLIDAY_TYPE] == "company"
            and self._m2o_id(company_alloc[FIELD_ALLOC_MODE_COMPANY]) == company_a_id
            and self._m2o_id(company_alloc[FIELD_ALLOC_HOLIDAY_STATUS]) == leave_type_a_id,
            f"allocation_id={alloc_company_id}",
        )

    def _test_res_users_company_employee(
        self,
        company_a_id: int,
        company_b_id: int,
        user_id: int,
        employee_a_id: int,
        employee_b_id: int,
    ) -> None:
        user_in_a = self.client.read(
            MODEL_RES_USERS,
            [user_id],
            [FIELD_USER_EMPLOYEE],
            context=self._ctx(company_a_id),
        )[0]
        self._ok(
            f"{MODEL_RES_USERS}.{FIELD_USER_EMPLOYEE} matches company A context",
            self._m2o_id(user_in_a[FIELD_USER_EMPLOYEE]) == employee_a_id,
            f"got employee_id={self._m2o_id(user_in_a[FIELD_USER_EMPLOYEE])}",
        )

        user_in_b = self.client.read(
            MODEL_RES_USERS,
            [user_id],
            [FIELD_USER_EMPLOYEE],
            context=self._ctx(company_b_id),
        )[0]
        self._ok(
            f"{MODEL_RES_USERS}.{FIELD_USER_EMPLOYEE} matches company B context",
            self._m2o_id(user_in_b[FIELD_USER_EMPLOYEE]) == employee_b_id,
            f"got employee_id={self._m2o_id(user_in_b[FIELD_USER_EMPLOYEE])}",
        )

    def _cleanup(self) -> None:
        order = [
            MODEL_HR_LEAVE,
            MODEL_HR_LEAVE_ALLOCATION,
            MODEL_HR_EMPLOYEE,
            MODEL_RES_USERS,
            MODEL_HR_LEAVE_TYPE,
            MODEL_RES_COMPANY,
        ]
        for model in order:
            ids = self._cleanup_ids.get(model, [])
            if not ids:
                continue
            try:
                if model == MODEL_HR_LEAVE:
                    for leave_id in ids:
                        state = self.client.read(MODEL_HR_LEAVE, [leave_id], ["state"])[0]["state"]
                        if state not in ("draft", "refuse"):
                            try:
                                self.client.execute_kw(
                                    MODEL_HR_LEAVE,
                                    "action_refuse",
                                    [[leave_id]],
                                    {},
                                )
                            except RuntimeError:
                                pass
                self.client.unlink(model, ids)
                print(f"  Cleaned up {len(ids)} {model} record(s)")
            except RuntimeError as exc:
                print(f"  [WARN] cleanup {model} {ids}: {exc}")
            self._cleanup_ids[model] = []

    def run(self) -> bool:
        print("=" * 80)
        print("CAP Single Employee For Multi Company — RPC Test (Odoo 19)")
        print(f"Module : {MODULE_NAME}")
        print(
            f"Protocol: {self.client.protocol.upper()} | DB: {self.client.db} | URL: {self.client.url}"
        )
        print("=" * 80)

        self._ok(f"Module {MODULE_NAME!r} installed", self._module_installed())

        company_a_id = self._get_or_create_company("CAP RPC Company A")
        company_b_id = self._get_or_create_company("CAP RPC Company B")
        print(f"Companies: A={company_a_id}, B={company_b_id}")

        leave_type_a_id = self._create_leave_type("CAP RPC Leave Type A", company_a_id)
        leave_type_b_id = self._create_leave_type("CAP RPC Leave Type B", company_b_id)

        user_login = "cap_multi_company_rpc_tester"
        user_id = self._create_test_user(user_login)
        employee_a_id = self._create_employee(
            "CAP RPC Employee A", company_a_id, user_id=user_id
        )
        employee_b_id = self._create_employee(
            "CAP RPC Employee B", company_b_id, user_id=user_id
        )

        self._test_record_rules()
        self._test_holiday_type_selections()
        self._test_hr_leave_constraints(
            company_a_id,
            company_b_id,
            employee_a_id,
            leave_type_a_id,
            leave_type_b_id,
        )
        self._test_hr_leave_allocation_constraints(
            company_a_id,
            company_b_id,
            employee_a_id,
            leave_type_a_id,
            leave_type_b_id,
        )
        self._test_res_users_company_employee(
            company_a_id,
            company_b_id,
            user_id,
            employee_a_id,
            employee_b_id,
        )

        print("=" * 80)
        print(f"Result: {self.passed} passed, {self.failed} failed")
        print("=" * 80)

        self._cleanup()
        return self.failed == 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RPC test for cap_single_employee_for_multi_company (Odoo 19)",
    )
    parser.add_argument("--url", default=DEFAULT_URL, help=f"Odoo URL (default: {DEFAULT_URL})")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"Database name (default: {DEFAULT_DB})")
    parser.add_argument("--user", default=DEFAULT_USER, help=f"Username (default: {DEFAULT_USER})")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Password")
    parser.add_argument(
        "--protocol",
        choices=["jsonrpc", "xmlrpc"],
        default=DEFAULT_PROTOCOL,
        help=f"RPC protocol (default: {DEFAULT_PROTOCOL})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = OdooRPCClient(args.url, args.db, args.user, args.password, args.protocol)
    try:
        uid = client.authenticate()
        print(f"Authenticated uid={uid}")
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    success = CapSingleEmployeeMultiCompanyRPCTest(client).run()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
