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
