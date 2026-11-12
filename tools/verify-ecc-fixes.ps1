param(
    [Parameter(Mandatory = $true)][string]$SpaceCompilerPath,
    [string]$ArduinoCli,
    [string]$ArduinoConfig,
    [string]$OutputDirectory = '.build/ecc-fixes-validation'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$originalLocation = Get-Location
$originalTemp = $env:TEMP
$originalTmp = $env:TMP
$originalCompiler = $env:RINGPILOT_CC
$stageResults = [System.Collections.Generic.List[object]]::new()
$transcriptStarted = $false
$outputPath = $null
$primaryFailure = $null

function Invoke-CheckedStage {
    param([string]$Stage, [string]$Executable, [string[]]$Arguments = @())
    Write-Host "Running: $Stage"
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        & $Executable @Arguments
        $stageExit = [int]$LASTEXITCODE
        if ($stageExit -ne 0) { throw "$Stage failed (exit $stageExit)" }
        $stageResults.Add([pscustomobject]@{stage=$Stage; status='passed'; exit_code=$stageExit; seconds=$timer.Elapsed.TotalSeconds})
    } catch {
        $stageResults.Add([pscustomobject]@{stage=$Stage; status='failed'; error=$_.Exception.Message; seconds=$timer.Elapsed.TotalSeconds})
        throw
    }
}

try {
    Set-Location -LiteralPath $projectRoot
    $SpaceCompilerPath = (Resolve-Path -LiteralPath $SpaceCompilerPath).Path
    if (!$SpaceCompilerPath.Contains(' ')) { throw 'SpaceCompilerPath must contain a space to verify quoted-path execution.' }
    if (!$ArduinoCli) {
        $localCli = Join-Path $projectRoot '.tools/arduino-cli/arduino-cli.exe'
        $ArduinoCli = if (Test-Path -LiteralPath $localCli) { $localCli } else { (Get-Command arduino-cli -ErrorAction Stop).Source }
    }
    if (!$ArduinoConfig) {
        $localConfig = Join-Path $projectRoot '.tools/arduino-cli.yaml'
        if (Test-Path -LiteralPath $localConfig) { $ArduinoConfig = $localConfig }
    }
    $outputPath = if ([System.IO.Path]::IsPathRooted($OutputDirectory)) {
        [System.IO.Path]::GetFullPath($OutputDirectory)
    } else {
        [System.IO.Path]::GetFullPath((Join-Path $projectRoot $OutputDirectory))
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $outputPath 'tmp') | Out-Null
    $env:TEMP = Join-Path $outputPath 'tmp'
    $env:TMP = $env:TEMP
    Start-Transcript -Path (Join-Path $outputPath 'validation.log') -Force | Out-Null
    $transcriptStarted = $true
    Remove-Item Env:RINGPILOT_CC -ErrorAction SilentlyContinue

    Invoke-CheckedStage -Stage 'Java capture/router tests' -Executable '.\android\tests\run-sidecar-tests.ps1'
    Invoke-CheckedStage -Stage 'Python tests' -Executable '.\ml\.venv\Scripts\python.exe' -Arguments @('-m', 'unittest', 'discover', '-s', 'ml', '-p', 'test_*.py')
    Invoke-CheckedStage -Stage 'Firmware transport tests' -Executable '.\firmware\tests\run-transport-tests.ps1'

    $env:RINGPILOT_CC = '"' + $SpaceCompilerPath + '"'
    Invoke-CheckedStage -Stage 'Quoted compiler host C parity' -Executable '.\ml\.venv\Scripts\python.exe' -Arguments @('-m', 'unittest', 'discover', '-s', 'ml', '-p', 'test_v2_c_infer.py')
    Remove-Item Env:RINGPILOT_CC -ErrorAction SilentlyContinue

    Push-Location android
    try {
        Invoke-CheckedStage -Stage 'Android debug build' -Executable '.\gradlew.bat' -Arguments @(':app:assembleDebug', '--offline', '--console=plain')
    } finally { Pop-Location }

    $cliArguments = @()
    if ($ArduinoConfig) { $cliArguments += @('--config-file', $ArduinoConfig) }
    foreach ($sketch in @('gesture_infer', 'imu_ble_stream')) {
        $buildPath = Join-Path $outputPath $sketch
        Invoke-CheckedStage -Stage "$sketch board build" -Executable $ArduinoCli -Arguments ($cliArguments + @('compile', '--fqbn', 'Seeeduino:nrf52:xiaonRF52840Sense', '--libraries', 'firmware/libraries', '--build-path', $buildPath, "firmware/$sketch"))
    }
    Invoke-CheckedStage -Stage 'Diff whitespace' -Executable 'git' -Arguments @('diff', '--check')
    Write-Host 'All PC validation stages passed. Board/phone operation still requires a separate observation.'
} catch {
    $primaryFailure = $_
    throw
} finally {
    $cleanupError = $null
    try {
        try {
            if ($outputPath -and (Test-Path -LiteralPath $outputPath -PathType Container)) {
                ConvertTo-Json -InputObject @($stageResults.ToArray()) -Depth 4 | Set-Content -LiteralPath (Join-Path $outputPath 'stages.json') -Encoding utf8
            }
        } catch { $cleanupError = $_ }
        try {
            if ($transcriptStarted) { Stop-Transcript | Out-Null }
        } catch {
            if (!$cleanupError) { $cleanupError = $_ }
        }
    } finally {
        $env:TEMP = $originalTemp
        $env:TMP = $originalTmp
        $env:RINGPILOT_CC = $originalCompiler
        Set-Location -LiteralPath $originalLocation
    }
    if ($cleanupError) {
        if ($primaryFailure) { Write-Warning "Validation log cleanup failed: $($cleanupError.Exception.Message)" }
        else { throw $cleanupError }
    }
}
