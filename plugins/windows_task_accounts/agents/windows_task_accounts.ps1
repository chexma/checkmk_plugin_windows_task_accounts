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
    error|<message>

    Keep this file ASCII only: Windows PowerShell 5.1 reads scripts without a
    BOM in the ANSI code page.
#>

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$script:SidCache = @{}

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

Write-Host '<<<windows_task_accounts:sep(124)>>>'
Write-Host ('computer|{0}|{1}' -f (Format-Field $env:COMPUTERNAME), (Get-MachineSid))

try {
    if (-not (Get-Command -Name Get-ScheduledTask -ErrorAction SilentlyContinue)) {
        throw 'Get-ScheduledTask is not available (Windows 8 / Server 2012 or later required)'
    }
    $tasks = Get-ScheduledTask | Sort-Object -Property TaskPath, TaskName
    foreach ($task in $tasks) {
        $principal = $task.Principal
        $user = Resolve-Principal (Format-Field $principal.UserId)
        $group = Resolve-Principal (Format-Field $principal.GroupId)
        $fields = @(
            'task',
            (Format-Field $task.TaskPath),
            (Format-Field $task.TaskName),
            (Format-Field $user[0]),
            $user[1],
            (Format-Field $group[0]),
            $group[1],
            (Format-Field $principal.LogonType),
            (Format-Field $principal.RunLevel),
            (Format-Field $task.State)
        )
        Write-Host ($fields -join '|')
    }
} catch {
    Write-Host ('error|' + (Format-Field $_.Exception.Message))
}
