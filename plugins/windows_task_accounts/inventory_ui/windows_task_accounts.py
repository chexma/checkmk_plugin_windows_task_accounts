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
