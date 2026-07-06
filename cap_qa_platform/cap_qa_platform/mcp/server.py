"""MCP server exposing cap_qa_platform tools to AI assistants."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root on path when run as script
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _run_mcp() -> int:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print(
            "ERROR: Install MCP SDK: pip install mcp",
            file=sys.stderr,
        )
        return 1

    from cap_qa_platform.backend.runner import RunConfig, run_scenario
    from cap_qa_platform.catalog import ALL_SCENARIO_IDS, list_scenarios
    from cap_qa_platform.nlp.prompt_cli import parse_natural_command, scaffold_scenario
    from cap_qa_platform.ui.runner import run_ui_smoke
    from cap_qa_platform.staging import load_staging_env

    load_staging_env()
    mcp = FastMCP("cap-qa-platform")

    @mcp.tool()
    def list_scenarios_tool() -> str:
        """List all QA scenarios (backend + UI layers)."""
        return json.dumps(list_scenarios(), indent=2)

    @mcp.tool()
    def run_backend_smoke(
        scenario: str,
        url: str,
        db: str,
        user: str,
        password: str,
        role: str = "President",
        protocol: str = "jsonrpc",
    ) -> str:
        """Run one backend scenario for one role (smoke)."""
        cfg = RunConfig(
            url=url,
            db=db,
            user=user,
            password=password,
            protocol=protocol,
            roles=[role],
        )
        return json.dumps(run_scenario(cfg, scenario), indent=2, default=str)

    @mcp.tool()
    def run_backend_matrix(
        scenario: str,
        url: str,
        db: str,
        user: str,
        password: str,
        roles_from: str = "db",
        protocol: str = "jsonrpc",
    ) -> str:
        """Run backend scenario for all roles from DB."""
        cfg = RunConfig(
            url=url,
            db=db,
            user=user,
            password=password,
            protocol=protocol,
            roles_from=roles_from,
        )
        return json.dumps(run_scenario(cfg, scenario), indent=2, default=str)

    @mcp.tool()
    def run_ui_smoke_tool(scenario: str, role: str = "President") -> str:
        """Run UI+backend hybrid smoke for a scenario."""
        import os

        os.environ.setdefault("CAP_QA_UI_USER", os.environ.get("ODOO_USER", "admin"))
        code = run_ui_smoke(scenario, role=role)
        return json.dumps({"exit_code": code, "scenario": scenario, "role": role})

    @mcp.tool()
    def ask_qa(prompt: str, url: str, db: str, user: str, password: str) -> str:
        """Parse natural language QA request and execute."""
        parsed = parse_natural_command(prompt)
        action = parsed.get("action", "smoke")
        scenario = parsed.get("scenario", "so_cancel_old_customer")
        role = parsed.get("role", "President")

        if action == "list":
            return json.dumps(list_scenarios(), indent=2)
        if action == "scaffold":
            sid = parsed.get("new_scenario_id", "new_feature")
            return json.dumps(
                scaffold_scenario(sid, parsed.get("brief", prompt)),
                indent=2,
            )
        if action == "ui":
            return run_ui_smoke_tool(scenario, role)
        if action == "matrix":
            return run_backend_matrix(scenario, url, db, user, password)
        return run_backend_smoke(scenario, url, db, user, password, role)

    @mcp.tool()
    def scaffold_scenario_tool(scenario_id: str, brief: str, modules_json: str = "[]") -> str:
        """Scaffold new scenario files from a brief."""
        modules = json.loads(modules_json)
        return json.dumps(scaffold_scenario(scenario_id, brief, modules), indent=2)

    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(_run_mcp())
