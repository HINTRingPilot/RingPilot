param([string]$Compiler = 'g++')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$outputDir = Join-Path $projectRoot '.build/transport-tests'
$libraryDir = Join-Path $projectRoot 'firmware/libraries/RingPilotTransport/src'
New-Item -ItemType Directory -Force $outputDir | Out-Null
$executable = Join-Path $outputDir 'transport_state_test.exe'
& $Compiler -std=c++11 -O2 -Wall -Wextra -Werror "-I$(Join-Path $PSScriptRoot 'stubs')" "-I$libraryDir" (Join-Path $libraryDir 'RingPilotTransport.cpp') (Join-Path $PSScriptRoot 'transport_state_test.cpp') -o $executable
if ($LASTEXITCODE -ne 0) { throw 'Transport test compilation failed.' }
& $executable
if ($LASTEXITCODE -ne 0) { throw 'Transport tests failed.' }
