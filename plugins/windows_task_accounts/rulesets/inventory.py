#!/usr/bin/env python3
# Copyright (C) 2026 Andre Eckstein - License: GNU General Public License v3
# This file is part of the Checkmk plugin windows_task_accounts. It is subject to the
# terms and conditions defined in the file LICENSE in the root of the repository.
# SPDX-License-Identifier: GPL-3.0-only
"""Parameters of the inventory table software > os > windows_task_accounts."""

from cmk.rulesets.v1 import Help, Label, Title
from cmk.rulesets.v1.form_specs import (
    BooleanChoice,
    DefaultValue,
    DictElement,
    Dictionary,
    List,
    MatchingScope,
    RegularExpression,
)
from cmk.rulesets.v1.rule_specs import InventoryParameters, Topic


def _parameter_form() -> Dictionary:
    return Dictionary(
        elements={
            "all_tasks": DictElement(
                required=True,
                parameter_form=BooleanChoice(
                    title=Title("Tasks in the inventory table"),
                    label=Label("Also list tasks under built-in accounts"),
                    help_text=Help(
                        "By default the table <i>Software > Operating system > Windows Task "
                        "Accounts</i> only contains tasks that run under a user or service "
                        "account, so a host without such tasks has no table. With this "
                        "option it contains also the tasks running as Local System, Local "
                        "Service, Network Service, for a group or without an account. The "
                        "column <i>Kind</i> tells them apart. Without the setting "
                        "<i>Ignored tasks</i> this option also lists the tasks of Windows "
                        "itself (folder <tt>\\Microsoft</tt>)."
                    ),
                    prefill=DefaultValue(False),
                ),
            ),
            "ignored_paths": DictElement(
                parameter_form=List(
                    title=Title("Ignored tasks"),
                    help_text=Help(
                        "Tasks matching one of these patterns are not listed in the table. "
                        "Regular expression that has to match the whole task, ignoring case: "
                        "its folder and name, e.g. <tt>\\Backup\\Nightly</tt>. A "
                        "backslash has to be written as <tt>\\\\</tt>: "
                        "<tt>\\\\Backup\\\\.*</tt> for every task in the folder "
                        "<tt>\\Backup</tt>. Without this setting the tasks of Windows "
                        "itself (<tt>\\\\Microsoft\\\\.*</tt>) are left out, unless the "
                        "built-in accounts are listed too (<i>Tasks in the inventory "
                        "table</i>). The list "
                        "replaces that default: add <tt>\\\\Microsoft\\\\.*</tt> to "
                        "keep leaving them out. This setting is independent of the setting "
                        "<i>Ignored tasks</i> of the service rule. Invalid patterns are "
                        "skipped."
                    ),
                    element_template=RegularExpression(
                        title=Title("Task"),
                        predefined_help_text=MatchingScope.FULL,
                    ),
                    add_element_label=Label("Add pattern"),
                    editable_order=False,
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
