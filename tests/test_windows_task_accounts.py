# Copyright (C) 2026 Andre Eckstein - License: GNU General Public License v3
# This file is part of the Checkmk plugin windows_task_accounts. It is subject to the
# terms and conditions defined in the file LICENSE in the root of the repository.
# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the plugin family windows_task_accounts. All names are fictional."""

import pytest
from cmk.agent_based.v2 import Metric, Result, Service, State, TableRow
from cmk_addons.plugins.windows_task_accounts.agent_based import windows_task_accounts as ta
from cmk_addons.plugins.windows_task_accounts.graphing import windows_task_accounts as graphing
from cmk_addons.plugins.windows_task_accounts.inventory_ui import (
    windows_task_accounts as inventory_ui,
)
from cmk_addons.plugins.windows_task_accounts.rulesets import inventory as inventory_rules
from cmk_addons.plugins.windows_task_accounts.rulesets import windows_task_accounts as rules

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
