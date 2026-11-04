param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("install", "test", "test-gpu", "lint", "types", "all", "convert", "compare", "mp3", "app", "fidelity")]
    [string]$Task,
    [Parameter(Position = 1)]
    [string]$InputPath,
    [Parameter(Position = 2)]
    [string]$OutputPath,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArguments,
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

function Invoke-PythonScript {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $srcPath = Join-Path (Get-Location) "src"
    if ($env:PYTHONPATH) {
        $env:PYTHONPATH = "$srcPath;$env:PYTHONPATH"
    }
    else {
        $env:PYTHONPATH = $srcPath
    }

    & $python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python script failed with exit code $LASTEXITCODE."
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
        $testArguments = @("-m", "pytest", "-q")
        if ($InputPath) {
            $testArguments += $InputPath
        }
        if ($ExtraArguments) {
            $testArguments += $ExtraArguments
        }
        Invoke-PythonModule $testArguments
    }
    "test-gpu" {
        Invoke-PythonModule @("-m", "pytest", "-q", "-m", "gpu")
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
    "convert" {
        if (-not $InputPath -or -not $OutputPath) {
            throw "convert requires an input MIDI path and an output JSON path."
        }
        $convertArguments = @("scripts/convert_midi.py", $InputPath, $OutputPath)
        if ($ExtraArguments) {
            $convertArguments += $ExtraArguments
        }
        Invoke-PythonScript $convertArguments
    }
    "compare" {
        $compareArguments = @("tools/compare.py")
        if ($ExtraArguments) {
            $compareArguments += $ExtraArguments
        }
        Invoke-PythonScript $compareArguments
    }
    "fidelity" {
        Invoke-PythonScript @("tools/fidelity.py")
    }
    "mp3" {
        if (-not $InputPath -or -not $OutputPath) {
            throw "mp3 requires an input MP3 path and an output JSON path."
        }
        $mp3Arguments = @("scripts/mp3_to_json.py", $InputPath, $OutputPath)
        if ($ExtraArguments) {
            $mp3Arguments += $ExtraArguments
        }
        Invoke-PythonScript $mp3Arguments
    }
    "app" {
        Invoke-PythonScript @("-m", "sky_cotl_studio.gui.app")
    }
}
