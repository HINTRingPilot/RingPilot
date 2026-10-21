# RingPilot 개발환경 일괄 설치 (Windows 10/11, winget 필요)
# 사용: PowerShell에서  .\setup.ps1            (전체)
#       .\setup.ps1 -SkipAndroid               (Android Studio/adb 제외)
# 이미 설치된 항목은 건너뛴다. 버전 근거는 requirements.txt와 docs/설치안내.md.

param([switch]$SkipAndroid)

$ErrorActionPreference = 'Stop'

$BoardIndexUrl = 'https://files.seeedstudio.com/arduino/package_seeeduino_boards_index.json'
$BoardCore     = 'Seeeduino:nrf52@1.1.13'   # non-mbed 코어
$ImuLibrary    = 'Seeed Arduino LSM6DS3@2.0.7'

function Has($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Install-Winget($id, $label) {
    Write-Host "==> $label ($id)"
    $listed = winget list --id $id --exact --accept-source-agreements 2>$null | Select-String $id
    if ($listed) { Write-Host '    이미 설치됨'; return }
    winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { Write-Warning "$label 설치 실패 (종료 코드 $LASTEXITCODE)" }
}

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

if (-not (Has 'winget')) {
    throw 'winget이 없습니다. Microsoft Store에서 "앱 설치 관리자"를 업데이트한 뒤 다시 실행하세요.'
}

# 1) 프로그램 설치
Install-Winget 'Arduino.ArduinoIDE'  'Arduino IDE'
Install-Winget 'ArduinoSA.CLI'       'arduino-cli'
Install-Winget 'OpenJS.NodeJS'       'Node.js (npm 포함)'
if (-not $SkipAndroid) {
    Install-Winget 'Google.AndroidStudio' 'Android Studio'
    Install-Winget 'Google.PlatformTools' 'Android Platform-Tools (adb)'
}
Refresh-Path

# 2) 보드 코어 + 라이브러리
if (Has 'arduino-cli') {
    Write-Host "==> Arduino 보드 코어 $BoardCore"
    arduino-cli config init --overwrite 2>$null | Out-Null
    arduino-cli config add board_manager.additional_urls $BoardIndexUrl
    arduino-cli core update-index
    arduino-cli core install $BoardCore
    Write-Host "==> 라이브러리 $ImuLibrary"
    arduino-cli lib install $ImuLibrary
} else {
    Write-Warning 'arduino-cli를 찾지 못했습니다. 새 PowerShell 창을 열고 다시 실행하세요.'
}

Write-Host ''
Write-Host '완료. 수동으로 남은 것:'
Write-Host ' - Android Studio를 한 번 실행해 SDK Manager에서 Platform 35, Build-Tools 36.0.0, Platform-Tools 설치'
Write-Host ' - 휴대폰: 개발자 옵션 > USB 디버깅, 앱 설치 후 접근성 > RingPilot 스와이프 사용'
