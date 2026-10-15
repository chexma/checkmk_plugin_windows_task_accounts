# Windows Task Accounts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Checkmk plugin `windows_task_accounts`: one service per Windows host that shows which scheduled tasks run under a user or service account and alerts on accounts that are not allowed, plus an inventory table, with the agent plugin deployed through the agent bakery.

**Architecture:** A PowerShell agent plugin reports every scheduled task with its principal (user or group), the principal's SID, logon type, run level and state, unfiltered. All evaluation (account kinds, ignored task folders, logon type filter, allow list, unwanted accounts, changes since the discovery) happens in one check plugin on the server, so a rule change never requires baking. The same section feeds an inventory table with a view for cross-host searches. Structure, naming and code mirror the plugin `windows_service_accounts` (copy in `temp/reference/`).

**Tech Stack:** Checkmk 2.5 (`cmk.agent_based.v2`, `cmk.rulesets.v1`, `cmk.graphing.v1`, `cmk.bakery.v2_unstable`, `cmk.inventory_ui.v1_unstable`), Python 3.13, pytest, Windows PowerShell 5.1.

**Spec:** `docs/superpowers/specs/2026-10-15-task-accounts-design.md`. Read it before starting.

## Global Constraints

- Target: Checkmk 2.5 (devcontainer: `ultimate` 2.5.0p15). Windows hosts only (Windows 8 / Server 2012 or later).
- All plugin files live in `plugins/windows_task_accounts/` (bind-mounted to `~/local/lib/python3/cmk_addons/plugins/windows_task_accounts/`). No `__init__.py` files: plugin families are namespace packages. Delete `plugins/windows_task_accounts/.gitkeep` in Task 1.
- All internal names are `windows_task_accounts` (section, check plugin, rulesets, bakery plugin, inventory path `software > os > windows_task_accounts`, graph, perfometer, man page). Metrics: `task_account_tasks`, `task_account_accounts`. View: `invtaskaccounts`. Service and rule titles: `Windows Task Accounts`.
- Section header is exactly `<<<windows_task_accounts:sep(124)>>>`. The agent plugin has no configuration file and reports all tasks unfiltered. Keep it ASCII only.
- The bakery (API v2) takes the plugin source from the family's `agents/` directory.
- Regexes are full-match and case-insensitive. Account patterns are tried against the account name and the SID; `$HOSTNAME$` is replaced by the escaped computer name. Task patterns are matched against the task identity `\<path>\<name>`.
- Without a rule the service is WARN for every reported account (`check_default_parameters={"not_allowed_state": 1}`).
- Test data uses fictional names only (CONTOSO, SRV-APP01, round SIDs such as `S-1-5-21-1000-2000-3000`). This also holds for files in `temp/` and for hosts in the dev site.
- `cmk.bakery.v2_unstable` and `cmk.inventory_ui.v1_unstable` are unstable APIs (stable in 3.0.0). Use them as shown.
- Formatting: black and isort with line length 100, flake8 clean. In Claude Code a hook formats every edited Python file; otherwise run `black plugins/ tests/ && isort plugins/ tests/` before each commit.
- Do not build an MKP and do not create the `package` manifest: only on explicit request. Never run `mkp release` or `mkp disable`. Never create symlinks in `~/local`.
- `List` form specs take no `prefill` argument.
- The code blocks in this plan were run against Checkmk 2.5.0p15: all 120 tests pass and flake8 is clean with the code as written. If a test fails, look for a transcription error before changing the code or the test.

## Decisions beyond the spec

Task 4 records these in the spec under "Amendments from the implementation".

1. Logon types are the names `Get-ScheduledTask` reports (`Password`, `S4U`, `Interactive`, `InteractiveOrPassword`, `ServiceAccount`, `Group`, `None`), not the task XML names (`InteractiveToken`). The rule option `logon_types` stores them in lower case; the form prefills `password` (the usual use: alert only on stored passwords), absent option = all.
2. A baseline entry of a task without user carries `"group": True`, so a domain group in the baseline is classified as `group`, as in the current data.
3. Kind `group` by SID: `S-1-5-32-*`, `S-1-2-*`, `S-1-1-0`, `S-1-5-4`, `S-1-5-6`, `S-1-5-11`; by name: `BUILTIN\*`, `Users`, `Administrators`, `Everyone`, `INTERACTIVE`, `Authenticated Users`, `NT AUTHORITY\INTERACTIVE` / `Authenticated Users` / `SERVICE`.
4. Ignored paths are removed from the baseline before the comparison, so a removed or changed task under `\Microsoft\` is never reported unless the rule evaluates that folder.
5. The inventory applies the default built-in kinds and the default ignored path unless `all_tasks` is set.
6. An invalid ignored-path pattern yields an UNKNOWN result like any other invalid pattern.

## Review Focus

Inputs the spec implies but does not spell out, each pinned by a test:

1. A task configured with only a domain group (`GroupId` = `CONTOSO\App Users`, domain SID): it must be `group`, not `domain`, in the check and in the baseline. Tests `test_classify_task_without_user_as_group`, `test_kinds_of_the_sample_tasks`, `test_task_changed_from_domain_group_to_user_is_a_change` (Task 1).
2. A task in the root folder (`TaskPath` = `\`) or a path without trailing backslash: identity `\Root`, not `\\Root`. Test `test_identity_in_the_root_folder_and_without_trailing_backslash` (Task 1).
3. A Microsoft task under a user account changes or disappears: no finding while `\Microsoft\` is ignored, a finding once the rule evaluates it. Test `test_changes_in_ignored_tasks_are_not_reported` (Task 1).
4. The SID of an account cannot be translated on one agent run but could before: no `changed` finding, and SID patterns still match via the baseline. Tests `test_unresolved_sid_is_not_a_change`, `test_sid_pattern_uses_the_baseline_sid_if_the_translation_failed` (Task 1).
5. Agent output with short lines, empty fields, unknown line types or a task without a name: the parser keeps what is usable. Test `test_parse_empty_and_missing_fields` (Task 1).

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `plugins/windows_task_accounts/agent_based/windows_task_accounts.py` | Section parser, classification, discovery, check, inventory plugin | 1 |
| `plugins/windows_task_accounts/rulesets/windows_task_accounts.py` | Check parameters rule | 2 |
| `plugins/windows_task_accounts/rulesets/inventory.py` | HW/SW inventory rule (`all_tasks`) | 2 |
| `plugins/windows_task_accounts/graphing/windows_task_accounts.py` | Metrics, graph, perfometer | 2 |
| `plugins/windows_task_accounts/inventory_ui/windows_task_accounts.py` | Titles and view of the inventory table | 2 |
| `plugins/windows_task_accounts/agents/windows_task_accounts.ps1` | Agent plugin | 3 |
| `plugins/windows_task_accounts/rulesets/agent_config.py` | Bakery rule | 3 |
| `plugins/windows_task_accounts/bakery/windows_task_accounts.py` | Bakery plugin | 3 |
| `plugins/windows_task_accounts/checkman/windows_task_accounts` | Man page | 4 |
| `tests/test_windows_task_accounts.py` | All pytest tests (one section per task) | 1-4 |
| `README.md`, `Changelog.md` | Plugin documentation (replace the template README) | 4 |

---

### Task 1: Section, check and inventory plugin

**Files:**
- Create: `plugins/windows_task_accounts/agent_based/windows_task_accounts.py`
- Create: `tests/test_windows_task_accounts.py`
- Delete: `plugins/windows_task_accounts/.gitkeep`, `tests/.gitkeep`

**Interfaces:**
- Consumes: nothing.
- Produces (used by Tasks 2-4 and their tests): module `cmk_addons.plugins.windows_task_accounts.agent_based.windows_task_accounts` with `WinTask`, `Section`, `parse_windows_task_accounts(StringTable) -> Section | None`, `classify(account, sid, computer, machine_sid, is_group=False) -> str`, `kind_of_task(WinTask, Section) -> str`, `discover_windows_task_accounts`, `check_windows_task_accounts(params, section)`, `inventory_windows_task_accounts(params, section)`, constants `DEFAULT_BUILTIN_KINDS`, `DEFAULT_IGNORED_PATHS`, `LOGON_TYPES`, `KIND_TITLES`, plugin objects `check_plugin_windows_task_accounts` (ruleset `windows_task_accounts`), `inventory_plugin_windows_task_accounts` (ruleset `windows_task_accounts_inventory`, default `{"all_tasks": False}`). Metrics `task_account_tasks`, `task_account_accounts`. Inventory row: path `["software", "os", "windows_task_accounts"]`, key `task`, columns `account`, `kind`, `logon_type`, `run_level`, status `state`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_windows_task_accounts.py`:

```python
# Copyright (C) 2026 Andre Eckstein - License: GNU General Public License v3
# This file is part of the Checkmk plugin windows_task_accounts. It is subject to the
# terms and conditions defined in the file LICENSE in the root of the repository.
# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the plugin family windows_task_accounts. All names are fictional."""

import pytest
from cmk.agent_based.v2 import Metric, Result, Service, State, TableRow
from cmk_addons.plugins.windows_task_accounts.agent_based import windows_task_accounts as ta

MACHINE_SID = "S-1-5-21-1000-2000-3000"
DOMAIN_SID = "S-1-5-21-4000-5000-6000"

# What the agent plugin prints, without the section header. Fields of a task line:
# path|name|user|user SID|group|group SID|logon type|run level|state
AGENT_OUTPUT = f"""\
computer|SRV-APP01|{MACHINE_SID}
task|\\Microsoft\\Windows\\Defrag\\|ScheduledDefrag|SYSTEM|S-1-5-18|||ServiceAccount|Highest|Ready
task|\\Microsoft\\Windows\\Shell\\|CreateObjectTask|||Users|S-1-5-32-545|Group|Limited|Ready
task|\\Microsoft\\Office\\|Telemetry|CONTOSO\\jdoe|{DOMAIN_SID}-1500|||Interactive|Limited|Ready
task|\\|Updater|NT-AUTORITÄT\\SYSTEM|S-1-5-18|||ServiceAccount|Highest|Ready
task|\\|Cleanup|LOCAL SERVICE|S-1-5-19|||ServiceAccount|Limited|Ready
task|\\Backup\\|Nightly|CONTOSO\\svc_backup|{DOMAIN_SID}-1105|||Password|Highest|Ready
task|\\Backup\\|Weekly|CONTOSO\\svc_backup|{DOMAIN_SID}-1105|||Password|Limited|Disabled
task|\\|LocalJob|.\\batch|{MACHINE_SID}-1001|||Password|Limited|Ready
task|\\Reports\\|Export|CONTOSO\\gmsa_rep$|{DOMAIN_SID}-1106|||Password|Limited|Ready
task|\\|UserLogon|CONTOSO\\old_admin||||Interactive|Limited|Ready
task|\\|Sync|svc_sync@contoso.example|{DOMAIN_SID}-1107|||S4U|Limited|Running
task|\\|AnyUser|||INTERACTIVE|S-1-5-4|Group|Limited|Ready
task|\\|AppUsers|||CONTOSO\\App Users|{DOMAIN_SID}-2000|Group|Limited|Ready
task|\\|Orphan|||||None|Limited|Ready
"""


def _table(text: str) -> list[list[str]]:
    """Agent output as the string table Checkmk passes to the parse function."""
    return [line.split("|") for line in text.splitlines()]


STRING_TABLE = _table(AGENT_OUTPUT)


@pytest.fixture(name="section")
def _section() -> ta.Section:
    section = ta.parse_windows_task_accounts(STRING_TABLE)
    assert section is not None
    return section


def _parse(*lines: str) -> ta.Section:
    """A section of the computer SRV-APP01 with these task lines (without "task|")."""
    section = ta.parse_windows_task_accounts(
        _table(f"computer|SRV-APP01|{MACHINE_SID}\n" + "\n".join(f"task|{x}" for x in lines))
    )
    assert section is not None
    return section


def _results(params, section) -> list[Result]:
    return [r for r in ta.check_windows_task_accounts(params, section) if isinstance(r, Result)]


def _discovered(section) -> dict:
    (service,) = ta.discover_windows_task_accounts(section)
    return dict(service.parameters)


def _notices(params, section) -> dict[str, State]:
    """Summary text -> state of all results that are not OK."""
    return {r.summary: r.state for r in _results(params, section) if r.state is not State.OK}


# --- parser -----------------------------------------------------------------


def test_parse_empty_section() -> None:
    assert ta.parse_windows_task_accounts([]) is None


def test_parse_tasks(section) -> None:
    assert section.computer == "SRV-APP01"
    assert section.machine_sid == MACHINE_SID
    assert section.error is None
    assert len(section.tasks) == 14
    task = section.tasks[5]
    assert task == ta.WinTask(
        path="\\Backup\\",
        name="Nightly",
        user="CONTOSO\\svc_backup",
        user_sid=DOMAIN_SID + "-1105",
        group="",
        group_sid="",
        logon_type="Password",
        run_level="Highest",
        state="Ready",
    )
    assert task.identity == "\\Backup\\Nightly"
    assert task.account == "CONTOSO\\svc_backup"
    assert task.sid == DOMAIN_SID + "-1105"
    assert not task.is_group


def test_parse_group_task(section) -> None:
    task = section.tasks[1]
    assert task.identity == "\\Microsoft\\Windows\\Shell\\CreateObjectTask"
    assert task.account == "Users"
    assert task.sid == "S-1-5-32-545"
    assert task.is_group


def test_identity_in_the_root_folder_and_without_trailing_backslash() -> None:
    section = _parse("\\|Root|SYSTEM|S-1-5-18", "\\Backup|NoSlash|SYSTEM|S-1-5-18")
    assert [t.identity for t in section.tasks] == ["\\Root", "\\Backup\\NoSlash"]


def test_parse_empty_and_missing_fields() -> None:
    section = ta.parse_windows_task_accounts(
        [
            ["computer", "SRV-APP01"],
            ["task", "\\", "Short", "CONTOSO\\x"],
            ["task", "\\", ""],
            ["task", "\\"],
            ["task"],
            ["garbage", "x"],
        ]
    )
    assert section is not None
    assert section.machine_sid == ""
    assert section.tasks == [ta.WinTask("\\", "Short", "CONTOSO\\x", "", "", "", "", "", "")]


def test_parse_error_line() -> None:
    section = ta.parse_windows_task_accounts(
        [["computer", "SRV-APP01", MACHINE_SID], ["error", "Access denied"]]
    )
    assert section is not None
    assert section.error == "Access denied"
    assert section.tasks == []


# --- classification ---------------------------------------------------------


@pytest.mark.parametrize(
    "account, sid, kind",
    [
        ("SYSTEM", "S-1-5-18", "local_system"),
        ("NT-AUTORITÄT\\LOKALER DIENST", "S-1-5-19", "local_service"),
        ("NT-AUTORITÄT\\NETZWERKDIENST", "S-1-5-20", "network_service"),
        ("NT SERVICE\\MSSQL$X", "S-1-5-80-1-2-3-4-5", "virtual"),
        ("VORDEFINIERT\\Benutzer", "S-1-5-32-545", "group"),
        ("Jeder", "S-1-1-0", "group"),
        ("INTERACTIVE", "S-1-5-4", "group"),
        ("SERVICE", "S-1-5-6", "group"),
        ("Authenticated Users", "S-1-5-11", "group"),
        ("LOCAL", "S-1-2-0", "group"),
        (".\\batch", MACHINE_SID + "-1001", "local_user"),
        ("CONTOSO\\gmsa_rep$", DOMAIN_SID + "-1106", "managed"),
        ("CONTOSO\\svc_backup", DOMAIN_SID + "-1105", "domain"),
        ("svc_backup", DOMAIN_SID + "-1105", "domain"),
        ("IIS APPPOOL\\DefaultAppPool", "S-1-5-82-1-2-3-4-5", "unknown"),
    ],
)
def test_classify_by_sid(account: str, sid: str, kind: str) -> None:
    assert ta.classify(account, sid, "SRV-APP01", MACHINE_SID) == kind


@pytest.mark.parametrize(
    "account, kind",
    [
        ("SYSTEM", "local_system"),
        ("LocalSystem", "local_system"),
        ("nt authority\\system", "local_system"),
        ("LOCAL SERVICE", "local_service"),
        ("NT AUTHORITY\\LocalService", "local_service"),
        ("NETWORK SERVICE", "network_service"),
        ("NT AUTHORITY\\Network Service", "network_service"),
        ("NT Service\\MSSQL$X", "virtual"),
        ("Users", "group"),
        ("BUILTIN\\Administrators", "group"),
        ("INTERACTIVE", "group"),
        ("NT AUTHORITY\\Authenticated Users", "group"),
        ("Everyone", "group"),
        (".\\batch", "local_user"),
        ("srv-app01\\batch", "local_user"),
        ("CONTOSO\\gmsa_rep$", "managed"),
        ("CONTOSO\\svc_backup", "domain"),
        ("svc_backup@contoso.example", "domain"),
        ("svc_backup", "unknown"),
        ("", "no_account"),
    ],
)
def test_classify_by_name(account: str, kind: str) -> None:
    assert ta.classify(account, "", "SRV-APP01", MACHINE_SID) == kind


def test_classify_task_without_user_as_group() -> None:
    # A domain group has a domain SID, but the task runs for its members.
    assert ta.classify("CONTOSO\\App Users", DOMAIN_SID + "-2000", "SRV-APP01", "", True) == (
        "group"
    )


def test_classify_without_machine_sid_uses_the_name_for_local_users() -> None:
    assert ta.classify(".\\batch", MACHINE_SID + "-1001", "SRV-APP01", "") == "local_user"
    assert ta.classify("CONTOSO\\svc_backup", DOMAIN_SID + "-1105", "SRV-APP01", "") == "domain"


def test_classify_machine_sid_is_not_a_string_prefix() -> None:
    # S-1-5-21-1000-2000-30001-500 belongs to another machine or domain
    assert ta.classify("CONTOSO\\x", MACHINE_SID + "1-500", "SRV-APP01", MACHINE_SID) == "domain"


def test_kinds_of_the_sample_tasks(section) -> None:
    assert {t.name: ta.kind_of_task(t, section) for t in section.tasks} == {
        "ScheduledDefrag": "local_system",
        "CreateObjectTask": "group",
        "Telemetry": "domain",
        "Updater": "local_system",
        "Cleanup": "local_service",
        "Nightly": "domain",
        "Weekly": "domain",
        "LocalJob": "local_user",
        "Export": "managed",
        "UserLogon": "domain",
        "Sync": "domain",
        "AnyUser": "group",
        "AppUsers": "group",
        "Orphan": "no_account",
    }


# --- discovery --------------------------------------------------------------


def test_discovery_stores_every_task_with_a_principal(section) -> None:
    discovered = _discovered(section)["discovered_tasks"]
    assert len(discovered) == 13
    assert "\\Orphan" not in discovered
    assert discovered["\\Microsoft\\Windows\\Defrag\\ScheduledDefrag"] == {
        "account": "SYSTEM",
        "sid": "S-1-5-18",
    }
    assert discovered["\\Backup\\Nightly"] == {
        "account": "CONTOSO\\svc_backup",
        "sid": DOMAIN_SID + "-1105",
    }
    assert discovered["\\UserLogon"] == {"account": "CONTOSO\\old_admin", "sid": ""}
    assert discovered["\\AppUsers"] == {
        "account": "CONTOSO\\App Users",
        "sid": DOMAIN_SID + "-2000",
        "group": True,
    }


def test_discovery_on_error_has_no_baseline() -> None:
    section = ta.parse_windows_task_accounts([["computer", "SRV-APP01", ""], ["error", "boom"]])
    assert list(ta.discover_windows_task_accounts(section)) == [Service()]


def test_no_discovery_without_tasks_and_error() -> None:
    section = ta.parse_windows_task_accounts([["computer", "SRV-APP01", MACHINE_SID]])
    assert not list(ta.discover_windows_task_accounts(section))


# --- check: summary, metrics, details ---------------------------------------


def test_check_without_rule_is_ok_and_counts(section) -> None:
    results = list(ta.check_windows_task_accounts({}, section))
    assert results[0] == Result(state=State.OK, summary="6 tasks under 5 accounts")
    assert Metric("task_account_tasks", 6) in results
    assert Metric("task_account_accounts", 5) in results
    assert all(r.state is State.OK for r in results if isinstance(r, Result))


def test_service_name() -> None:
    assert ta.check_plugin_windows_task_accounts.service_name == "Windows Task Accounts"


def test_default_is_warn_for_accounts_that_are_not_allowed(section) -> None:
    # Checkmk passes these parameters if no rule matches.
    defaults = ta.check_plugin_windows_task_accounts.check_default_parameters
    assert defaults == {"not_allowed_state": 1}
    assert set(_notices(defaults, section).values()) == {State.WARN}
    assert len(_notices(defaults, section)) == 5
    # A rule can switch it off again.
    assert _notices({**defaults, "not_allowed_state": 0}, section) == {}


def test_check_details_have_one_line_per_task(section) -> None:
    details = [r.details for r in _results({}, section)]
    assert (
        "\\Backup\\Nightly: CONTOSO\\svc_backup (domain account), Password, Highest, Ready\n"
        "\\Backup\\Weekly: CONTOSO\\svc_backup (domain account), Password, Limited, Disabled"
    ) in details
    assert "\\Sync: svc_sync@contoso.example (domain account), S4U, Limited, Running" in details


def test_check_singular() -> None:
    section = _parse(f"\\|A|CONTOSO\\svc_a|{DOMAIN_SID}-1|||Password|Limited|Ready")
    assert _results({}, section)[0].summary == "1 task under 1 account"


def test_check_same_account_in_two_spellings_is_counted_once() -> None:
    section = _parse(
        f"\\|A|CONTOSO\\svc_a|{DOMAIN_SID}-1|||Password|Limited|Ready",
        f"\\|B|svc_a|{DOMAIN_SID}-1|||Password|Limited|Ready",
    )
    assert _results({}, section)[0].summary == "2 tasks under 1 account"


def test_builtin_kinds(section) -> None:
    params = {"builtin_kinds": ["local_system", "domain", "managed", "local_user"]}
    # Cleanup (Local Service), AnyUser, AppUsers (groups), Orphan (no account)
    assert _results(params, section)[0].summary == "4 tasks under 4 accounts"


def test_ignore_disabled(section) -> None:
    assert _results({"ignore_disabled": True}, section)[0].summary == "5 tasks under 5 accounts"


def test_query_error_state() -> None:
    section = ta.parse_windows_task_accounts([["computer", "SRV-APP01", ""], ["error", "boom"]])
    assert list(ta.check_windows_task_accounts({}, section)) == [
        Result(state=State.UNKNOWN, summary="Agent plugin reported an error: boom")
    ]
    assert _results({"query_error_state": 2}, section)[0].state is State.CRIT


# --- check: ignored paths and logon types -----------------------------------


def test_microsoft_tasks_are_ignored_by_default(section) -> None:
    notices = _notices({"not_allowed_state": 1}, section)
    assert not [n for n in notices if "jdoe" in n]


def test_ignored_paths_empty_list_evaluates_microsoft_tasks(section) -> None:
    params = {"not_allowed_state": 1, "ignored_paths": []}
    assert _results(params, section)[0].summary == "7 tasks under 6 accounts"
    assert _notices(params, section)["CONTOSO\\jdoe: not on the allow list (1 task)"] is (
        State.WARN
    )


def test_ignored_paths_replace_the_default(section) -> None:
    params = {"ignored_paths": ["\\\\backup\\\\.*", "\\\\Sync"]}
    # The Microsoft task is evaluated again, Backup and Sync are ignored.
    assert _results(params, section)[0].summary == "4 tasks under 4 accounts"


def test_ignored_paths_match_the_whole_task(section) -> None:
    params = {"ignored_paths": ["\\\\Backup"]}
    assert _results(params, section)[0].summary == "7 tasks under 6 accounts"


def test_logon_types(section) -> None:
    assert _results({"logon_types": ["password"]}, section)[0].summary == (
        "4 tasks under 3 accounts"
    )
    assert _results({"logon_types": ["s4u", "interactive"]}, section)[0].summary == (
        "2 tasks under 2 accounts"
    )


def test_invalid_ignored_path_is_reported(section) -> None:
    assert _notices({"ignored_paths": ["("]}, section) == {
        "Invalid pattern in rule: (": State.UNKNOWN
    }


# --- check: allow list and unwanted accounts --------------------------------


def test_task_without_account_and_groups_are_built_in_by_default() -> None:
    section = _parse(
        "\\|A||||||None|Limited|Ready", "\\|B|||Users|S-1-5-32-545|Group|Limited|Ready"
    )
    assert _results({"not_allowed_state": 1}, section)[0].summary == "0 tasks under 0 accounts"
    params = {"not_allowed_state": 1, "builtin_kinds": ["local_system"]}
    assert _notices(params, section) == {
        "(no account): not on the allow list (1 task)": State.WARN,
        "Users: not on the allow list (1 task)": State.WARN,
    }


def test_not_allowed_state_applies_to_every_reported_account(section) -> None:
    assert _notices({"not_allowed_state": 1}, section) == {
        ".\\batch: not on the allow list (1 task)": State.WARN,
        "CONTOSO\\gmsa_rep$: not on the allow list (1 task)": State.WARN,
        "CONTOSO\\old_admin: not on the allow list (1 task)": State.WARN,
        "CONTOSO\\svc_backup: not on the allow list (2 tasks)": State.WARN,
        "svc_sync@contoso.example: not on the allow list (1 task)": State.WARN,
    }


def test_allowed_and_allowed_additional_are_combined(section) -> None:
    params = {
        "not_allowed_state": 2,
        "allowed": [{"account": "CONTOSO\\\\svc_.*"}, {"account": "contoso\\\\gmsa_rep\\$"}],
        "allowed_additional": [
            {"account": "\\$HOSTNAME\\$-is-literal"},
            {"account": "$HOSTNAME$\\\\batch"},
            {"account": "svc_sync@.*"},
        ],
    }
    assert _notices(params, section) == {
        "CONTOSO\\old_admin: not on the allow list (1 task)": State.CRIT,
    }


def test_allowed_matches_the_whole_account_only(section) -> None:
    notices = _notices(
        {"not_allowed_state": 1, "allowed": [{"account": "CONTOSO\\\\svc"}]}, section
    )
    assert "CONTOSO\\svc_backup: not on the allow list (2 tasks)" in notices


def test_allowed_matches_the_sid(section) -> None:
    params = {"not_allowed_state": 1, "allowed": [{"account": DOMAIN_SID + "-.*"}]}
    assert set(_notices(params, section)) == {
        ".\\batch: not on the allow list (1 task)",
        "CONTOSO\\old_admin: not on the allow list (1 task)",
    }


def test_hostname_placeholder_is_escaped() -> None:
    section = ta.parse_windows_task_accounts(
        [
            ["computer", "SRV.APP01", ""],
            ["task", "\\", "A", "SRVXAPP01\\batch", "", "", "", "Password", "Limited", "Ready"],
            ["task", "\\", "B", "SRV.APP01\\batch", "", "", "", "Password", "Limited", "Ready"],
        ]
    )
    params = {"not_allowed_state": 1, "allowed": [{"account": "$HOSTNAME$\\\\batch"}]}
    assert set(_notices(params, section)) == {"SRVXAPP01\\batch: not on the allow list (1 task)"}


def test_forbidden_first_match_wins_and_allow_list_exempts(section) -> None:
    params = {
        "allowed": [{"account": "CONTOSO\\\\svc_backup"}],
        "forbidden": [
            {"pattern": ".*admin.*", "state": 2},
            {"pattern": "CONTOSO\\\\.*", "state": 1},
        ],
    }
    assert _notices(params, section) == {
        "CONTOSO\\gmsa_rep$: unwanted account (1 task)": State.WARN,
        "CONTOSO\\old_admin: unwanted account (1 task)": State.CRIT,
    }


def test_forbidden_and_not_allowed_take_the_worst_state(section) -> None:
    params = {"not_allowed_state": 2, "forbidden": [{"pattern": ".*admin.*", "state": 1}]}
    assert (
        _notices(params, section)[
            "CONTOSO\\old_admin: unwanted account, not on the allow list (1 task)"
        ]
        is State.CRIT
    )


def test_invalid_pattern_is_reported_and_does_not_crash(section) -> None:
    params = {
        "allowed": [{"account": "CONTOSO\\\\(svc"}],
        "forbidden": [{"pattern": "[", "state": 2}],
    }
    assert _notices(params, section) == {
        "Invalid pattern in rule: CONTOSO\\\\(svc": State.UNKNOWN,
        "Invalid pattern in rule: [": State.UNKNOWN,
    }


def test_allow_entry_for_a_task_applies_to_that_task_only(section) -> None:
    # CONTOSO\svc_backup may run \Backup\Nightly, but it also runs \Backup\Weekly.
    params = {
        "not_allowed_state": 1,
        "allowed": [
            {"task": "\\\\backup\\\\nightly", "account": "CONTOSO\\\\svc_backup"},
            {"account": "CONTOSO\\\\(gmsa_rep\\$|old_admin)|svc_sync@.*"},
            {"task": "\\\\LocalJob", "account": "$HOSTNAME$\\\\batch"},
        ],
    }
    assert _notices(params, section) == {
        "CONTOSO\\svc_backup: not on the allow list (1 of 2 tasks)": State.WARN,
    }
    details = [r.details for r in _results(params, section)]
    assert (
        "\\Backup\\Nightly: CONTOSO\\svc_backup (domain account), Password, Highest, Ready\n"
        "\\Backup\\Weekly: CONTOSO\\svc_backup (domain account), Password, Limited, Disabled: "
        "not on the allow list"
    ) in details


def test_allow_entry_task_pattern_matches_the_whole_task(section) -> None:
    params = {
        "not_allowed_state": 1,
        "allowed": [{"task": "\\\\Backup", "account": "CONTOSO\\\\svc_backup"}],
    }
    assert "CONTOSO\\svc_backup: not on the allow list (2 tasks)" in _notices(params, section)
    params["allowed"] = [{"task": "\\\\Backup\\\\.*", "account": "CONTOSO\\\\svc_backup"}]
    assert not [n for n in _notices(params, section) if "svc_backup" in n]


def test_unwanted_account_is_checked_if_one_of_its_tasks_is_not_allowed(section) -> None:
    params = {
        "allowed": [{"task": "\\\\Backup\\\\Nightly", "account": "CONTOSO\\\\svc_backup"}],
        "forbidden": [{"pattern": ".*svc_backup", "state": 2}],
    }
    assert _notices(params, section) == {
        "CONTOSO\\svc_backup: unwanted account (1 of 2 tasks)": State.CRIT
    }
    params["allowed"] = [{"task": "\\\\Backup\\\\.*", "account": "CONTOSO\\\\svc_backup"}]
    assert _notices(params, section) == {}


def test_invalid_task_pattern_is_reported(section) -> None:
    params = {"allowed": [{"task": "(", "account": ".*"}]}
    assert _notices(params, section) == {"Invalid pattern in rule: (": State.UNKNOWN}


def test_account_with_two_spellings_is_matched_under_each_of_them() -> None:
    section = _parse(
        f"\\|A|svc_backup|{DOMAIN_SID}-1105|||Password|Limited|Ready",
        f"\\|B|CONTOSO\\svc_backup|{DOMAIN_SID}-1105|||Password|Limited|Ready",
    )
    params = {"not_allowed_state": 2, "allowed": [{"account": "CONTOSO\\\\svc_.*"}]}
    assert _notices(params, section) == {}
    assert _results(params, section)[1].details == (
        "\\A: svc_backup (domain account), Password, Limited, Ready\n"
        "\\B: CONTOSO\\svc_backup (domain account), Password, Limited, Ready"
    )


def test_sid_pattern_uses_the_baseline_sid_if_the_translation_failed(section) -> None:
    # Domain not reachable: the agent sends the account without SID this time.
    unresolved = _with(
        "\\Backup\\|Nightly|CONTOSO\\svc_backup||||Password|Highest|Ready",
        "\\Backup\\|Weekly|CONTOSO\\svc_backup||||Password|Limited|Disabled",
    )
    params = {
        "not_allowed_state": 1,
        "allowed": [{"account": f"{DOMAIN_SID}-1105"}],
        **_discovered(section),
    }
    assert "CONTOSO\\svc_backup: not on the allow list (2 tasks)" not in _notices(
        params, unresolved
    )


def test_details_name_the_reason(section) -> None:
    params = {"not_allowed_state": 1, "forbidden": [{"pattern": ".*admin.*", "state": 2}]}
    details = [r.details for r in _results(params, section)]
    assert (
        "\\UserLogon: CONTOSO\\old_admin (domain account), Interactive, Limited, Ready: "
        "unwanted account, not on the allow list"
    ) in details


def _many_accounts(count: int) -> ta.Section:
    return _parse(
        *(f"\\|App{i:02}|CONTOSO\\svc_app{i:02}||||Password|Limited|Ready" for i in range(count))
    )


def test_summary_names_at_most_ten_findings() -> None:
    not_ok = [
        r for r in _results({"not_allowed_state": 1}, _many_accounts(13)) if r.state is not State.OK
    ]
    assert len(not_ok) == 11
    assert not_ok[9].summary == "CONTOSO\\svc_app09: not on the allow list (1 task)"
    assert not_ok[10].state is State.WARN
    assert not_ok[10].summary == "3 more findings (see details)"
    assert not_ok[10].details == (
        "\\App10: CONTOSO\\svc_app10 (domain account), Password, Limited, Ready: "
        "not on the allow list(!)\n"
        "\\App11: CONTOSO\\svc_app11 (domain account), Password, Limited, Ready: "
        "not on the allow list(!)\n"
        "\\App12: CONTOSO\\svc_app12 (domain account), Password, Limited, Ready: "
        "not on the allow list(!)"
    )


def test_summary_names_the_worst_findings_first() -> None:
    params = {"not_allowed_state": 1, "forbidden": [{"pattern": ".*svc_app12", "state": 2}]}
    not_ok = [r for r in _results(params, _many_accounts(13)) if r.state is not State.OK]
    assert not_ok[0].state is State.CRIT
    assert not_ok[0].summary.startswith("CONTOSO\\svc_app12: unwanted account")
    assert not_ok[10].state is State.WARN


# --- check: changes since the discovery -------------------------------------

CHANGES = {"added": 1, "changed": 2, "removed": 3}


def _with(*lines: str) -> ta.Section:
    """STRING_TABLE with tasks replaced or added (by path and name).

    A line is "path|name|user|user SID|group|group SID|logon type|run level|state"."""
    new = [["task", *line.split("|")] for line in lines]
    names = {(line[1], line[2]) for line in new}
    section = ta.parse_windows_task_accounts(
        [line for line in STRING_TABLE if line[0] != "task" or (line[1], line[2]) not in names]
        + new
    )
    assert section is not None
    return section


def _without(*names: str) -> ta.Section:
    """STRING_TABLE without the named tasks (by name)."""
    section = ta.parse_windows_task_accounts(
        [line for line in STRING_TABLE if line[0] != "task" or line[2] not in names]
    )
    assert section is not None
    return section


def test_no_changes_no_findings(section) -> None:
    params = {"changes": CHANGES, **_discovered(section)}
    assert _notices(params, section) == {}


def test_changes_need_the_rule(section) -> None:
    changed = _with("\\|New|CONTOSO\\svc_new||||Password|Limited|Ready")
    assert _notices(_discovered(section), changed) == {}


def test_changes_need_a_baseline(section) -> None:
    assert _notices({"changes": CHANGES}, section) == {}


def test_added_task(section) -> None:
    changed = _with(
        "\\|New|CONTOSO\\svc_new||||Password|Limited|Ready",
        "\\|NewSystem|SYSTEM|S-1-5-18|||ServiceAccount|Highest|Ready",
        "\\|NewGroup|||Users|S-1-5-32-545|Group|Limited|Ready",
        "\\Microsoft\\Windows\\|NewMs|CONTOSO\\svc_ms||||Password|Limited|Ready",
    )
    params = {"changes": CHANGES, **_discovered(section)}
    assert _notices(params, changed) == {"New task \\New runs as CONTOSO\\svc_new": State.WARN}


def test_added_task_under_an_allowed_account_is_not_reported(section) -> None:
    changed = _with("\\|New|CONTOSO\\svc_new||||Password|Limited|Ready")
    params = {
        "changes": CHANGES,
        "allowed": [{"account": "CONTOSO\\\\svc_.*"}],
        **_discovered(section),
    }
    assert _notices(params, changed) == {}


def test_task_changed_from_system_is_a_change(section) -> None:
    changed = _with("\\|Updater|CONTOSO\\svc_x||||Password|Highest|Ready")
    params = {"changes": {"changed": 2}, **_discovered(section)}
    assert _notices(params, changed) == {
        "Account of task \\Updater changed from NT-AUTORITÄT\\SYSTEM to CONTOSO\\svc_x": State.CRIT
    }


def test_task_changed_from_domain_group_to_user_is_a_change(section) -> None:
    changed = _with(f"\\|AppUsers|CONTOSO\\svc_x|{DOMAIN_SID}-1300|||Password|Limited|Ready")
    params = {"changes": {"changed": 2}, **_discovered(section)}
    assert _notices(params, changed) == {
        "Account of task \\AppUsers changed from CONTOSO\\App Users to CONTOSO\\svc_x": State.CRIT
    }


def test_local_system_not_built_in_does_not_report_known_tasks_as_added(section) -> None:
    params = {"changes": CHANGES, "builtin_kinds": ["virtual"], **_discovered(section)}
    assert _notices(params, section) == {}


def test_tasks_without_account_are_left_out_of_the_change_detection(section) -> None:
    changed = _with("\\|NewOrphan||||||None|Limited|Ready")
    params = {"changes": CHANGES, "builtin_kinds": ["local_system"], **_discovered(section)}
    assert _notices(params, changed) == {}


def test_changed_account(section) -> None:
    changed = _with(
        # user account -> other user account
        f"\\Backup\\|Nightly|CONTOSO\\svc_other|{DOMAIN_SID}-1200|||Password|Highest|Ready",
        # user account -> built-in
        "\\Reports\\|Export|SYSTEM|S-1-5-18|||ServiceAccount|Limited|Ready",
        # built-in -> user account
        f"\\|Cleanup|CONTOSO\\svc_clean|{DOMAIN_SID}-1201|||Password|Limited|Ready",
        # built-in -> built-in: not reported
        "\\|AnyUser|NETWORK SERVICE|S-1-5-20|||ServiceAccount|Limited|Ready",
    )
    params = {"changes": CHANGES, **_discovered(section)}
    prefix = "Account of task"
    assert _notices(params, changed) == {
        f"{prefix} \\Backup\\Nightly changed from CONTOSO\\svc_backup to CONTOSO\\svc_other": (
            State.CRIT
        ),
        f"{prefix} \\Reports\\Export changed from CONTOSO\\gmsa_rep$ to SYSTEM": State.CRIT,
        f"{prefix} \\Cleanup changed from LOCAL SERVICE to CONTOSO\\svc_clean": State.CRIT,
    }


def test_changes_in_ignored_tasks_are_not_reported(section) -> None:
    changed = _with("\\Microsoft\\Office\\|Telemetry|CONTOSO\\svc_x||||Password|Limited|Ready")
    params = {"changes": CHANGES, **_discovered(section)}
    assert _notices(params, _without("Telemetry")) == {}
    assert _notices(params, changed) == {}
    assert len(_notices({**params, "ignored_paths": []}, changed)) == 1


def test_unresolved_sid_is_not_a_change(section) -> None:
    params = {"changes": CHANGES, **_discovered(section)}
    # Domain not reachable: same name, the SID could not be translated this time.
    unresolved = _with("\\Backup\\|Nightly|contoso\\SVC_BACKUP||||Password|Highest|Ready")
    assert _notices(params, unresolved) == {}
    # The other way round: the baseline has no SID, now there is one.
    changed = _with(
        f"\\|UserLogon|CONTOSO\\old_admin|{DOMAIN_SID}-1300|||Interactive|Limited|Ready"
    )
    assert _notices(params, changed) == {}


def test_renamed_account_with_the_same_sid_is_not_a_change(section) -> None:
    changed = _with(
        f"\\Reports\\|Export|CONTOSO\\gmsa_rep2$|{DOMAIN_SID}-1106|||Password|Limited|Ready"
    )
    params = {"changes": CHANGES, **_discovered(section)}
    assert _notices(params, changed) == {}


def test_removed_task(section) -> None:
    params = {"changes": CHANGES, **_discovered(section)}
    # Cleanup ran under a built-in account: its removal is not reported.
    assert _notices(params, _without("UserLogon", "Cleanup")) == {
        "Task \\UserLogon (CONTOSO\\old_admin) no longer exists": State.UNKNOWN
    }


def test_only_configured_changes_are_reported(section) -> None:
    table = [line for line in STRING_TABLE if line[0] != "task" or line[2] != "UserLogon"]
    table.append("task|\\|New|CONTOSO\\svc_new||||Password|Limited|Ready".split("|"))
    params = {"changes": {"removed": 1}, **_discovered(section)}
    assert _notices(params, ta.parse_windows_task_accounts(table)) == {
        "Task \\UserLogon (CONTOSO\\old_admin) no longer exists": State.WARN
    }


def test_ignore_disabled_skips_changes_of_disabled_tasks(section) -> None:
    changed = _with("\\Backup\\|Weekly|CONTOSO\\svc_x||||Password|Limited|Disabled")
    params = {"changes": CHANGES, "ignore_disabled": True, **_discovered(section)}
    assert _notices(params, changed) == {}
    assert len(_notices({**params, "ignore_disabled": False}, changed)) == 1


def test_logon_types_skip_changes_of_other_tasks(section) -> None:
    changed = _with("\\|Sync|CONTOSO\\svc_x||||S4U|Limited|Running")
    params = {"changes": CHANGES, "logon_types": ["password"], **_discovered(section)}
    assert _notices(params, changed) == {}


def test_no_change_detection_while_the_plugin_reports_an_error(section) -> None:
    broken = ta.parse_windows_task_accounts(
        [["computer", "SRV-APP01", MACHINE_SID], ["error", "boom"]]
    )
    params = {"changes": CHANGES, **_discovered(section)}
    assert list(_notices(params, broken)) == ["Agent plugin reported an error: boom"]


def test_change_to_an_account_allowed_for_another_task_only_is_reported(section) -> None:
    allowed = [{"task": "\\\\Backup\\\\.*", "account": "CONTOSO\\\\svc_backup"}]
    params = {"changes": CHANGES, "allowed": allowed, **_discovered(section)}
    changed = _with(f"\\|Updater|CONTOSO\\svc_backup|{DOMAIN_SID}-1105|||Password|Highest|Ready")
    assert _notices(params, changed) == {
        "Account of task \\Updater changed from NT-AUTORITÄT\\SYSTEM to CONTOSO\\svc_backup": (
            State.CRIT
        )
    }
    params["allowed"] = [{"account": "CONTOSO\\\\svc_backup"}]
    assert _notices(params, changed) == {}


def test_changes_without_a_baseline_are_announced(section) -> None:
    summaries = [r.summary for r in _results({"changes": CHANGES}, section)]
    assert "No change detection: no baseline, run the service discovery" in summaries
    assert all("baseline" not in r.summary for r in _results({}, section))


def test_recreated_account_shows_the_sids(section) -> None:
    changed = _with(
        f"\\Reports\\|Export|CONTOSO\\gmsa_rep$|{DOMAIN_SID}-1999|||Password|Limited|Ready"
    )
    params = {"changes": CHANGES, **_discovered(section)}
    assert list(_notices(params, changed)) == [
        f"Account of task \\Reports\\Export changed from CONTOSO\\gmsa_rep$ ({DOMAIN_SID}-1106) "
        f"to CONTOSO\\gmsa_rep$ ({DOMAIN_SID}-1999)"
    ]


def test_malformed_baseline_does_not_crash(section) -> None:
    baseline = {"\\UserLogon": "CONTOSO\\old_admin", "\\Sync": {"account": "x"}}
    params = {"changes": CHANGES, "discovered_tasks": baseline}
    assert all(isinstance(r.summary, str) for r in _results(params, section))
    assert not [
        r
        for r in _results({"changes": CHANGES, "discovered_tasks": "x"}, section)
        if r.state is not State.OK
    ]


# --- inventory --------------------------------------------------------------


INVENTORY_DEFAULTS = ta.inventory_plugin_windows_task_accounts.inventory_default_parameters


def test_inventory_default_leaves_out_built_in_accounts() -> None:
    assert INVENTORY_DEFAULTS == {"all_tasks": False}


def test_inventory_can_list_all_tasks(section) -> None:
    rows = list(ta.inventory_windows_task_accounts({"all_tasks": True}, section))
    assert len(rows) == len(section.tasks)
    assert rows[0].key_columns == {"task": "\\Microsoft\\Windows\\Defrag\\ScheduledDefrag"}
    assert rows[0].inventory_columns["kind"] == "local_system"


def test_inventory_rows(section) -> None:
    rows = list(ta.inventory_windows_task_accounts(INVENTORY_DEFAULTS, section))
    assert [r.key_columns["task"] for r in rows] == [
        "\\Backup\\Nightly",
        "\\Backup\\Weekly",
        "\\LocalJob",
        "\\Reports\\Export",
        "\\UserLogon",
        "\\Sync",
    ]
    assert rows[2] == TableRow(
        path=["software", "os", "windows_task_accounts"],
        key_columns={"task": "\\LocalJob"},
        inventory_columns={
            "account": ".\\batch",
            "kind": "local_user",
            "logon_type": "Password",
            "run_level": "Limited",
        },
        status_columns={"state": "Ready"},
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_windows_task_accounts.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'cmk_addons.plugins.windows_task_accounts.agent_based'`.

- [ ] **Step 3: Write the implementation**

Create `plugins/windows_task_accounts/agent_based/windows_task_accounts.py`:

```python
#!/usr/bin/env python3
# Copyright (C) 2026 Andre Eckstein - License: GNU General Public License v3
# This file is part of the Checkmk plugin windows_task_accounts. It is subject to the
# terms and conditions defined in the file LICENSE in the root of the repository.
# SPDX-License-Identifier: GPL-3.0-only
"""Windows scheduled tasks and the accounts they run under.

Section <<<windows_task_accounts:sep(124)>>> (agent plugin windows_task_accounts.ps1):

    computer|<computer name>|<machine SID>
    task|<path>|<name>|<user id>|<user SID>|<group id>|<group SID>|<logon type>|<run level>|<state>
    error|<message>
"""

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from cmk.agent_based.v2 import (
    AgentSection,
    CheckPlugin,
    CheckResult,
    DiscoveryResult,
    InventoryPlugin,
    InventoryResult,
    Metric,
    Result,
    Service,
    State,
    StringTable,
    TableRow,
)


@dataclass(frozen=True)
class WinTask:
    path: str
    name: str
    user: str
    user_sid: str
    group: str
    group_sid: str
    logon_type: str
    run_level: str
    state: str

    @property
    def identity(self) -> str:
        """Full name of the task, e.g. \\Backup\\Nightly."""
        path = self.path if self.path.endswith("\\") else self.path + "\\"
        return path + self.name

    @property
    def account(self) -> str:
        """The principal: the user, or the group if the task has no user."""
        return self.user or self.group

    @property
    def sid(self) -> str:
        return self.user_sid if self.user else self.group_sid

    @property
    def is_group(self) -> bool:
        return not self.user and bool(self.group)


@dataclass(frozen=True)
class Section:
    computer: str
    machine_sid: str
    tasks: Sequence[WinTask]
    error: str | None


def parse_windows_task_accounts(string_table: StringTable) -> Section | None:
    if not string_table:
        return None
    computer = machine_sid = ""
    tasks = []
    error = None
    for line in string_table:
        if not line:
            continue
        fields = [field.strip() for field in line]
        match fields[0]:
            case "computer":
                computer, machine_sid = (fields[1:] + ["", ""])[:2]
            case "task" if len(fields) > 2 and fields[2]:
                tasks.append(WinTask(*(fields[1:] + [""] * 9)[:9]))
            case "error":
                error = " ".join(fields[1:]) or "unknown error"
    return Section(computer, machine_sid.upper(), tasks, error)


agent_section_windows_task_accounts = AgentSection(
    name="windows_task_accounts",
    parse_function=parse_windows_task_accounts,
)


DEFAULT_BUILTIN_KINDS = (
    "local_system",
    "local_service",
    "network_service",
    "virtual",
    "no_account",
    "group",
)

# Microsoft's own tasks; nearly all of them run as SYSTEM or a group anyway.
DEFAULT_IGNORED_PATHS = ("\\\\Microsoft\\\\.*",)

# Principal.LogonType as Get-ScheduledTask reports it, in lower case.
LOGON_TYPES = (
    "password",
    "s4u",
    "interactive",
    "interactiveorpassword",
    "serviceaccount",
    "group",
    "none",
)


KIND_TITLES = {
    "local_system": "Local System",
    "local_service": "Local Service",
    "network_service": "Network Service",
    "virtual": "virtual account",
    "no_account": "no account",
    "group": "group",
    "local_user": "local user",
    "managed": "managed service account",
    "domain": "domain account",
    "unknown": "unknown account",
}


_WELL_KNOWN_SIDS = {
    "S-1-5-18": "local_system",
    "S-1-5-19": "local_service",
    "S-1-5-20": "network_service",
    # Everyone, INTERACTIVE, SERVICE, Authenticated Users
    "S-1-1-0": "group",
    "S-1-5-4": "group",
    "S-1-5-6": "group",
    "S-1-5-11": "group",
}


_WELL_KNOWN_NAMES = {
    "system": "local_system",
    "localsystem": "local_system",
    ".\\localsystem": "local_system",
    "nt authority\\system": "local_system",
    "local service": "local_service",
    "localservice": "local_service",
    "nt authority\\localservice": "local_service",
    "nt authority\\local service": "local_service",
    "network service": "network_service",
    "networkservice": "network_service",
    "nt authority\\networkservice": "network_service",
    "nt authority\\network service": "network_service",
    "everyone": "group",
    "users": "group",
    "administrators": "group",
    "interactive": "group",
    "authenticated users": "group",
    "nt authority\\interactive": "group",
    "nt authority\\authenticated users": "group",
    "nt authority\\service": "group",
}


def _is_local_name(account: str, computer: str) -> bool:
    domain, sep, _user = account.partition("\\")
    return bool(sep) and (domain == "." or (bool(computer) and domain.lower() == computer.lower()))


def classify(
    account: str, sid: str, computer: str, machine_sid: str, is_group: bool = False
) -> str:
    """Return the kind of a principal, by SID if there is one, otherwise by name."""
    if is_group:
        # A task without user runs for the members of a group, local or domain.
        return "group"
    sid = sid.upper()
    if sid:
        if sid in _WELL_KNOWN_SIDS:
            return _WELL_KNOWN_SIDS[sid]
        if sid.startswith("S-1-5-80-"):
            return "virtual"
        if sid.startswith(("S-1-5-32-", "S-1-2-")):
            return "group"
        if not sid.startswith("S-1-5-21-"):
            return "unknown"
        if machine_sid:
            if sid.startswith(machine_sid.upper() + "-"):
                return "local_user"
        elif _is_local_name(account, computer):
            return "local_user"
        return "managed" if account.endswith("$") else "domain"

    name = account.lower()
    if not name:
        return "no_account"
    if name in _WELL_KNOWN_NAMES:
        return _WELL_KNOWN_NAMES[name]
    if name.startswith("nt service\\"):
        return "virtual"
    if name.startswith("builtin\\"):
        return "group"
    if _is_local_name(account, computer):
        return "local_user"
    if "\\" in account:
        return "managed" if account.endswith("$") else "domain"
    if "@" in account:
        return "domain"
    return "unknown"


def kind_of_task(task: WinTask, section: Section) -> str:
    return classify(task.account, task.sid, section.computer, section.machine_sid, task.is_group)


def account_key(account: str, sid: str) -> str:
    """Identity of an account: the SID if known, else the lower-case name."""
    return sid.upper() or account.lower()


def discover_windows_task_accounts(section: Section) -> DiscoveryResult:
    if section.error is not None:
        # No baseline from a failed query: the check skips the comparison then.
        yield Service()
        return
    if not section.tasks:
        return
    yield Service(
        parameters={
            "discovered_tasks": {
                # "group": the task has no user, see WinTask.is_group
                t.identity: {"account": t.account, "sid": t.sid}
                | ({"group": True} if t.is_group else {})
                for t in section.tasks
                if t.account or t.sid
            }
        }
    )


@dataclass
class _Account:
    name: str
    sid: str
    kind: str
    tasks: list[WinTask]
    # Further spellings of the same account (same SID), e.g. UPN and DOMAIN\name
    other_names: list[str]

    @property
    def names(self) -> list[str]:
        return [self.name, *self.other_names]


def _group_accounts(section: Section, tasks: Iterable[WinTask]) -> dict[str, _Account]:
    accounts: dict[str, _Account] = {}
    for task in tasks:
        key = account_key(task.account, task.sid)
        if key not in accounts:
            accounts[key] = _Account(
                name=task.account,
                sid=task.sid,
                kind=kind_of_task(task, section),
                tasks=[],
                other_names=[],
            )
        account = accounts[key]
        account.tasks.append(task)
        if task.account.lower() not in (name.lower() for name in account.names):
            account.other_names.append(task.account)
    return accounts


def _account_details(
    account: _Account, findings: Sequence[str] = (), affected: Iterable[WinTask] = ()
) -> str:
    """One line per task of the account, the findings behind the affected ones."""
    suffix = f": {', '.join(findings)}" if findings else ""
    affected_names = {t.identity for t in affected}
    return "\n".join(
        f"{t.identity}: {_display(t.account)} ({KIND_TITLES[account.kind]}), "
        f"{t.logon_type}, {t.run_level}, {t.state}"
        + (suffix if t.identity in affected_names else "")
        for t in sorted(account.tasks, key=lambda t: t.identity.lower())
    )


def _display(account: str) -> str:
    return account or "(no account)"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def match_candidates(account: str, sid: str, computer: str) -> list[str]:
    """Strings a rule pattern is tried against."""
    candidates = [account]
    if sid:
        candidates.append(sid)
    if computer and account.startswith(".\\"):
        candidates.append(computer + account[1:])
    return candidates


def compile_patterns(
    patterns: Iterable[str], computer: str
) -> tuple[list[re.Pattern[str]], list[str]]:
    """Compile rule patterns, return (compiled, invalid).

    $HOSTNAME$ is replaced by the escaped computer name."""
    compiled, invalid = [], []
    for pattern in patterns:
        try:
            compiled.append(
                re.compile(pattern.replace("$HOSTNAME$", re.escape(computer)), re.IGNORECASE)
            )
        except re.error:
            invalid.append(pattern)
    return compiled, invalid


def matches_any(patterns: Iterable[re.Pattern[str]], candidates: Iterable[str]) -> bool:
    candidates = list(candidates)
    return any(p.fullmatch(c) for p in patterns for c in candidates)


def same_account(account_a: str, sid_a: str, account_b: str, sid_b: str) -> bool:
    """Compare by SID only if both sides have one: a SID that could not be
    resolved this time (domain not reachable) must not look like a change."""
    if sid_a and sid_b:
        return sid_a.upper() == sid_b.upper()
    return account_a.lower() == account_b.lower()


# Findings named in the summary; further ones are counted there and listed in the details.
SUMMARY_LIMIT = 10

_STATE_MARKERS = {
    State.OK: "",
    State.WARN: "(!)",
    State.CRIT: "(!!)",
    State.UNKNOWN: "(?)",
}
_SEVERITY = {State.CRIT: 0, State.UNKNOWN: 1, State.WARN: 2, State.OK: 3}

# state, text for the summary, text for the details
_Finding = tuple[State, str, str]


@dataclass(frozen=True)
class _Known:
    """A task as remembered by the service discovery."""

    account: str
    sid: str
    is_group: bool


def _baseline(params: Mapping[str, Any]) -> dict[str, _Known] | None:
    """The tasks remembered by the service discovery, None if there are none."""
    raw = params.get("discovered_tasks")
    if not isinstance(raw, Mapping):
        return None
    return {
        str(name): _Known(
            str(old.get("account", "")), str(old.get("sid", "")), bool(old.get("group"))
        )
        for name, old in raw.items()
        if isinstance(old, Mapping)
    }


# identity, account, SID, is_group -> is the account reported and not allowed?
_Relevance = Callable[[str, str, str, bool], bool]


def _changes(
    changes: Mapping[str, int],
    discovered: Mapping[str, _Known],
    section: Section,
    evaluated: Sequence[WinTask],
    is_relevant: _Relevance,
) -> Iterable[_Finding]:
    """Compare the tasks with the ones remembered by the service discovery."""
    for task in sorted(evaluated, key=lambda t: t.identity.lower()):
        if not (task.account or task.sid):
            # Not part of the baseline, see discover_windows_task_accounts.
            continue
        old = discovered.get(task.identity)
        new_relevant = is_relevant(task.identity, task.account, task.sid, task.is_group)
        if old is None:
            if new_relevant and "added" in changes:
                text = f"New task {task.identity} runs as {_display(task.account)}"
                yield State(changes["added"]), text, text
            continue
        if same_account(old.account, old.sid, task.account, task.sid):
            continue
        old_relevant = is_relevant(task.identity, old.account, old.sid, old.is_group)
        if (new_relevant or old_relevant) and "changed" in changes:
            old_name, new_name = _display(old.account), _display(task.account)
            if old_name.lower() == new_name.lower():
                # The account was deleted and created again: only the SID tells.
                old_name += f" ({old.sid})"
                new_name += f" ({task.sid})"
            text = f"Account of task {task.identity} changed from {old_name} to {new_name}"
            yield State(changes["changed"]), text, text

    if "removed" not in changes:
        return
    existing = {t.identity for t in section.tasks}
    for name, old in sorted(discovered.items()):
        if name not in existing and is_relevant(name, old.account, old.sid, old.is_group):
            text = f"Task {name} ({_display(old.account)}) no longer exists"
            yield State(changes["removed"]), text, text


def _report(findings: Iterable[_Finding]) -> CheckResult:
    """The worst findings go to the summary, the others are counted there."""
    ordered = sorted(findings, key=lambda finding: _SEVERITY[finding[0]])
    not_ok = [finding for finding in ordered if finding[0] is not State.OK]
    for state, text, details in not_ok[:SUMMARY_LIMIT]:
        yield Result(state=state, notice=text, details=details)
    if rest := not_ok[SUMMARY_LIMIT:]:
        yield Result(
            state=State.worst(*(state for state, _text, _details in rest)),
            summary=f"{_plural(len(rest), 'more finding')} (see details)",
            details="\n".join(
                line + _STATE_MARKERS[state]
                for state, _text, details in rest
                for line in details.splitlines()
            ),
        )
    for state, text, details in ordered[len(not_ok) :]:
        yield Result(state=state, notice=text, details=details)


def check_windows_task_accounts(params: Mapping[str, Any], section: Section) -> CheckResult:
    if section.error is not None:
        yield Result(
            state=State(params.get("query_error_state", 3)),
            summary=f"Agent plugin reported an error: {section.error}",
        )
        if not section.tasks:
            return

    builtin_kinds = set(params.get("builtin_kinds", DEFAULT_BUILTIN_KINDS))
    ignore_disabled = params.get("ignore_disabled", False)
    logon_types = params.get("logon_types")
    computer = section.computer

    invalid: list[str] = []

    def compiled(pattern: str) -> list[re.Pattern[str]]:
        patterns, bad = compile_patterns([pattern], computer)
        invalid.extend(bad)
        return patterns

    ignored_paths = [
        p
        for pattern in params.get("ignored_paths", DEFAULT_IGNORED_PATHS)
        for p in compiled(pattern)
    ]

    def path_ignored(identity: str) -> bool:
        return any(p.fullmatch(identity) for p in ignored_paths)

    discovered = _baseline(params)
    if discovered is not None:
        discovered = {name: old for name, old in discovered.items() if not path_ignored(name)}
    # If the agent could not translate an account this time (domain not
    # reachable), patterns written against the SID still have to match.
    known_sids = {old.account.lower(): old.sid for old in (discovered or {}).values() if old.sid}

    evaluated = [
        t
        for t in section.tasks
        if not path_ignored(t.identity)
        and (logon_types is None or t.logon_type.lower() in logon_types)
        and not (ignore_disabled and t.state.lower() == "disabled")
    ]
    reported = [t for t in evaluated if kind_of_task(t, section) not in builtin_kinds]
    accounts = _group_accounts(section, reported)

    yield Result(
        state=State.OK,
        summary=f"{_plural(len(reported), 'task')} under {_plural(len(accounts), 'account')}",
    )
    yield Metric("task_account_tasks", len(reported))
    yield Metric("task_account_accounts", len(accounts))

    # (task pattern or None for every task, account pattern)
    allowed: list[tuple[re.Pattern[str] | None, re.Pattern[str]]] = []
    for entry in [*params.get("allowed", []), *params.get("allowed_additional", [])]:
        task_patterns = compiled(entry["task"]) if entry.get("task") else [None]
        allowed += [(tp, ap) for tp in task_patterns for ap in compiled(entry["account"])]
    forbidden = [
        (pattern, State(entry["state"]))
        for entry in params.get("forbidden", [])
        for pattern in compiled(entry["pattern"])
    ]
    for pattern in invalid:
        yield Result(state=State.UNKNOWN, summary=f"Invalid pattern in rule: {pattern}")

    def candidates_of(names: Sequence[str], sid: str) -> list[str]:
        sid = sid or next(
            (known_sids[name.lower()] for name in names if name.lower() in known_sids),
            "",
        )
        return [c for name in names for c in match_candidates(name, sid, computer)]

    def is_allowed(identity: str, candidates: Sequence[str]) -> bool:
        return any(
            (task_pattern is None or task_pattern.fullmatch(identity))
            and matches_any([account_pattern], candidates)
            for task_pattern, account_pattern in allowed
        )

    findings: list[_Finding] = []
    not_allowed_state = params.get("not_allowed_state")
    for account in sorted(accounts.values(), key=lambda a: a.name.lower()):
        state = State.OK
        reasons = []
        candidates = candidates_of(account.names, account.sid)
        denied = [t for t in account.tasks if not is_allowed(t.identity, candidates)]
        if denied:
            for pattern, forbidden_state in forbidden:
                if matches_any([pattern], candidates):
                    state = forbidden_state
                    reasons.append("unwanted account")
                    break
            if not_allowed_state is not None:
                state = State.worst(state, State(not_allowed_state))
                reasons.append("not on the allow list")
        text = _plural(len(account.tasks), "task")
        if reasons and len(denied) < len(account.tasks):
            text = f"{len(denied)} of {text}"
        findings.append(
            (
                state,
                f"{_display(account.name)}: "
                + (f"{', '.join(reasons)} ({text})" if reasons else text),
                _account_details(account, reasons, denied),
            )
        )

    changes = params.get("changes")
    if changes and section.error is None:
        if discovered is None:
            yield Result(
                state=State.OK,
                summary="No change detection: no baseline, run the service discovery",
            )
        else:
            findings += _changes(
                changes,
                discovered,
                section,
                evaluated,
                lambda identity, account, sid, is_group: (
                    classify(account, sid, computer, section.machine_sid, is_group)
                    not in builtin_kinds
                    and not is_allowed(identity, candidates_of([account], sid))
                ),
            )
    yield from _report(findings)


check_plugin_windows_task_accounts = CheckPlugin(
    name="windows_task_accounts",
    service_name="Windows Task Accounts",
    discovery_function=discover_windows_task_accounts,
    check_function=check_windows_task_accounts,
    # Accounts have to be allowed explicitly; a rule can set the state to OK.
    check_default_parameters={"not_allowed_state": 1},
    check_ruleset_name="windows_task_accounts",
)


def inventory_windows_task_accounts(params: Mapping[str, Any], section: Section) -> InventoryResult:
    ignored_paths, _invalid = compile_patterns(DEFAULT_IGNORED_PATHS, section.computer)
    for task in section.tasks:
        kind = kind_of_task(task, section)
        if not params.get("all_tasks") and (
            kind in DEFAULT_BUILTIN_KINDS or matches_any(ignored_paths, [task.identity])
        ):
            continue
        yield TableRow(
            path=["software", "os", "windows_task_accounts"],
            key_columns={"task": task.identity},
            inventory_columns={
                "account": task.account,
                "kind": kind,
                "logon_type": task.logon_type,
                "run_level": task.run_level,
            },
            status_columns={"state": task.state},
        )


inventory_plugin_windows_task_accounts = InventoryPlugin(
    name="windows_task_accounts",
    inventory_function=inventory_windows_task_accounts,
    inventory_default_parameters={"all_tasks": False},
    inventory_ruleset_name="windows_task_accounts_inventory",
)
```

Delete `plugins/windows_task_accounts/.gitkeep` and `tests/.gitkeep`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_windows_task_accounts.py -q && flake8 plugins/ tests/`
Expected: `106 passed`, no flake8 output.

- [ ] **Step 5: Commit**

```bash
git add -A plugins/windows_task_accounts tests
git commit -m "Add section, check and inventory plugin windows_task_accounts"
```

### Task 2: Check and inventory rules, graphing, inventory UI

**Files:**
- Create: `plugins/windows_task_accounts/rulesets/windows_task_accounts.py`
- Create: `plugins/windows_task_accounts/rulesets/inventory.py`
- Create: `plugins/windows_task_accounts/graphing/windows_task_accounts.py`
- Create: `plugins/windows_task_accounts/inventory_ui/windows_task_accounts.py`
- Modify: `tests/test_windows_task_accounts.py` (imports, new section before the end)

**Interfaces:**
- Consumes: from Task 1 `DEFAULT_BUILTIN_KINDS`, `KIND_TITLES`, `LOGON_TYPES`, `check_plugin_windows_task_accounts`, `inventory_plugin_windows_task_accounts`, `inventory_windows_task_accounts`, `check_windows_task_accounts`.
- Produces: `rule_spec_windows_task_accounts` (CheckParameters, name `windows_task_accounts`, ignores `discovered_tasks`), `rule_spec_windows_task_accounts_inventory` (InventoryParameters, name `windows_task_accounts_inventory`), `metric_task_account_tasks`, `metric_task_account_accounts`, `graph_windows_task_accounts`, `perfometer_windows_task_accounts`, `node_software_os_windows_task_accounts` (view `invtaskaccounts`).

- [ ] **Step 1: Write the failing tests**

In `tests/test_windows_task_accounts.py` replace the import block (from `import pytest` to the `ta` import) with:

```python
import pytest
from cmk.agent_based.v2 import Metric, Result, Service, State, TableRow
from cmk_addons.plugins.windows_task_accounts.agent_based import windows_task_accounts as ta
from cmk_addons.plugins.windows_task_accounts.graphing import windows_task_accounts as graphing
from cmk_addons.plugins.windows_task_accounts.inventory_ui import (
    windows_task_accounts as inventory_ui,
)
from cmk_addons.plugins.windows_task_accounts.rulesets import inventory as inventory_rules
from cmk_addons.plugins.windows_task_accounts.rulesets import windows_task_accounts as rules
```

Append at the end of the file:

```python
# --- rule forms, inventory UI, graphing -------------------------------------


def test_inventory_rule_form_builds() -> None:
    plugin = ta.inventory_plugin_windows_task_accounts
    assert (
        plugin.inventory_ruleset_name
        == inventory_rules.rule_spec_windows_task_accounts_inventory.name
    )
    form = inventory_rules.rule_spec_windows_task_accounts_inventory.parameter_form()
    assert set(form.elements) == set(INVENTORY_DEFAULTS)


def test_inventory_ui_knows_every_column(section) -> None:
    row = next(iter(ta.inventory_windows_task_accounts(INVENTORY_DEFAULTS, section)))
    node = inventory_ui.node_software_os_windows_task_accounts
    assert node.title.localize(lambda x: x) == "Windows Task Accounts"
    assert node.table.view.name == "invtaskaccounts"
    assert node.table.view.title.localize(lambda x: x) == "Windows Task Accounts"
    assert list(node.path) == row.path
    assert set(node.table.columns) == {
        *row.key_columns,
        *row.inventory_columns,
        *row.status_columns,
    }
    assert set(node.table.columns["kind"].mapping) == set(ta.KIND_TITLES)


def test_check_rule_form_builds() -> None:
    form = rules.rule_spec_windows_task_accounts.parameter_form()
    assert set(form.elements) == {
        "builtin_kinds",
        "ignored_paths",
        "logon_types",
        "ignore_disabled",
        "allowed",
        "allowed_additional",
        "not_allowed_state",
        "forbidden",
        "changes",
        "query_error_state",
    }
    assert tuple(form.elements["builtin_kinds"].parameter_form.prefill.value) == (
        ta.DEFAULT_BUILTIN_KINDS
    )
    kinds = {e.name for e in form.elements["builtin_kinds"].parameter_form.elements}
    assert kinds == set(ta.KIND_TITLES)
    logon_types = {e.name for e in form.elements["logon_types"].parameter_form.elements}
    assert logon_types == set(ta.LOGON_TYPES)


def test_allow_list_entries_have_task_and_account() -> None:
    form = rules.rule_spec_windows_task_accounts.parameter_form()
    for name in ("allowed", "allowed_additional"):
        entry = form.elements[name].parameter_form.element_template
        assert list(entry.elements) == ["task", "account"]
        assert not entry.elements["task"].required
        assert entry.elements["account"].required


def test_check_rule_form_prefills_the_default_state() -> None:
    form = rules.rule_spec_windows_task_accounts.parameter_form()
    defaults = ta.check_plugin_windows_task_accounts.check_default_parameters
    assert form.elements["not_allowed_state"].parameter_form.prefill.value == (
        defaults["not_allowed_state"]
    )


def test_check_rule_form_ignores_the_discovered_baseline() -> None:
    # The discovery page validates the effective parameters with this form.
    form = rules.rule_spec_windows_task_accounts.parameter_form()
    assert "discovered_tasks" in form.ignored_elements


def test_graphing_uses_the_metrics_of_the_check(section) -> None:
    yielded = {m.name for m in ta.check_windows_task_accounts({}, section) if isinstance(m, Metric)}
    assert yielded == {
        graphing.metric_task_account_tasks.name,
        graphing.metric_task_account_accounts.name,
    }
    assert set(graphing.graph_windows_task_accounts.simple_lines) == yielded
    assert set(graphing.perfometer_windows_task_accounts.segments) <= yielded
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_windows_task_accounts.py -q`
Expected: collection error `ModuleNotFoundError` for `...windows_task_accounts.graphing`.

- [ ] **Step 3: Write the implementation**

Create `plugins/windows_task_accounts/rulesets/windows_task_accounts.py`:

```python
#!/usr/bin/env python3
# Copyright (C) 2026 Andre Eckstein - License: GNU General Public License v3
# This file is part of the Checkmk plugin windows_task_accounts. It is subject to the
# terms and conditions defined in the file LICENSE in the root of the repository.
# SPDX-License-Identifier: GPL-3.0-only
"""Check parameters of the service "Windows Task Accounts"."""

from cmk.rulesets.v1 import Help, Label, Title
from cmk.rulesets.v1.form_specs import (
    BooleanChoice,
    DefaultValue,
    DictElement,
    Dictionary,
    List,
    MatchingScope,
    MultipleChoice,
    MultipleChoiceElement,
    RegularExpression,
    ServiceState,
)
from cmk.rulesets.v1.rule_specs import CheckParameters, HostCondition, Topic

_PATTERN_HELP = (
    "Regular expression that has to match the whole account, ignoring case. It is tried "
    "against the account as configured in the task (e.g. <tt>CONTOSO\\svc_backup</tt>, "
    "<tt>svc_backup@contoso.example</tt>, <tt>.\\backup</tt>) and against its SID. For a "
    "task that runs for a group it is the group. A backslash has to be written as "
    "<tt>\\\\</tt>, e.g. <tt>CONTOSO\\\\svc_.*</tt>. <tt>$HOSTNAME$</tt> is replaced by the "
    "computer name of the host, so <tt>$HOSTNAME$\\\\backup</tt> matches the local user "
    "<tt>backup</tt> on every host, also if the task is configured with <tt>.\\backup</tt>."
)

_TASK_PATTERN_HELP = (
    "Regular expression that has to match the whole task, ignoring case: its folder and "
    "name as shown in the details of the service <i>Windows Task Accounts</i>, e.g. "
    "<tt>\\Backup\\Nightly</tt>. A backslash has to be written as <tt>\\\\</tt>: "
    "<tt>\\\\Backup\\\\Nightly</tt> for one task, <tt>\\\\Backup\\\\.*</tt> for every task "
    "in the folder <tt>\\Backup</tt> and its subfolders."
)


def _pattern(title: Title) -> RegularExpression:
    return RegularExpression(
        title=title,
        help_text=Help(_PATTERN_HELP),
        predefined_help_text=MatchingScope.FULL,
    )


def _allow_entry() -> Dictionary:
    return Dictionary(
        elements={
            "task": DictElement(
                parameter_form=RegularExpression(
                    title=Title("Only for these tasks"),
                    help_text=Help(
                        _TASK_PATTERN_HELP
                        + " Without this setting the account is allowed for every task of "
                        "the host."
                    ),
                    predefined_help_text=MatchingScope.FULL,
                ),
            ),
            "account": DictElement(
                required=True,
                parameter_form=_pattern(Title("Account")),
            ),
        },
    )


def _parameter_form() -> Dictionary:
    return Dictionary(
        # The baseline the service discovery stores next to the rule parameters.
        ignored_elements=("discovered_tasks",),
        help_text=Help(
            "The service <i>Windows Task Accounts</i> shows which Windows scheduled tasks run "
            "under a user or service account. By default it is WARN for every task whose "
            "account is not on the allow list of this rule."
        ),
        elements={
            "builtin_kinds": DictElement(
                parameter_form=MultipleChoice(
                    title=Title("Built-in accounts"),
                    help_text=Help(
                        "Tasks running under these kinds of accounts are unremarkable and "
                        "not reported. Everything else is reported."
                    ),
                    elements=[
                        MultipleChoiceElement(name="local_system", title=Title("Local System")),
                        MultipleChoiceElement(name="local_service", title=Title("Local Service")),
                        MultipleChoiceElement(
                            name="network_service", title=Title("Network Service")
                        ),
                        MultipleChoiceElement(
                            name="virtual", title=Title("Virtual accounts (NT SERVICE\\...)")
                        ),
                        MultipleChoiceElement(
                            name="no_account", title=Title("Tasks without an account")
                        ),
                        MultipleChoiceElement(
                            name="group",
                            title=Title("Groups (e.g. Users, INTERACTIVE, domain groups)"),
                        ),
                        MultipleChoiceElement(name="local_user", title=Title("Local users")),
                        MultipleChoiceElement(
                            name="managed",
                            title=Title("Managed service accounts (name ends with $)"),
                        ),
                        MultipleChoiceElement(name="domain", title=Title("Domain accounts")),
                        MultipleChoiceElement(name="unknown", title=Title("Unknown accounts")),
                    ],
                    prefill=DefaultValue(
                        [
                            "local_system",
                            "local_service",
                            "network_service",
                            "virtual",
                            "no_account",
                            "group",
                        ]
                    ),
                ),
            ),
            "ignored_paths": DictElement(
                parameter_form=List(
                    title=Title("Ignored tasks"),
                    help_text=Help(
                        "Tasks matching one of these patterns are not evaluated at all, also "
                        "not for changes since the service discovery. Without this setting "
                        "the tasks of Windows itself (<tt>\\\\Microsoft\\\\.*</tt>) are "
                        "ignored; to evaluate them too, set this option with an empty list. "
                        + _TASK_PATTERN_HELP
                    ),
                    element_template=RegularExpression(
                        title=Title("Task"),
                        predefined_help_text=MatchingScope.FULL,
                    ),
                    add_element_label=Label("Add pattern"),
                    editable_order=False,
                ),
            ),
            "logon_types": DictElement(
                parameter_form=MultipleChoice(
                    title=Title("Evaluated logon types"),
                    help_text=Help(
                        "Only tasks with one of these logon types are evaluated. "
                        "<i>Password</i> means that Windows stores the password of the "
                        "account; with <i>S4U</i> no password is stored, with "
                        "<i>Interactive</i> the task only runs while the user is logged on. "
                        "Without this setting every logon type is evaluated."
                    ),
                    elements=[
                        MultipleChoiceElement(name="password", title=Title("Password")),
                        MultipleChoiceElement(name="s4u", title=Title("S4U")),
                        MultipleChoiceElement(name="interactive", title=Title("Interactive")),
                        MultipleChoiceElement(
                            name="interactiveorpassword", title=Title("Interactive or password")
                        ),
                        MultipleChoiceElement(
                            name="serviceaccount", title=Title("Service account")
                        ),
                        MultipleChoiceElement(name="group", title=Title("Group")),
                        MultipleChoiceElement(name="none", title=Title("None")),
                    ],
                    prefill=DefaultValue(["password"]),
                ),
            ),
            "ignore_disabled": DictElement(
                parameter_form=BooleanChoice(
                    title=Title("Disabled tasks"),
                    label=Label("Ignore tasks in the state Disabled"),
                    help_text=Help(
                        "By default disabled tasks are evaluated too, because Windows "
                        "keeps the credentials of their account."
                    ),
                    prefill=DefaultValue(False),
                ),
            ),
            "allowed": DictElement(
                parameter_form=List(
                    title=Title("Allowed accounts"),
                    help_text=Help(
                        "Which account may run which tasks. A task whose account matches an "
                        "entry is OK and exempt from the other settings. An entry without "
                        "tasks allows the account for every task of the host. In a more "
                        "specific rule this list replaces the list of a more general rule."
                    ),
                    element_template=_allow_entry(),
                    add_element_label=Label("Add account"),
                    editable_order=False,
                ),
            ),
            "allowed_additional": DictElement(
                parameter_form=List(
                    title=Title("Additional allowed accounts"),
                    help_text=Help(
                        "Like <i>Allowed accounts</i>, but in addition to the allow list of a "
                        "more general rule instead of replacing it. Use it for host specific "
                        "exceptions."
                    ),
                    element_template=_allow_entry(),
                    add_element_label=Label("Add account"),
                    editable_order=False,
                ),
            ),
            "not_allowed_state": DictElement(
                parameter_form=ServiceState(
                    title=Title("State for accounts that are not allowed"),
                    help_text=Help(
                        "State for every task whose account is not on the allow list, "
                        "by default WARN. Set it to OK to only show the accounts."
                    ),
                    prefill=DefaultValue(ServiceState.WARN),
                ),
            ),
            "forbidden": DictElement(
                parameter_form=List(
                    title=Title("Unwanted accounts"),
                    help_text=Help(
                        "Accounts that must not run tasks, e.g. personal or administrator "
                        "accounts. The first matching entry determines the state. An account "
                        "is not checked if all its tasks are on the allow list."
                    ),
                    element_template=Dictionary(
                        elements={
                            "pattern": DictElement(
                                required=True, parameter_form=_pattern(Title("Pattern"))
                            ),
                            "state": DictElement(
                                required=True,
                                parameter_form=ServiceState(
                                    title=Title("State"),
                                    prefill=DefaultValue(ServiceState.CRIT),
                                ),
                            ),
                        },
                    ),
                    add_element_label=Label("Add account"),
                ),
            ),
            "changes": DictElement(
                parameter_form=Dictionary(
                    title=Title("Changes since the service discovery"),
                    help_text=Help(
                        "The service discovery remembers which task runs under which "
                        "account. Report differences to that for tasks running under a "
                        "reported account that is not on the allow list. To accept a change, "
                        "update the service parameters in the service discovery of the host."
                    ),
                    elements={
                        "added": DictElement(
                            parameter_form=ServiceState(
                                title=Title("State if a task was added"),
                                prefill=DefaultValue(ServiceState.WARN),
                            ),
                        ),
                        "changed": DictElement(
                            parameter_form=ServiceState(
                                title=Title("State if the account of a task changed"),
                                prefill=DefaultValue(ServiceState.WARN),
                            ),
                        ),
                        "removed": DictElement(
                            parameter_form=ServiceState(
                                title=Title("State if a task was removed"),
                                prefill=DefaultValue(ServiceState.WARN),
                            ),
                        ),
                    },
                ),
            ),
            "query_error_state": DictElement(
                parameter_form=ServiceState(
                    title=Title("State if the agent plugin reported an error"),
                    prefill=DefaultValue(ServiceState.UNKNOWN),
                ),
            ),
        },
    )


rule_spec_windows_task_accounts = CheckParameters(
    name="windows_task_accounts",
    title=Title("Windows Task Accounts"),
    topic=Topic.OPERATING_SYSTEM,
    parameter_form=_parameter_form,
    condition=HostCondition(),
)
```

Create `plugins/windows_task_accounts/rulesets/inventory.py`:

```python
#!/usr/bin/env python3
# Copyright (C) 2026 Andre Eckstein - License: GNU General Public License v3
# This file is part of the Checkmk plugin windows_task_accounts. It is subject to the
# terms and conditions defined in the file LICENSE in the root of the repository.
# SPDX-License-Identifier: GPL-3.0-only
"""Parameters of the inventory table software > os > windows_task_accounts."""

from cmk.rulesets.v1 import Help, Label, Title
from cmk.rulesets.v1.form_specs import BooleanChoice, DefaultValue, DictElement, Dictionary
from cmk.rulesets.v1.rule_specs import InventoryParameters, Topic


def _parameter_form() -> Dictionary:
    return Dictionary(
        elements={
            "all_tasks": DictElement(
                required=True,
                parameter_form=BooleanChoice(
                    title=Title("Tasks in the inventory table"),
                    label=Label("Also list tasks under built-in accounts and of Windows itself"),
                    help_text=Help(
                        "By default the table <i>Software > Operating system > Windows Task "
                        "Accounts</i> only contains tasks that run under a user or service "
                        "account and are not in the folder <tt>\\Microsoft</tt>, so a host "
                        "without such tasks has no table. With this option it contains every "
                        "scheduled task of the host, also the ones running as Local System, "
                        "Local Service, Network Service, for a group or without an account. "
                        "The column <i>Kind</i> tells them apart."
                    ),
                    prefill=DefaultValue(False),
                ),
            ),
        },
    )


rule_spec_windows_task_accounts_inventory = InventoryParameters(
    name="windows_task_accounts_inventory",
    title=Title("Windows Task Accounts"),
    topic=Topic.OPERATING_SYSTEM,
    parameter_form=_parameter_form,
)
```

Create `plugins/windows_task_accounts/graphing/windows_task_accounts.py`:

```python
#!/usr/bin/env python3
# Copyright (C) 2026 Andre Eckstein - License: GNU General Public License v3
# This file is part of the Checkmk plugin windows_task_accounts. It is subject to the
# terms and conditions defined in the file LICENSE in the root of the repository.
# SPDX-License-Identifier: GPL-3.0-only
"""Metrics, graph and perfometer of the service "Windows Task Accounts"."""

from cmk.graphing.v1 import Title
from cmk.graphing.v1.graphs import Graph, MinimalRange
from cmk.graphing.v1.metrics import Color, DecimalNotation, Metric, StrictPrecision, Unit
from cmk.graphing.v1.perfometers import Closed, FocusRange, Open, Perfometer

_UNIT_COUNT = Unit(DecimalNotation(""), StrictPrecision(0))

metric_task_account_tasks = Metric(
    name="task_account_tasks",
    title=Title("Scheduled tasks under reported accounts"),
    unit=_UNIT_COUNT,
    color=Color.BLUE,
)

metric_task_account_accounts = Metric(
    name="task_account_accounts",
    title=Title("Accounts running scheduled tasks"),
    unit=_UNIT_COUNT,
    color=Color.ORANGE,
)

graph_windows_task_accounts = Graph(
    name="windows_task_accounts",
    title=Title("Scheduled task accounts"),
    simple_lines=["task_account_tasks", "task_account_accounts"],
    minimal_range=MinimalRange(0, 10),
)

perfometer_windows_task_accounts = Perfometer(
    name="windows_task_accounts",
    focus_range=FocusRange(Closed(0), Open(20)),
    segments=["task_account_tasks"],
)
```

Create `plugins/windows_task_accounts/inventory_ui/windows_task_accounts.py`:

```python
#!/usr/bin/env python3
# Copyright (C) 2026 Andre Eckstein - License: GNU General Public License v3
# This file is part of the Checkmk plugin windows_task_accounts. It is subject to the
# terms and conditions defined in the file LICENSE in the root of the repository.
# SPDX-License-Identifier: GPL-3.0-only
"""Titles and view of the inventory table software > os > windows_task_accounts."""

from cmk.inventory_ui.v1_unstable import ChoiceField, Node, Table, TextField, Title, View

node_software_os_windows_task_accounts = Node(
    name="software_os_windows_task_accounts",
    path=["software", "os", "windows_task_accounts"],
    title=Title("Windows Task Accounts"),
    table=Table(
        view=View(name="invtaskaccounts", title=Title("Windows Task Accounts")),
        columns={
            "task": TextField(Title("Task")),
            "account": TextField(Title("Account")),
            "kind": ChoiceField(
                Title("Kind"),
                mapping={
                    "local_system": "Local System",
                    "local_service": "Local Service",
                    "network_service": "Network Service",
                    "virtual": "Virtual account",
                    "no_account": "No account",
                    "group": "Group",
                    "local_user": "Local user",
                    "managed": "Managed service account",
                    "domain": "Domain account",
                    "unknown": "Unknown",
                },
            ),
            "logon_type": TextField(Title("Logon type")),
            "run_level": TextField(Title("Run level")),
            "state": TextField(Title("State")),
        },
    ),
)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_windows_task_accounts.py -q && flake8 plugins/ tests/ && cmk-validate-plugins`
Expected: `113 passed`, no flake8 output, `cmk-validate-plugins` reports no errors.

- [ ] **Step 5: Commit**

```bash
git add plugins/windows_task_accounts tests
git commit -m "Add rules, graphing and inventory view for windows_task_accounts"
```

### Task 3: Agent plugin and bakery

**Files:**
- Create: `plugins/windows_task_accounts/agents/windows_task_accounts.ps1`
- Create: `plugins/windows_task_accounts/rulesets/agent_config.py`
- Create: `plugins/windows_task_accounts/bakery/windows_task_accounts.py`
- Modify: `tests/test_windows_task_accounts.py` (imports, new section at the end)

**Interfaces:**
- Consumes: the section format of Task 1 (`computer|...`, `task|<path>|<name>|<user>|<user SID>|<group>|<group SID>|<logon type>|<run level>|<state>`, `error|...`).
- Produces: `rule_spec_windows_task_accounts_bakery` (AgentConfig `windows_task_accounts`, keys `deployment`, `interval`), `bakery_plugin_windows_task_accounts` (one `Plugin` for `OS.WINDOWS`, source `windows_task_accounts.ps1`).

- [ ] **Step 1: Write the failing tests**

Replace the import block of `tests/test_windows_task_accounts.py` with the final one:

```python
from pathlib import Path

import pytest
from cmk.agent_based.v2 import Metric, Result, Service, State, TableRow
from cmk_addons.plugins.windows_task_accounts.agent_based import windows_task_accounts as ta
from cmk_addons.plugins.windows_task_accounts.bakery import windows_task_accounts as bakery
from cmk_addons.plugins.windows_task_accounts.graphing import windows_task_accounts as graphing
from cmk_addons.plugins.windows_task_accounts.inventory_ui import (
    windows_task_accounts as inventory_ui,
)
from cmk_addons.plugins.windows_task_accounts.rulesets import agent_config
from cmk_addons.plugins.windows_task_accounts.rulesets import inventory as inventory_rules
from cmk_addons.plugins.windows_task_accounts.rulesets import windows_task_accounts as rules
```

Insert before the section `# --- documentation` (or at the end, if Task 4 is not done yet):

```python
# --- bakery -----------------------------------------------------------------


def test_bakery_rule_form_builds() -> None:
    form = agent_config.rule_spec_windows_task_accounts_bakery.parameter_form()
    assert set(form.elements) == {"deployment", "interval"}
    assert agent_config.rule_spec_windows_task_accounts_bakery.name == (
        bakery.bakery_plugin_windows_task_accounts.name
    )


def _bake(rule: dict) -> list:
    plugin = bakery.bakery_plugin_windows_task_accounts
    return list(plugin.files_function(plugin.parameter_parser(rule)))


def test_bakery_deploys_the_windows_plugin() -> None:
    (plugin,) = _bake({"deployment": ("deploy", None)})
    assert str(plugin.base_os) == "windows"
    assert str(plugin.source) == "windows_task_accounts.ps1"
    assert plugin.interval is None


def test_bakery_interval() -> None:
    (plugin,) = _bake({"deployment": ("deploy", None), "interval": 3600.0})
    assert plugin.interval == 3600


def test_bakery_do_not_deploy() -> None:
    assert not _bake({"deployment": ("do_not_deploy", None), "interval": 3600.0})


def test_agent_plugin_exists_and_is_ascii() -> None:
    # The bakery takes the source from the family's agents/ directory. Windows
    # PowerShell 5.1 reads a script without BOM in the ANSI code page.
    (plugin,) = _bake({"deployment": ("deploy", None)})
    source = Path(bakery.__file__).parent.parent / "agents" / plugin.source
    assert source.read_bytes().isascii()
    text = source.read_text()
    assert "<<<windows_task_accounts:sep(124)>>>" in text
    assert "Get-ScheduledTask" in text


def test_rules_are_named_like_the_service() -> None:
    for rule in (
        rules.rule_spec_windows_task_accounts,
        agent_config.rule_spec_windows_task_accounts_bakery,
        inventory_rules.rule_spec_windows_task_accounts_inventory,
    ):
        assert rule.title.localize(lambda x: x) == "Windows Task Accounts"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_windows_task_accounts.py -q`
Expected: collection error `ModuleNotFoundError` for `...windows_task_accounts.bakery`.

- [ ] **Step 3: Write the implementation**

Create `plugins/windows_task_accounts/agents/windows_task_accounts.ps1` (ASCII only, no BOM):

```powershell
# Copyright (C) 2026 Andre Eckstein - License: GNU General Public License v3
# This file is part of the Checkmk plugin windows_task_accounts. It is subject to the
# terms and conditions defined in the file LICENSE in the root of the repository.
# SPDX-License-Identifier: GPL-3.0-only

<#
.SYNOPSIS
    Checkmk agent plugin: Windows scheduled tasks and the accounts they run under.
.DESCRIPTION
    Prints every scheduled task, unfiltered. The evaluation (which accounts are
    reported, which are allowed, which task folders are ignored) happens on the
    Checkmk server in the check plugin windows_task_accounts, so the plugin
    needs no configuration.

    <<<windows_task_accounts:sep(124)>>>
    computer|<computer name>|<machine SID>
    task|<path>|<name>|<user id>|<user SID>|<group id>|<group SID>|<logon type>|<run level>|<state>
    error|<message>

    Keep this file ASCII only: Windows PowerShell 5.1 reads scripts without a
    BOM in the ANSI code page.
#>

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$script:SidCache = @{}

function Format-Field {
    # Pipes and line breaks would break the section format.
    param($Value)
    if ($null -eq $Value) { return '' }
    return (([string]$Value) -replace '[|\r\n]+', ' ').Trim()
}

function Get-MachineSid {
    # The SID prefix shared by the local accounts of this computer. A domain
    # controller has no local accounts: the query would walk the directory and
    # return the domain SID, so the field stays empty there.
    try {
        $role = (Get-CimInstance -ClassName Win32_ComputerSystem -Property DomainRole).DomainRole
        if ($role -ge 4) { return '' }
        $account = Get-CimInstance -ClassName Win32_UserAccount -Filter 'LocalAccount=True' |
            Select-Object -First 1
        if ($account) {
            $sid = New-Object System.Security.Principal.SecurityIdentifier($account.SID)
            return $sid.AccountDomainSid.Value
        }
    } catch {
        # Leave the field empty: the check then falls back to the account name.
    }
    return ''
}

function Resolve-Principal {
    # Returns @(<name>, <SID>). A principal given as SID string is translated
    # to a name, a name to a SID. A side that cannot be translated (deleted
    # account, domain not reachable) keeps what the task has: the SID as name,
    # or an empty SID.
    param([string]$Principal)
    if ([string]::IsNullOrEmpty($Principal)) { return @('', '') }
    $key = $Principal.ToLowerInvariant()
    if ($script:SidCache.ContainsKey($key)) { return $script:SidCache[$key] }

    $result = @($Principal, '')
    if ($Principal -match '^S-1-\d+(-\d+)+$') {
        $result = @($Principal, $Principal.ToUpperInvariant())
        try {
            $sid = New-Object System.Security.Principal.SecurityIdentifier($Principal)
            $result[0] = $sid.Translate([System.Security.Principal.NTAccount]).Value
        } catch {
            # Keep the SID as name.
        }
    } else {
        $name = $Principal
        if ($name.StartsWith('.\')) { $name = $env:COMPUTERNAME + $name.Substring(1) }
        try {
            $ntAccount = New-Object System.Security.Principal.NTAccount($name)
            $result[1] = $ntAccount.Translate([System.Security.Principal.SecurityIdentifier]).Value
        } catch {
            # Leave the SID empty: the check then classifies by name.
        }
    }
    $script:SidCache[$key] = $result
    return $result
}

Write-Host '<<<windows_task_accounts:sep(124)>>>'
Write-Host ('computer|{0}|{1}' -f (Format-Field $env:COMPUTERNAME), (Get-MachineSid))

try {
    if (-not (Get-Command -Name Get-ScheduledTask -ErrorAction SilentlyContinue)) {
        throw 'Get-ScheduledTask is not available (Windows 8 / Server 2012 or later required)'
    }
    $tasks = Get-ScheduledTask | Sort-Object -Property TaskPath, TaskName
    foreach ($task in $tasks) {
        $principal = $task.Principal
        $user = Resolve-Principal (Format-Field $principal.UserId)
        $group = Resolve-Principal (Format-Field $principal.GroupId)
        $fields = @(
            'task',
            (Format-Field $task.TaskPath),
            (Format-Field $task.TaskName),
            (Format-Field $user[0]),
            $user[1],
            (Format-Field $group[0]),
            $group[1],
            (Format-Field $principal.LogonType),
            (Format-Field $principal.RunLevel),
            (Format-Field $task.State)
        )
        Write-Host ($fields -join '|')
    }
} catch {
    Write-Host ('error|' + (Format-Field $_.Exception.Message))
}
```

Create `plugins/windows_task_accounts/rulesets/agent_config.py`:

```python
#!/usr/bin/env python3
# Copyright (C) 2026 Andre Eckstein - License: GNU General Public License v3
# This file is part of the Checkmk plugin windows_task_accounts. It is subject to the
# terms and conditions defined in the file LICENSE in the root of the repository.
# SPDX-License-Identifier: GPL-3.0-only
"""Bakery rule for the agent plugin windows_task_accounts.ps1."""

from cmk.rulesets.v1 import Help, Label, Title
from cmk.rulesets.v1.form_specs import (
    CascadingSingleChoice,
    CascadingSingleChoiceElement,
    DefaultValue,
    DictElement,
    Dictionary,
    FixedValue,
    TimeMagnitude,
    TimeSpan,
)
from cmk.rulesets.v1.rule_specs import AgentConfig, Topic


def _parameter_form() -> Dictionary:
    return Dictionary(
        help_text=Help(
            "Deploys the agent plugin <tt>windows_task_accounts.ps1</tt>, which reports every "
            "Windows scheduled task and the account it runs under. Which accounts are "
            "reported and which are allowed is set in the rule <i>Windows Task Accounts</i> "
            "for the service, so changing that never requires baking agents."
        ),
        elements={
            "deployment": DictElement(
                required=True,
                parameter_form=CascadingSingleChoice(
                    title=Title("Deployment"),
                    prefill=DefaultValue("deploy"),
                    elements=[
                        CascadingSingleChoiceElement(
                            name="deploy",
                            title=Title("Deploy the plugin"),
                            parameter_form=FixedValue(value=None),
                        ),
                        CascadingSingleChoiceElement(
                            name="do_not_deploy",
                            title=Title("Do not deploy the plugin"),
                            parameter_form=FixedValue(value=None),
                        ),
                    ],
                ),
            ),
            "interval": DictElement(
                parameter_form=TimeSpan(
                    title=Title("Run asynchronously and cache the result"),
                    help_text=Help(
                        "Translating accounts of a domain that is not reachable can take a "
                        "while. With this option the plugin runs in the background and the "
                        "agent delivers the cached result."
                    ),
                    label=Label("Interval"),
                    displayed_magnitudes=[TimeMagnitude.HOUR, TimeMagnitude.MINUTE],
                    prefill=DefaultValue(3600.0),
                ),
            ),
        },
    )


rule_spec_windows_task_accounts_bakery = AgentConfig(
    name="windows_task_accounts",
    title=Title("Windows Task Accounts"),
    topic=Topic.OPERATING_SYSTEM,
    parameter_form=_parameter_form,
)
```

Create `plugins/windows_task_accounts/bakery/windows_task_accounts.py`:

```python
#!/usr/bin/env python3
# Copyright (C) 2026 Andre Eckstein - License: GNU General Public License v3
# This file is part of the Checkmk plugin windows_task_accounts. It is subject to the
# terms and conditions defined in the file LICENSE in the root of the repository.
# SPDX-License-Identifier: GPL-3.0-only
"""Bakery plugin: deploys windows_task_accounts.ps1 to Windows hosts."""

from pathlib import Path
from typing import Literal

from cmk.bakery.v2_unstable import OS, BakeryPlugin, FileGenerator, Plugin
from pydantic import BaseModel


class Config(BaseModel):
    deployment: tuple[Literal["deploy", "do_not_deploy"], None]
    interval: float | None = None


def get_windows_task_accounts_files(conf: Config) -> FileGenerator:
    if conf.deployment[0] != "deploy":
        return
    yield Plugin(
        base_os=OS.WINDOWS,
        source=Path("windows_task_accounts.ps1"),
        interval=conf.interval,
    )


bakery_plugin_windows_task_accounts = BakeryPlugin(
    name="windows_task_accounts",
    parameter_parser=Config.model_validate,
    default_parameters=None,
    files_function=get_windows_task_accounts_files,
)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_windows_task_accounts.py -q && flake8 plugins/ tests/ && cmk-validate-plugins`
Expected: `119 passed`, no flake8 output, no validation errors.

- [ ] **Step 5: Commit**

```bash
git add plugins/windows_task_accounts tests
git commit -m "Add agent plugin and bakery rule for windows_task_accounts"
```

### Task 4: Man page, docs, dev-site run

**Files:**
- Create: `plugins/windows_task_accounts/checkman/windows_task_accounts`
- Modify: `tests/test_windows_task_accounts.py` (new section at the end)
- Modify: `README.md` (replace the template README by the plugin README)
- Modify: `Changelog.md`
- Modify: `docs/superpowers/specs/2026-10-15-task-accounts-design.md` (amendments)
- Create (untracked): `temp/SRV-APP01.agent_output`

**Interfaces:**
- Consumes: everything above.
- Produces: documentation; a verified dev-site run.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_windows_task_accounts.py`:

```python
# --- documentation ----------------------------------------------------------


def test_man_page_has_each_key_once() -> None:
    man_page = Path(ta.__file__).parent.parent / "checkman" / "windows_task_accounts"
    keys = [line.split(":")[0] for line in man_page.read_text().splitlines() if line[:1].isalpha()]
    assert keys == [
        "title",
        "agents",
        "catalog",
        "license",
        "distribution",
        "description",
        "discovery",
    ]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_windows_task_accounts.py -q -k man_page`
Expected: FAIL with `FileNotFoundError` for `checkman/windows_task_accounts`.

- [ ] **Step 3: Write the man page**

Create `plugins/windows_task_accounts/checkman/windows_task_accounts`:

```text
title: Windows Task Accounts
agents: windows
catalog: os/services
license: GPLv3
distribution: Andre Eckstein
description:
 This check shows which Windows scheduled tasks do not run under a built-in
 system account but under a user or service account: a domain account, a
 local user or a managed service account. It needs the agent plugin
 {windows_task_accounts.ps1}, which is deployed with the agent bakery rule
 {Windows Task Accounts}.

 The account of a task is its user, or its group if the task runs for a
 group. Every account gets a kind, by its SID if the agent could translate
 the account, otherwise by its name: Local System, Local Service, Network
 Service, virtual account ({NT SERVICE\...}), group (e.g. {Users},
 {INTERACTIVE}, any task without user but with a group), local user,
 managed service account (name ends with {$}), domain account or unknown.
 Tasks without user and group are a kind of their own. By default Local
 System, Local Service, Network Service, virtual accounts, groups and tasks
 without an account are built-in and not reported. The tasks of Windows
 itself (folder {\Microsoft}) are ignored by default.

 By default the service is {WARN} for every task whose account is not on
 the allow list. With the rule {Windows Task Accounts} for the service you
 can define the allow list (which account may run which tasks) and the
 state for everything that is not on it, set which kinds are built-in
 accounts, which task folders are ignored and which logon types are
 evaluated (e.g. only {Password}: tasks whose password Windows stores),
 ignore disabled tasks, define unwanted accounts with a state, and report
 changes since the service discovery (added tasks, changed accounts and
 removed tasks; tasks without an account are left out of this comparison).
 To accept a change, update the service parameters in the service discovery
 of the host. If the agent plugin reports an error the service is
 {UNKNOWN} (configurable).

 Account patterns are regular expressions that have to match the whole
 account name or SID, ignoring case. {$HOSTNAME$} is replaced by the
 computer name. Task patterns have to match the whole task, folder and
 name, e.g. {\Backup\Nightly}.

 Limitations: computer accounts ({DOMAIN\HOST$}) are shown as managed
 service accounts. An account without domain that cannot be translated to
 a SID is shown as unknown. The agent plugin needs Windows 8 / Server 2012
 or later.

 The tasks under reported accounts are also available in the HW/SW
 inventory under {Software > Operating system > Windows Task Accounts}.
 The HW/SW inventory rule {Windows Task Accounts} makes the table list
 every scheduled task instead.

discovery:
 One service is created for each host whose agent sends the section
 {windows_task_accounts} with at least one task or an error.
```

- [ ] **Step 4: Run everything CI runs**

Run: `.devcontainer/ci.sh`
Expected: black/isort/flake8 clean, `120 passed`, `cmk-validate-plugins` without errors.

- [ ] **Step 5: Run the plugin in the dev site**

Create `temp/SRV-APP01.agent_output` (fictional data only):

```text
<<<check_mk>>>
Version: 2.5.0p15
AgentOS: windows
<<<windows_task_accounts:sep(124)>>>
computer|SRV-APP01|S-1-5-21-1000-2000-3000
task|\Microsoft\Windows\Defrag\|ScheduledDefrag|SYSTEM|S-1-5-18|||ServiceAccount|Highest|Ready
task|\Microsoft\Windows\Shell\|CreateObjectTask|||Users|S-1-5-32-545|Group|Limited|Ready
task|\Microsoft\Office\|Telemetry|CONTOSO\jdoe|S-1-5-21-4000-5000-6000-1500|||Interactive|Limited|Ready
task|\|Updater|NT-AUTORITÄT\SYSTEM|S-1-5-18|||ServiceAccount|Highest|Ready
task|\|Cleanup|LOCAL SERVICE|S-1-5-19|||ServiceAccount|Limited|Ready
task|\Backup\|Nightly|CONTOSO\svc_backup|S-1-5-21-4000-5000-6000-1105|||Password|Highest|Ready
task|\Backup\|Weekly|CONTOSO\svc_backup|S-1-5-21-4000-5000-6000-1105|||Password|Limited|Disabled
task|\|LocalJob|.\batch|S-1-5-21-1000-2000-3000-1001|||Password|Limited|Ready
task|\Reports\|Export|CONTOSO\gmsa_rep$|S-1-5-21-4000-5000-6000-1106|||Password|Limited|Ready
task|\|UserLogon|CONTOSO\old_admin||||Interactive|Limited|Ready
task|\|Sync|svc_sync@contoso.example|S-1-5-21-4000-5000-6000-1107|||S4U|Limited|Running
task|\|AnyUser|||INTERACTIVE|S-1-5-4|Group|Limited|Ready
task|\|AppUsers|||CONTOSO\App Users|S-1-5-21-4000-5000-6000-2000|Group|Limited|Ready
task|\|Orphan|||||None|Limited|Ready
```

Then:

```bash
omd restart && cmk -R
.devcontainer/test-host.sh SRV-APP01 temp/SRV-APP01.agent_output
cmk -vI --detect-plugins=windows_task_accounts SRV-APP01
cmk -v --detect-plugins=windows_task_accounts SRV-APP01
```

Expected: discovery creates `Windows Task Accounts`; the check prints `6 tasks under 5 accounts` followed by five WARN findings (`not on the allow list`). Open the rule *Setup > Services > Service monitoring rules > Windows Task Accounts* in the GUI (port 5000, `/cmk/`) and check that the form renders. Afterwards: `.devcontainer/test-host.sh --remove SRV-APP01`.

- [ ] **Step 6: Documentation**

- `README.md`: replace the template README with a plugin README in the layout of `temp/reference/README.md` (sections Requirements, Installation, Setup, Service, Account kinds, Rule, Changes since the service discovery, Inventory, Limitations, Agent output, Development, License), adapted to tasks: kinds incl. *Group*, the settings *Ignored tasks* (default `\\Microsoft\\.*`) and *Evaluated logon types*, task patterns against `\<folder>\<name>`, view `invtaskaccounts` (search `invtaskaccounts_search`), requirement Windows 8 / Server 2012. Fictional names only.
- `Changelog.md`: under `## [Unreleased]` add `- Initial implementation: agent plugin windows_task_accounts.ps1 with bakery rule, service Windows Task Accounts with check parameters, metrics and graph, HW/SW inventory table with view. The agent plugin is not yet verified on Windows hosts.`
- Spec: append a section `## Amendments from the implementation` with the six items of "Decisions beyond the spec" of this plan.

- [ ] **Step 7: Commit**

```bash
git add plugins/windows_task_accounts tests README.md Changelog.md docs
git commit -m "Add man page and documentation for windows_task_accounts"
```

Then tell the user that the PowerShell plugin has to be tested on real Windows hosts (German and English OS, domain member, domain controller, a task with a deleted account, a task running for a group) and update the status in `CLAUDE.local.md`.
