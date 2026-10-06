@echo off
setlocal

set "EI_FORWARDER=%APPDATA%\npm\edge-impulse-data-forwarder.cmd"

if not exist "%EI_FORWARDER%" (
  echo Edge Impulse CLI was not found at:
  echo   %EI_FORWARDER%
  echo Install it with: npm.cmd install --global edge-impulse-cli
  exit /b 1
)

call "%EI_FORWARDER%" --frequency 100 %*
