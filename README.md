# Checkmk plugin: Windows Task Accounts

Shows which Windows scheduled tasks do not run under a built-in system account
(Local System, Local Service, Network Service, `NT SERVICE\...`, a group) but
under a user or service account: a domain account, a local user or a managed
service account. Optionally alerts on accounts that are not allowed, on
unwanted accounts and on changes since the service discovery.

- One service `Windows Task Accounts` per Windows host
- HW/SW inventory table with a view to search an account across all hosts
- Agent plugin `windows_task_accounts.ps1`, deployed with the agent bakery

## Requirements

- Checkmk 2.5.
- A commercial edition for the agent bakery. Without the bakery, copy
  `windows_task_accounts.ps1` to the plugin directory of the Windows agent by hand.
- Windows hosts with Windows 8 / Server 2012 or later (PowerShell 5.1 or newer,
  cmdlet `Get-ScheduledTask`).

The plugin uses the APIs `cmk.bakery.v2_unstable` and
`cmk.inventory_ui.v1_unstable`, which Checkmk declares unstable in 2.5; a later
Checkmk release may need an adapted plugin version.

## Installation

Upload the MKP in *Setup > Extension packages* and enable it, or on the command
line as site user:

```bash
mkp add windows_task_accounts-<version>.mkp
mkp enable windows_task_accounts <version>
```

## Setup

1. *Setup > Agents > Windows, Linux, Solaris, AIX > Agent rules > Windows Task
   Accounts*: create a rule with *Deploy the plugin* for the Windows hosts.
   Optionally let the plugin run asynchronously with a cache interval
   (suggested: 1 hour); useful where translating accounts takes long because a
   domain is not reachable.
2. Bake and deploy the agents.
3. Run the service discovery on the hosts. Each host gets the service
   `Windows Task Accounts`.
4. For the inventory table the HW/SW inventory has to be enabled for the hosts
   (rule *Do HW/SW inventory*).

Without a rule the service is WARN for every task that runs under a user or
service account: accounts have to be allowed explicitly (see the rule below).

## Service

Summary, for example:

```text
6 tasks under 5 accounts, .\batch: not on the allow list (1 task)(!), CONTOSO\gmsa_rep$: not on the allow list (1 task)(!), CONTOSO\old_admin: not on the allow list (1 task)(!), CONTOSO\svc_backup: not on the allow list (2 tasks)(!), svc_sync@contoso.example: not on the allow list (1 task)(!)
```

The details have one line per task with its folder and name, its account, the
kind of the account, logon type, run level and state, and the reason if the
account is not OK:

```text
\LocalJob: .\batch (local user), Password, Limited, Ready: not on the allow list
\Reports\Export: CONTOSO\gmsa_rep$ (managed service account), Password, Limited, Ready: not on the allow list
\UserLogon: CONTOSO\old_admin (domain account), Interactive, Limited, Ready: not on the allow list
\Backup\Nightly: CONTOSO\svc_backup (domain account), Password, Highest, Ready: not on the allow list
\Backup\Weekly: CONTOSO\svc_backup (domain account), Password, Limited, Disabled: not on the allow list
\Sync: svc_sync@contoso.example (domain account), S4U, Limited, Running: not on the allow list
```

At most 10 findings are named in the summary, the worst first; further ones
are counted there and listed in the details.

Metrics: number of tasks under reported accounts and number of distinct
accounts, with a graph and a perfometer.

### Account kinds

The account of a task is its user, or its group if the task runs for a group.
Every account gets a kind, by its SID if the agent could translate the
account, otherwise by its name:

| Kind | Recognised by | Built-in by default |
|---|---|---|
| Local System | `S-1-5-18`, `LocalSystem` | yes |
| Local Service | `S-1-5-19` | yes |
| Network Service | `S-1-5-20` | yes |
| Virtual account | `S-1-5-80-*`, `NT SERVICE\...` | yes |
| No account | task without user and group | yes |
| Group | task without user but with a group: `S-1-5-32-*`, `S-1-5-4`, `S-1-5-11`, ..., `Users`, `INTERACTIVE`, domain groups | yes |
| Local user | SID of the computer, `.\name`, `<computer>\name` | no |
| Managed service account | domain SID and name ends with `$` | no |
| Domain account | any other domain SID, `DOMAIN\name`, `name@domain` | no |
| Unknown | anything else | no |

Tasks under built-in kinds are not reported. Because the kind comes from the
SID, this works independently of the language of the operating system.

### Rule *Windows Task Accounts*

*Setup > Services > Service monitoring rules*. All settings are optional.

| Setting | Effect |
|---|---|
| Built-in accounts | Which kinds are unremarkable and not reported |
| Ignored tasks | Task patterns that are not evaluated at all. Default: `\\Microsoft\\.*`, the tasks of Windows itself; the list replaces this default, so add `\\Microsoft\\.*` to keep ignoring the tasks of Windows itself; an empty list evaluates them too |
| Evaluated logon types | Only tasks with these logon types are evaluated, e.g. only `Password` (Windows stores the password of the account). `S4U` stores no password, `Interactive` runs only while the user is logged on. Default: all |
| Disabled tasks | Ignore tasks in the state Disabled (by default they are evaluated: Windows keeps their credentials) |
| Allowed accounts | Which account may run which tasks: a pattern for the account and optionally one for the tasks. Without tasks the account is allowed for every task of the host. Allowed combinations are OK and exempt from the other settings |
| Additional allowed accounts | Like the allow list, but added to the list of a more general rule instead of replacing it |
| State for accounts that are not allowed | State for every task whose account is not on the allow list. Default WARN; set it to OK to only show the accounts |
| Unwanted accounts | Patterns with a state, e.g. for personal or administrator accounts; the first matching entry counts |
| Changes since the service discovery | States for added tasks, changed accounts and removed tasks |
| State if the agent plugin reported an error | Default UNKNOWN |

Patterns are regular expressions that have to match the whole account,
ignoring case. They are tried against the account name as configured in the
task and against its SID:

- A backslash is written as `\\`: `CONTOSO\\svc_.*`
- Task patterns are matched against the folder and name of the task as shown
  in the details (`\<folder>\<name>`, a task in the root folder is
  `\<name>`): `\\Backup\\Nightly` for one task, `\\Backup\\.*` for every task
  in the folder `\Backup` and its subfolders.
- `$HOSTNAME$` is replaced by the computer name: `$HOSTNAME$\\backup` matches
  the local user `backup` on every host, also if the task is configured with
  `.\backup`.
- An account configured in several spellings (`CONTOSO\svc_backup` and
  `svc_backup@contoso.example`) is matched under each of them.

A typical first rule: per-user tasks with the logon type `Interactive` (for
example `\OneDrive Reporting Task-...`) are reported by default. Restrict
*Evaluated logon types* to `Password`, or allow them with a task pattern such
as `\\OneDrive .*`.

### Changes since the service discovery

The service discovery remembers the account of every task. With the setting
*Changes since the service discovery* the check reports differences for tasks
whose old or new account is a reported account that is not on the allow list:

- a new task
- a task whose account changed, e.g. from Local System to a domain account
- a task that no longer exists

To accept a change, update the service parameters in the service discovery of
the host. Tasks without an account and ignored tasks are left out of the
comparison.

## Inventory

Table *Software > Operating system > Windows Task Accounts* with one row per
task that is reported by default (not under a built-in kind, not in
`\Microsoft`): task, account, kind, logon type, run level and state. A host
without such tasks has no table.

With the rule *Windows Task Accounts* under *Setup > Hosts > HW/SW inventory
rules* the table can list every scheduled task instead, also the ones under
built-in accounts and of Windows itself; the column *Kind* tells them apart.

The view `invtaskaccounts` *Windows Task Accounts* (search:
`invtaskaccounts_search`) finds the hosts and tasks that use an account; it
shows rows after a filter was submitted.

## Limitations

- Computer accounts (`DOMAIN\HOST$`) are shown as managed service accounts.
- An account without domain that cannot be translated to a SID is shown as
  unknown.
- On a domain controller the SID classification works as everywhere; only the
  decision between local user and domain account falls back to the account
  name, because a domain controller has no machine SID.
- If the agent plugin reports an error, the tasks it could read are still
  evaluated (and listed in the inventory), but removed tasks are not reported
  while the error lasts: an unreadable task must not look removed. Added tasks
  and changed accounts are still reported. Without any readable task only the
  error is shown.
- Not covered: services (see the plugin Windows Service Accounts), IIS
  application pools and other places that store credentials; whether an
  account is privileged; Linux.

## Agent output

```text
<<<windows_task_accounts:sep(124)>>>
computer|<computer name>|<machine SID>
task|<folder>|<name>|<user>|<user SID>|<group>|<group SID>|<logon type>|<run level>|<state>
error|<message>
```

The plugin reports every task unfiltered and has no configuration file: all
evaluation happens on the Checkmk server, so changing a rule never requires
baking agents.

## Development

Developed in a devcontainer with a Checkmk site based on
[checkmk-plugin-template](https://github.com/chexma/checkmk-plugin-template).
The development environment (devcontainer, CI, tool configuration, design
documents) is not part of this repository. The tests in `tests/` run with
the site's pytest, the plugin directory mounted as
`~/local/lib/python3/cmk_addons/plugins/windows_task_accounts`.

Changes: `Changelog.md`.

## License

GNU General Public License v3, see `LICENSE`.
