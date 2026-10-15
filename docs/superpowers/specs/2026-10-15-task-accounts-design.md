# Design: Checkmk plugin `windows_task_accounts`

Date: 2026-10-15. Status: design agreed with the user, nothing implemented yet.

## Purpose

Show which Windows scheduled tasks do not run under a built-in system account
(SYSTEM, LocalService, NetworkService, groups) but under a user or service
account, and alert on accounts that are not allowed. Counterpart of the plugin
`windows_service_accounts` (Windows services), whose structure, naming, form
specs, help texts, test style and README/checkman layout this plugin mirrors.
The agent plugin is deployed through the agent bakery.

Target: Checkmk 2.5 (devcontainer: `ultimate` 2.5.0p15). Windows hosts only
(Windows 8 / Server 2012 and later: `Get-ScheduledTask`).

All names (MKP, plugin directory, files, section, check plugin, rulesets,
bakery plugin, inventory path, graph, perfometer, man page) are
`windows_task_accounts`. Metrics: `task_account_tasks`,
`task_account_accounts`. Inventory view: `invtaskaccounts`. Service and rule
title: `Windows Task Accounts`.

## Data flow

Bakery rule -> `windows_task_accounts.ps1` on the host -> section
`<<<windows_task_accounts:sep(124)>>>` -> one service `Windows Task Accounts`
per host, plus the inventory table `software > os > windows_task_accounts`.

## Components

All files live in `plugins/windows_task_accounts/`.

| Component | File |
|---|---|
| Agent plugin (PowerShell 5.1, ASCII only) | `agents/windows_task_accounts.ps1` |
| Section, check and inventory plugin | `agent_based/windows_task_accounts.py` |
| Check parameters | `rulesets/windows_task_accounts.py` |
| Bakery ruleset (deploy / do not deploy, cache interval) | `rulesets/agent_config.py` |
| Bakery plugin (`cmk.bakery.v2_unstable`) | `bakery/windows_task_accounts.py` |
| Inventory parameters (`all_tasks`) | `rulesets/inventory.py` |
| Metrics, graph, perfometer | `graphing/windows_task_accounts.py` |
| Inventory table + view (`cmk.inventory_ui.v1_unstable`) | `inventory_ui/windows_task_accounts.py` |
| Checkman | `checkman/windows_task_accounts` |
| Tests | `tests/test_windows_task_accounts.py` |

## Agent plugin

`windows_task_accounts.ps1` reads all tasks with `Get-ScheduledTask` and
prints one line per task, unfiltered (also tasks under `\Microsoft\` and
SYSTEM). It has no configuration file; all evaluation happens in the check,
so changing a rule never requires baking agents.

```text
<<<windows_task_accounts:sep(124)>>>
computer|<computer name>|<machine SID>
task|<path>|<name>|<user id>|<user SID>|<group id>|<group SID>|<logon type>|<run level>|<state>
error|<message>
```

- `<path>` is `TaskPath` (e.g. `\`, `\Backup\`), `<name>` is `TaskName`.
  The check joins them to the task identity `\Backup\Nightly`.
- `<user id>` is `Principal.UserId` as configured (`SYSTEM`,
  `CONTOSO\svc_backup`, `svc_backup`, ...). If it is a SID string
  (`S-1-...`), it goes into `<user SID>` and `<user id>` becomes the
  translated name (or stays the SID if the translation fails).
- `<user SID>` is the user translated to a SID (cached), empty if that fails.
  A name starting with `.\` is translated as `<computer>\name`.
- `<group id>` / `<group SID>`: `Principal.GroupId` and its SID, same rules.
- `<logon type>`: `Principal.LogonType` (`Password`, `S4U`,
  `Interactive`, `InteractiveOrPassword`, `ServiceAccount`, `Group`,
  `None`), the names `Get-ScheduledTask` reports.
- `<run level>`: `Principal.RunLevel` (`Limited`, `Highest`).
- `<state>`: `State` (`Ready`, `Running`, `Disabled`, `Queued`, `Unknown`).
- `<machine SID>`: SID prefix of the local accounts, empty on domain
  controllers (`DomainRole` >= 4), as in the reference.
- Pipes and line breaks inside a field are replaced by a blank; output UTF-8.
- If `Get-ScheduledTask` is missing or fails, the plugin prints the header,
  the `computer` line and `error|<message>`. There is no COM fallback.
- Last run time/result (`Get-ScheduledTaskInfo`) is not collected (slow,
  not about accounts).

## Bakery

Rule `Windows Task Accounts`, topic operating system: deploy / do not deploy,
optionally run asynchronously and cache the result (default 1 hour). One
`Plugin` for `OS.WINDOWS`. Same as the reference.

## Check `Windows Task Accounts`

One service per host, discovered if the section has at least one `task` line
or an `error` line.

### Account kinds

The principal of a task is its user if it has one, otherwise its group.
Classification by SID if there is one, otherwise by name (case-insensitive):

| Kind | By SID | By name (fallback) |
|---|---|---|
| `local_system` | `S-1-5-18` | `SYSTEM`, `LocalSystem`, `NT AUTHORITY\SYSTEM` |
| `local_service` | `S-1-5-19` | `LOCAL SERVICE`, `LocalService`, `NT AUTHORITY\LocalService` / `Local Service` |
| `network_service` | `S-1-5-20` | `NETWORK SERVICE`, `NetworkService`, `NT AUTHORITY\...` |
| `virtual` | `S-1-5-80-*` | `NT SERVICE\*` |
| `group` | `S-1-5-32-*`, `S-1-1-0`, `S-1-5-4`, `S-1-5-6`, `S-1-5-11`, `S-1-2-*`; or any task without user but with a group | `BUILTIN\*`, `NT AUTHORITY\INTERACTIVE` / `Authenticated Users` / `SERVICE`, `Everyone`, `Users`, `Administrators` |
| `no_account` | — | neither user nor group |
| `local_user` | `S-1-5-21-*` with machine SID prefix | `.\name`, `<computer>\name` |
| `managed` | domain SID, name ends with `$` | `DOMAIN\name$` |
| `domain` | other `S-1-5-21-*` | `DOMAIN\name`, `name@domain` |
| `unknown` | anything else | anything else, also a plain name without domain |

A domain group (task with only a domain group `GroupId`) is `group` as well.

### Parameters

| Parameter | Effect | Default |
|---|---|---|
| `builtin_kinds` | Kinds that are unremarkable; tasks under them are not reported | `local_system`, `local_service`, `network_service`, `virtual`, `no_account`, `group` |
| `ignored_paths` | Regexes (fullmatch, ignore case) on the task identity `\path\name`; matching tasks are left out of check, baseline and change detection | `\\Microsoft\\.*` |
| `logon_types` | Only tasks with these logon types are evaluated | all |
| `ignore_disabled` | Do not evaluate tasks in state `Disabled` | off |
| `allowed` | Allow list: `{"account": <regex>, "task": <regex, optional>}` | empty |
| `allowed_additional` | Merges with the allow list of a more general rule | empty |
| `not_allowed_state` | State for every reported account not on the allow list | WARN (also check default) |
| `forbidden` | Unwanted accounts: regex + state, first match wins | empty |
| `changes` | States for `added`, `changed`, `removed` since the discovery | not set |
| `query_error_state` | State if the plugin reported an error | UNKNOWN |

Account patterns: fullmatch, ignore case, `$HOSTNAME$` placeholder, tried
against the name, the SID, and for `.\x` also `<computer>\x`; plus the other
spellings of the same SID and the SID remembered by the discovery. The task
pattern is matched against the task identity. An invalid pattern yields an
UNKNOWN result naming the pattern.

Ignored paths and the logon type filter only narrow what is evaluated; the
default `\Microsoft\` exclusion can be removed by setting an empty list.

### Changes since the discovery

The discovery stores `discovered_tasks`: task identity -> `{"account":
<name>, "sid": <SID or "">}` for every task with a user or group (also
built-in ones, so a switch from SYSTEM to a user is `changed`). The discovery
gets no check parameters, so it stores every task with a principal, also
those under `\Microsoft\` (as the reference stores every service); the check
applies `ignored_paths`, `logon_types` and `ignore_disabled` to both sides
when comparing. Comparison logic as in the
reference (SID if both sides have one, else name ignoring case; limited to
tasks whose old or new account is reported; allowed accounts may be added
without notice). The rule form ignores `discovered_tasks`
(`ignored_elements`). No baseline during a plugin error; with `changes` but
without baseline the summary says so.

### Output

- Summary: `5 tasks under 3 accounts`, then at most 10 findings worst first,
  rest counted ("3 more findings (see details)").
- Details: one line per reported task:
  `\Backup\Nightly: CONTOSO\svc_backup (domain account), Password, Highest, Ready[: <reason>]`.
- Metrics without levels: `task_account_tasks` (tasks under reported
  accounts), `task_account_accounts` (distinct reported accounts). One graph,
  one perfometer.

## Inventory

Table `software > os > windows_task_accounts`, titled `Windows Task
Accounts`, one row per task not under a built-in kind and not under
`\Microsoft\` (the defaults). Inventory rule `windows_task_accounts_inventory`
with `all_tasks`: list every task.

- Key column: `task` (identity `\path\name`).
- Inventory columns: `account`, `kind`, `logon_type`, `run_level`.
- Status column: `state`.
- View `invtaskaccounts` for cross-host searches.

## Tests

- pytest: parser (empty fields, error line, SID as user id), classification
  incl. `group`, every parameter (`ignored_paths`, `logon_types`, allow list,
  forbidden, changes), inventory rows, building all rule forms, bakery output,
  graphing objects.
- Dev site: test host with canned output in `temp/`.
- The PowerShell script is verified by the user on real Windows hosts
  (German and English OS, domain member, DC, task with a deleted account).

Test data uses fictional names only (CONTOSO, SRV-APP01, round SIDs).

## Not in scope

- Last run time / result of tasks, task actions, author.
- COM fallback for systems without `Get-ScheduledTask`.
- Whether an account is privileged.
- One service per task or per account.

## Amendments from the implementation

1. Logon types are the names `Get-ScheduledTask` reports (`Password`, `S4U`, `Interactive`, `InteractiveOrPassword`, `ServiceAccount`, `Group`, `None`), not the task XML names (`InteractiveToken`). The rule option `logon_types` stores them in lower case; the form prefills `password` (the usual use: alert only on stored passwords), absent option = all.
2. A baseline entry of a task without user carries `"group": True`, so a domain group in the baseline is classified as `group`, as in the current data.
3. Kind `group` by SID: `S-1-5-32-*`, `S-1-2-*`, `S-1-1-0`, `S-1-5-4`, `S-1-5-6`, `S-1-5-11`; by name: `BUILTIN\*`, `Users`, `Administrators`, `Everyone`, `INTERACTIVE`, `Authenticated Users`, `NT AUTHORITY\INTERACTIVE` / `Authenticated Users` / `SERVICE`.
4. Ignored paths are removed from the baseline before the comparison, so a removed or changed task under `\Microsoft\` is never reported unless the rule evaluates that folder.
5. The inventory applies the default built-in kinds and the default ignored path unless `all_tasks` is set.
6. An invalid ignored-path pattern yields an UNKNOWN result like any other invalid pattern.
7. The baseline entries also carry `logon_type` and, for disabled tasks, `disabled: true`. The check applies `logon_types` and `ignore_disabled` to the baseline as well (entries without a logon type are still evaluated), so a removed task that was never evaluated is not reported.
8. One unreadable task does not wipe out the section: the agent prints all readable tasks and one `error|` line per enumeration error; the parser joins all error lines with `; `. With tasks and an error the discovery stores the baseline and the check evaluates the tasks and reports added/changed, but not removed tasks while the error lasts. With an error and no tasks only the error result is shown.
