# Copyright (C) 2026 Andre Eckstein - License: GNU General Public License v3
# This file is part of the Checkmk plugin windows_task_accounts. It is subject to the
# terms and conditions defined in the file LICENSE in the root of the repository.
# SPDX-License-Identifier: GPL-3.0-only

<#
.SYNOPSIS
    Checkmk agent plugin: Windows scheduled tasks and the accounts they run under.
.DESCRIPTION
    Prints every scheduled task, unfiltered. The evaluation (which accounts are
    reported, which are allowed, which task folders are ignored) happens on the
    Checkmk server in the check plugin windows_task_accounts, so the plugin
    needs no configuration.

    <<<windows_task_accounts:sep(124)>>>
    computer|<computer name>|<machine SID>
    task|<path>|<name>|<user id>|<user SID>|<group id>|<group SID>|<logon type>|<run level>|<state>
    unreadable|<path>|<name>|<message>
    error|<message>

    A task that cannot be read (typically: registered in the task cache in the
    registry, but its task file is missing) does not stop the listing. If
    Get-ScheduledTask reports errors, the plugin lists the registered tasks
    from the registry, reads them folder by folder, and in a folder that fails
    task by task, and prints an unreadable line for every task it cannot read.
    If even the registry cannot be read, it prints the tasks it got and one
    error line per problem.

    Keep this file ASCII only: Windows PowerShell 5.1 reads scripts without a
    BOM in the ANSI code page.
#>

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$script:SidCache = @{}
$script:TaskCacheTree = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Schedule\TaskCache\Tree'

function Format-Field {
    # Pipes and line breaks would break the section format.
    param($Value)
    if ($null -eq $Value) { return '' }
    return (([string]$Value) -replace '[|\r\n]+', ' ').Trim()
}

function Get-MachineSid {
    # The SID prefix shared by the local accounts of this computer. A domain
    # controller has no local accounts: the query would walk the directory and
    # return the domain SID, so the field stays empty there.
    try {
        $role = (Get-CimInstance -ClassName Win32_ComputerSystem -Property DomainRole).DomainRole
        if ($role -ge 4) { return '' }
        $account = Get-CimInstance -ClassName Win32_UserAccount -Filter 'LocalAccount=True' |
            Select-Object -First 1
        if ($account) {
            $sid = New-Object System.Security.Principal.SecurityIdentifier($account.SID)
            return $sid.AccountDomainSid.Value
        }
    } catch {
        # Leave the field empty: the check then falls back to the account name.
    }
    return ''
}

function Resolve-Principal {
    # Returns @(<name>, <SID>). A principal given as SID string is translated
    # to a name, a name to a SID. A side that cannot be translated (deleted
    # account, domain not reachable) keeps what the task has: the SID as name,
    # or an empty SID.
    param([string]$Principal)
    if ([string]::IsNullOrEmpty($Principal)) { return @('', '') }
    $key = $Principal.ToLowerInvariant()
    if ($script:SidCache.ContainsKey($key)) { return $script:SidCache[$key] }

    $result = @($Principal, '')
    if ($Principal -match '^S-1-\d+(-\d+)+$') {
        $result = @($Principal, $Principal.ToUpperInvariant())
        try {
            $sid = New-Object System.Security.Principal.SecurityIdentifier($Principal)
            $result[0] = $sid.Translate([System.Security.Principal.NTAccount]).Value
        } catch {
            # Keep the SID as name.
        }
    } else {
        $name = $Principal
        if ($name.StartsWith('.\')) { $name = $env:COMPUTERNAME + $name.Substring(1) }
        try {
            $ntAccount = New-Object System.Security.Principal.NTAccount($name)
            $result[1] = $ntAccount.Translate([System.Security.Principal.SecurityIdentifier]).Value
        } catch {
            # Leave the SID empty: the check then classifies by name.
        }
    }
    $script:SidCache[$key] = $result
    return $result
}

function Write-TaskLine {
    param($Task)
    $principal = $Task.Principal
    $user = Resolve-Principal (Format-Field $principal.UserId)
    $group = Resolve-Principal (Format-Field $principal.GroupId)
    $fields = @(
        'task',
        (Format-Field $Task.TaskPath),
        (Format-Field $Task.TaskName),
        (Format-Field $user[0]),
        $user[1],
        (Format-Field $group[0]),
        $group[1],
        (Format-Field $principal.LogonType),
        (Format-Field $principal.RunLevel),
        (Format-Field $Task.State)
    )
    Write-Host ($fields -join '|')
}

function Get-RegisteredTasks {
    # The folders and tasks registered in the task cache, as a hashtable
    # '\Folder\' -> list of task names. A key with the value Id is a task, any
    # other key a folder.
    $folders = @{}
    $folders['\'] = New-Object System.Collections.ArrayList
    $pending = New-Object System.Collections.Stack
    $pending.Push(@((Get-Item -LiteralPath $script:TaskCacheTree), '\'))
    while ($pending.Count -gt 0) {
        $key, $path = $pending.Pop()
        foreach ($child in (Get-ChildItem -LiteralPath $key.PSPath)) {
            if ($null -ne $child.GetValue('Id')) {
                [void]$folders[$path].Add($child.PSChildName)
            } else {
                $childPath = $path + $child.PSChildName + '\'
                $folders[$childPath] = New-Object System.Collections.ArrayList
                $pending.Push(@($child, $childPath))
            }
        }
    }
    return $folders
}

function Write-TasksOneByOne {
    # Reads the tasks of a folder one at a time, so that a broken task only
    # costs its own line. Exact comparison instead of escaping: TaskPath and
    # TaskName are wildcard patterns.
    param([string]$Path, $Names)
    foreach ($name in ($Names | Sort-Object)) {
        $taskError = $null
        $found = @(Get-ScheduledTask -TaskPath $Path -TaskName $name `
                -ErrorAction SilentlyContinue -ErrorVariable taskError |
            Where-Object { $_.TaskPath -eq $Path -and $_.TaskName -eq $name })
        if ($found.Count -gt 0) {
            Write-TaskLine $found[0]
            continue
        }
        $message = 'not found'
        if ($taskError) { $message = $taskError[0].Exception.Message }
        $file = Join-Path $env:windir ('System32\Tasks' + $Path + $name)
        if (-not (Test-Path -LiteralPath $file)) {
            $message = 'registered, but the task file is missing (' + $message + ')'
        }
        $fields = @('unreadable', (Format-Field $Path), (Format-Field $name), (Format-Field $message))
        Write-Host ($fields -join '|')
    }
}

Write-Host '<<<windows_task_accounts:sep(124)>>>'
Write-Host ('computer|{0}|{1}' -f (Format-Field $env:COMPUTERNAME), (Get-MachineSid))

try {
    if (-not (Get-Command -Name Get-ScheduledTask -ErrorAction SilentlyContinue)) {
        throw 'Get-ScheduledTask is not available (Windows 8 / Server 2012 or later required)'
    }
    $taskErrors = $null
    $tasks = @(Get-ScheduledTask -ErrorAction SilentlyContinue -ErrorVariable taskErrors)
    $registered = $null
    if ($taskErrors) {
        try {
            $registered = Get-RegisteredTasks
        } catch {
            $registered = $null
        }
    }
    if ($null -eq $registered) {
        foreach ($task in ($tasks | Sort-Object -Property TaskPath, TaskName)) {
            Write-TaskLine $task
        }
        foreach ($taskError in $taskErrors) {
            Write-Host ('error|' + (Format-Field $taskError.Exception.Message))
        }
    } else {
        foreach ($path in ($registered.Keys | Sort-Object)) {
            $names = $registered[$path]
            if ($names.Count -eq 0) { continue }
            $folderErrors = $null
            $folderTasks = @(Get-ScheduledTask -TaskPath $path `
                    -ErrorAction SilentlyContinue -ErrorVariable folderErrors |
                Where-Object { $_.TaskPath -eq $path })
            if ($folderErrors) {
                Write-TasksOneByOne $path $names
            } else {
                foreach ($task in ($folderTasks | Sort-Object -Property TaskName)) {
                    Write-TaskLine $task
                }
            }
        }
    }
} catch {
    Write-Host ('error|' + (Format-Field $_.Exception.Message))
}
