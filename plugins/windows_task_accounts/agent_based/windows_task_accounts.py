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
    errors = []
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
                errors.append(" ".join(fields[1:]) or "unknown error")
    return Section(computer, machine_sid.upper(), tasks, "; ".join(errors) or None)


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
    if not section.tasks:
        if section.error is not None:
            # No baseline from a failed query: the check skips the comparison then.
            yield Service()
        return
    yield Service(
        parameters={
            "discovered_tasks": {
                # "group": the task has no user, see WinTask.is_group
                t.identity: {"account": t.account, "sid": t.sid, "logon_type": t.logon_type}
                | ({"group": True} if t.is_group else {})
                | ({"disabled": True} if t.state.lower() == "disabled" else {})
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
    logon_type: str = ""
    disabled: bool = False


def _baseline(params: Mapping[str, Any]) -> dict[str, _Known] | None:
    """The tasks remembered by the service discovery, None if there are none."""
    raw = params.get("discovered_tasks")
    if not isinstance(raw, Mapping):
        return None
    return {
        str(name): _Known(
            str(old.get("account", "")),
            str(old.get("sid", "")),
            bool(old.get("group")),
            str(old.get("logon_type", "")),
            bool(old.get("disabled")),
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

    if "removed" not in changes or section.error is not None:
        # An unreadable task must not look removed.
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
        # The rule filters both sides of the comparison.
        discovered = {
            name: old
            for name, old in discovered.items()
            if not path_ignored(name)
            and (logon_types is None or not old.logon_type or old.logon_type.lower() in logon_types)
            and not (ignore_disabled and old.disabled)
        }
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
        account_patterns = compiled(entry["account"])
        task_patterns = compiled(entry["task"]) if entry.get("task") else [None]
        allowed += [(tp, ap) for tp in task_patterns for ap in account_patterns]
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
    if changes:
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
