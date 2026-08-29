# Agent2Learn installer for Windows.
#
# It installs one pinned Agent2Learn release with uv, verifies the command, and — only in an
# interactive console — hands straight to interactive onboarding. Onboarding is what asks before
# writing anything: this script never creates a vault, an agent skills directory, or a browser
# profile, and it never needs administrator rights.
#
# Everything it installs is pinned in the constants block below. There is deliberately no parameter
# for pointing it at another package, index, or URL.
#
# PATH is left to uv: `uv tool update-shell` writes the user PATH entry and broadcasts the change
# itself, so this script adds no custom Win32 broadcasting and assumes no fixed directory.

$ErrorActionPreference = "Stop"

# ---- reviewed constants ---------------------------------------------------------------
$UV_VERSION = "0.12.5"
$A2L_VERSION = "0.1.0"
# ---------------------------------------------------------------------------------------

$UV_INSTALLER = "https://astral.sh/uv/$UV_VERSION/install.ps1"

function Get-UvVersion {
    try {
        $raw = (& uv --version) 2>$null | Out-String
    } catch {
        return $null
    }
    if ($raw -match 'uv\s+([0-9]+(?:\.[0-9]+)*)') {
        return [string]$Matches[1]
    }
    return ""
}

function Test-VersionAtLeast {
    param([string] $Have, [string] $Want)

    $haveParts = $Have.Split('.')
    $wantParts = $Want.Split('.')
    for ($index = 0; $index -lt 3; $index++) {
        $haveValue = 0
        $wantValue = 0
        if ($index -lt $haveParts.Length) { $haveValue = [int] $haveParts[$index] }
        if ($index -lt $wantParts.Length) { $wantValue = [int] $wantParts[$index] }
        if ($haveValue -gt $wantValue) { return $true }
        if ($haveValue -lt $wantValue) { return $false }
    }
    return $true
}

$existing = $null
$needsUv = $true
if (Get-Command uv -ErrorAction SilentlyContinue) {
    $existing = Get-UvVersion
    if ([string]::IsNullOrEmpty($existing)) {
        Write-Error @"
found uv but could not read its version.
Install the tested version yourself, then rerun this installer:
  powershell -ExecutionPolicy ByPass -c "irm $UV_INSTALLER | iex"
"@
        exit 1
    }
    if (Test-VersionAtLeast -Have $existing -Want $UV_VERSION) {
        $needsUv = $false
    }
}

Write-Output "Agent2Learn installer"
Write-Output ""
Write-Output "This will:"
if ($needsUv) {
    if ($existing) {
        Write-Output "  - replace uv $existing with the tested uv $UV_VERSION from $UV_INSTALLER"
    } else {
        Write-Output "  - install uv $UV_VERSION from $UV_INSTALLER"
    }
} else {
    Write-Output "  - reuse the uv $existing already on your PATH"
}
Write-Output "  - install agent2learn==$A2L_VERSION as a uv tool"
Write-Output "  - let uv add its tool directory to your user PATH"
Write-Output "  - verify that a2l runs"
Write-Output ""
Write-Output "It does not create a vault, install agent skills, open a browser, or need admin rights."
Write-Output ""

if ($needsUv) {
    Invoke-RestMethod $UV_INSTALLER | Invoke-Expression
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv is still not on PATH after installation"
    exit 1
}

Write-Output "installing agent2learn==$A2L_VERSION"
& uv tool install "agent2learn==$A2L_VERSION"
try { & uv tool update-shell } catch { }

$toolBin = (& uv tool dir --bin | Out-String).Trim()
if ([string]::IsNullOrEmpty($toolBin)) {
    Write-Error "uv did not report its tool executable directory"
    exit 1
}
$env:PATH = "$toolBin;$env:PATH"

$reported = (& a2l --version | Out-String).Trim()
if ([string]::IsNullOrEmpty($reported)) {
    Write-Error "a2l did not run after installation"
    exit 1
}
if ($reported -notlike "*$A2L_VERSION*") {
    Write-Error "expected agent2learn $A2L_VERSION but a2l reported: $reported"
    exit 1
}
Write-Output "verified: $reported"
Write-Output ""
Write-Output "A terminal that was already open before this install may still need to be reopened"
Write-Output "before it can find a2l, because uv updates the PATH for new sessions."
Write-Output ""

$interactive = [Environment]::UserInteractive -and -not [Console]::IsInputRedirected
if ($interactive) {
    Write-Output "starting setup; it will preview and ask before writing anything"
    & a2l init
} else {
    Write-Output "Installed. Onboarding is interactive, so finish it yourself:"
    Write-Output "run in a terminal: a2l init"
}
