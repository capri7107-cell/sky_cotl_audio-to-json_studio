param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("install", "test", "lint", "types", "all")]
    [string]$Task,
    [switch]$Fix
)

$ErrorActionPreference = "Stop"
$python = "D:\My Folder\Environment\pytorch-env\Scripts\python.exe"
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Required Python interpreter was not found: $python"
}

function Invoke-PythonModule {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE."
    }
}

$ruffArguments = @("-m", "ruff", "check")
if ($Fix) {
    $ruffArguments += "--fix"
}
$ruffArguments += "."

switch ($Task) {
    "install" {
        Invoke-PythonModule @("-m", "pip", "install", "-r", "requirements-core.txt")
        Invoke-PythonModule @("-m", "pip", "install", "-r", "requirements-dev.txt")
        Invoke-PythonModule @("-m", "pip", "check")
    }
    "test" {
        Invoke-PythonModule @("-m", "pytest", "-q")
    }
    "lint" {
        Invoke-PythonModule $ruffArguments
    }
    "types" {
        Invoke-PythonModule @("-m", "mypy", "src")
    }
    "all" {
        Invoke-PythonModule @("-m", "pytest", "-q")
        Invoke-PythonModule $ruffArguments
        Invoke-PythonModule @("-m", "mypy", "src")
    }
}
