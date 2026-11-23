param(
    [string]$Agents = "auto",
    [ValidateSet("link", "copy")]
    [string]$Mode = "link",
    [string]$Project = "",
    [switch]$ListTargets,
    [switch]$Force,
    [switch]$DryRun
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ArgsList = @("$ScriptDir\install.py")

if ($ListTargets) {
    $ArgsList += "--list-targets"
} else {
    $ArgsList += @("--agents", $Agents, "--mode", $Mode)
    if ($Project) { $ArgsList += @("--project", $Project) }
    if ($Force) { $ArgsList += "--force" }
    if ($DryRun) { $ArgsList += "--dry-run" }
}

python @ArgsList
exit $LASTEXITCODE
