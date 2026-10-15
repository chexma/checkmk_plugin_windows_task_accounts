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
                        "ignored. The list replaces this default: add "
                        "<tt>\\\\Microsoft\\\\.*</tt> to keep ignoring "
                        "the tasks of Windows itself, or leave the list empty to "
                        "evaluate them too. " + _TASK_PATTERN_HELP
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
