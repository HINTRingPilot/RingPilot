param([string]$JavaHome = $env:JAVA_HOME)
$ErrorActionPreference = 'Stop'
if (!$JavaHome) { throw 'Set JAVA_HOME or pass -JavaHome (JDK 17 or newer).' }
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
$out = Join-Path $root '.build/android-sidecar-tests'
New-Item -ItemType Directory -Force $out | Out-Null
& (Join-Path $JavaHome 'bin/javac.exe') --release 17 -encoding UTF-8 -d $out (Join-Path $root 'android/app/src/main/java/com/hintringpilot/ringpilot/dev/CaptureSidecar.java') (Join-Path $root 'android/tests/CaptureSidecarTest.java')
if ($LASTEXITCODE -ne 0) { throw 'Sidecar test compilation failed.' }
& (Join-Path $JavaHome 'bin/java.exe') -cp $out com.hintringpilot.ringpilot.dev.CaptureSidecarTest
if ($LASTEXITCODE -ne 0) { throw 'Sidecar tests failed.' }
& (Join-Path $JavaHome 'bin/javac.exe') --release 17 -encoding UTF-8 -d $out (Join-Path $root 'android/app/src/main/java/com/hintringpilot/ringpilot/GestureRouter.java') (Join-Path $root 'android/tests/GestureRouterTest.java')
if ($LASTEXITCODE -ne 0) { throw 'Gesture router test compilation failed.' }
& (Join-Path $JavaHome 'bin/java.exe') -cp $out com.hintringpilot.ringpilot.GestureRouterTest
if ($LASTEXITCODE -ne 0) { throw 'Gesture router tests failed.' }
$sources = @('CaptureSidecar', 'CaptureCoordinator', 'SessionDirectory', 'SlotContinuity') | ForEach-Object {
    Join-Path $root "android/app/src/main/java/com/hintringpilot/ringpilot/dev/$_.java"
}
$sources += Join-Path $root 'android/tests/CaptureCoordinatorTest.java'
& (Join-Path $JavaHome 'bin/javac.exe') --release 17 -encoding UTF-8 -d $out @sources
if ($LASTEXITCODE -ne 0) { throw 'Capture coordinator test compilation failed.' }
& (Join-Path $JavaHome 'bin/java.exe') "-Djava.io.tmpdir=$out" -cp $out com.hintringpilot.ringpilot.dev.CaptureCoordinatorTest
if ($LASTEXITCODE -ne 0) { throw 'Capture coordinator tests failed.' }
& (Join-Path $JavaHome 'bin/javac.exe') --release 17 -encoding UTF-8 -d $out (Join-Path $root 'android/app/src/main/java/com/hintringpilot/ringpilot/BleConnectionEpoch.java') (Join-Path $root 'android/tests/BleConnectionEpochTest.java')
if ($LASTEXITCODE -ne 0) { throw 'Connection epoch test compilation failed.' }
& (Join-Path $JavaHome 'bin/java.exe') -cp $out com.hintringpilot.ringpilot.BleConnectionEpochTest
if ($LASTEXITCODE -ne 0) { throw 'Connection epoch tests failed.' }

