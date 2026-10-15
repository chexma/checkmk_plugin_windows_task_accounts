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
