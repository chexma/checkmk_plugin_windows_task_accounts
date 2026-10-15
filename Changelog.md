# Changelog

All notable changes to this plugin. Versions match `version` in `package`
and the release tags `v<version>`.

## [Unreleased]

## [2.5.2] - 2026-10-15

- HW/SW inventory rule: new setting *Ignored tasks* (default
  `\\Microsoft\\.*`), independent of the service rule. The option *Tasks in
  the inventory table* now means "also list tasks under built-in accounts";
  without *Ignored tasks* it still lists every task as before.

## [2.5.1] - 2026-10-15

- A scheduled task that is registered but cannot be read (typically: its
  task file is missing) no longer turns the service UNKNOWN or hides the
  other tasks. The agent plugin falls back to reading the registered tasks
  folder by folder and task by task, and the service names each unreadable
  task with a new configurable state (default WARN).
- Repeated identical error messages of the agent plugin are shown once.

## [2.5.0] - 2026-10-15

- Initial implementation: agent plugin windows_task_accounts.ps1 with bakery rule, service Windows Task Accounts with check parameters, metrics and graph, HW/SW inventory table with view. The agent plugin is not yet verified on Windows hosts.
