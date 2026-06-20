#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone RPC test for access_rights_management roles (Odoo 19).

Fully **dynamic**: models, groups, ``ir.model.access``, and ``ir.rule`` are loaded
live from the database. When a new model or access line is installed, the next run
picks it up automatically — no hardcoded model list required.

Uses ONE admin login + ONE test user. Each role is assigned individually and tested
for read / write / create / unlink (ACL + CRUD + record rules on existing data).

Outputs a **break report** showing exactly which role × model × operation fails.

Run::

 python3 scripts/test_access_rights_roles_rpc.py \\
 --url http://localhost:8069 --db odoo --user admin --password admin

 python3 scripts/test_access_rights_roles_rpc.py --roles-from db \\
 --report-file /tmp/access_breaks.json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import xmlrpc.client
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_URL = "http://localhost:8069"
DEFAULT_DB = "odoo"
DEFAULT_USER = "admin"
DEFAULT_PASSWORD = "admin"
DEFAULT_PROTOCOL = "jsonrpc"
TEST_USER_LOGIN = "access_rights_role_tester"
TEST_USER_NAME = "Access Rights RPC Tester"
TEST_USER_PASSWORD = "access…test"

MODULE_NAME = "access_rights_management"
ROLES_DATA_XML = Path(__file__).resolve().parent.parent / "data" / "roles_data.xml"

# Odoo x2many commands
CMD_CREATE = 0
CMD_LINK = 4
CMD_UNLINK = 3
CMD_CLEAR = 5
CMD_SET = 6

# Legacy static list (--smoke-mode fixed only).
SMOKE_MODELS_FIXED = [
    "crm.lead",
    "sale.order",
    "res.partner",
    "account.move",
    "project.project",
    "project.task",
    "helpdesk.ticket",
    "purchase.order",
    "hr.expense",
    "hr.applicant",
    "account.analytic.line",
    "gamification.goal",
    "survey.survey",
    "hr.employee",
    "approval.request",
]

PERM_FIELDS = ("perm_read", "perm_write", "perm_create", "perm_unlink")
PERM_TO_OP = {
    "perm_read": "read",
    "perm_write": "write",
    "perm_create": "create",
    "perm_unlink": "unlink",
}

# RPC errors that mean "model exists but user cannot read" vs "not searchable".
_ACCESS_DENIED_MARKERS = (
    "access error",
    "access denied",
    "access rights",
    "not allowed to access",
    "odoo.exceptions.accesserror",
