$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TempRoot = Join-Path $RootDir "temp"
$RunTempRoot = Join-Path $TempRoot ("run-" + (Get-Date -Format "yyyyMMdd-HHmmss") + "-" + $PID)
$LegacyBuildRoot = Join-Path $RootDir "build_release"
$LogPath = Join-Path $RootDir "build_release.log"
$NuitkaOut = Join-Path $RunTempRoot "nuitka"
$PortableRoot = Join-Path $RootDir "portable"
$ReleaseDir = Join-Path $PortableRoot "SemiUtilsQt"
$ZipPath = Join-Path $PortableRoot "SemiUtilsQt-windows.zip"
$CondaEnvName = "semi-utils"
$AppExeName = "SemiUtilsQt.exe"
$ConsoleMode = if ($env:BUILD_CONSOLE -eq "1") { "force" } else { "disable" }
$PushdDone = $false
$FinalExitCode = 1
$OldTemp = $env:TEMP
$OldTmp = $env:TMP
$OldNuitkaCacheDir = $env:NUITKA_CACHE_DIR
$OldPath = $env:PATH

function Write-Log {
    param([string]$Message = "")
    Write-Host $Message
    Add-Content -LiteralPath $LogPath -Value $Message -Encoding UTF8
}

function Remove-PathIfExists {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        $lastError = $null
        for ($attempt = 1; $attempt -le 3; $attempt++) {
            try {
                Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
                return
            }
            catch {
                $lastError = $_
                Start-Sleep -Milliseconds 500
            }
        }
        throw $lastError
    }
}

function Run-Command {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    $quotedArgs = $Arguments | ForEach-Object {
        if ($_ -match '\s') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }
    Add-Content -LiteralPath $LogPath -Value ("[CMD] {0} {1}" -f $FilePath, ($quotedArgs -join " ")) -Encoding UTF8
    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $FilePath @Arguments 2>&1 | ForEach-Object {
            Add-Content -LiteralPath $LogPath -Value ([string]$_) -Encoding UTF8
        }
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }
    if ($exitCode -ne 0) {
        throw "Command failed with exit code ${exitCode}: $FilePath $($Arguments -join ' ')"
    }
}

function Select-Python {
    if ($env:BUILD_PYTHON) {
        if (Test-Path -LiteralPath $env:BUILD_PYTHON) {
            return @($env:BUILD_PYTHON, "BUILD_PYTHON")
        }
        throw "BUILD_PYTHON is set but the file does not exist: $env:BUILD_PYTHON"
    }

    if ($env:CONDA_PREFIX) {
        $activeCondaPython = Join-Path $env:CONDA_PREFIX "python.exe"
        if (Test-Path -LiteralPath $activeCondaPython) {
            $source = if ($env:CONDA_DEFAULT_ENV) { "active conda env $env:CONDA_DEFAULT_ENV" } else { "active conda env" }
            return @($activeCondaPython, $source)
        }
    }

    $conda = Get-Command conda -ErrorAction SilentlyContinue
    if ($conda) {
        try {
            $condaInfo = & $conda.Source env list --json 2>$null | ConvertFrom-Json
            $match = $condaInfo.envs | Where-Object { (Split-Path -Leaf $_).ToLowerInvariant() -eq $CondaEnvName.ToLowerInvariant() } | Select-Object -First 1
            if ($match) {
                $python = Join-Path $match "python.exe"
                if (Test-Path -LiteralPath $python) {
                    return @($python, "conda env $CondaEnvName")
                }
            }
        }
        catch {
            Add-Content -LiteralPath $LogPath -Value ("[WARN] Failed to query conda env list: " + $_.Exception.Message) -Encoding UTF8
        }
    }

    $knownRoots = @(
        (Join-Path $env:USERPROFILE "anaconda3"),
        (Join-Path $env:USERPROFILE "miniconda3"),
        (Join-Path $env:USERPROFILE "miniforge3")
    )
    foreach ($knownRoot in $knownRoots) {
        $python = Join-Path $knownRoot "envs\$CondaEnvName\python.exe"
        if (Test-Path -LiteralPath $python) {
            return @($python, "conda env $CondaEnvName under $(Split-Path -Leaf $knownRoot)")
        }
    }

    if ($env:VIRTUAL_ENV) {
        $venvPython = Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"
        if (Test-Path -LiteralPath $venvPython) {
            return @($venvPython, "active VIRTUAL_ENV")
        }
    }

    $localVenvPython = Join-Path $RootDir ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $localVenvPython) {
        return @($localVenvPython, "qt_gui\.venv")
    }

    throw "No usable Python executable was selected. Activate conda env '$CondaEnvName' or set BUILD_PYTHON."
}

function Find-VsDevCmd {
    $knownPaths = @(
        "D:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat",
        "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat",
        "C:\Program Files\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat"
    )
    foreach ($path in $knownPaths) {
        if (Test-Path -LiteralPath $path) {
            return $path
        }
    }

    $vswhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path -LiteralPath $vswhere) {
        $installPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
        if ($installPath) {
            $candidate = Join-Path $installPath "Common7\Tools\VsDevCmd.bat"
            if (Test-Path -LiteralPath $candidate) {
                return $candidate
            }
        }
    }

    return $null
}

function Import-VsDevEnvironment {
    param([string]$VsDevCmd)

    Write-Log "[INFO] Loading Visual Studio build environment: $VsDevCmd"
    $envDump = & cmd.exe /s /c "`"$VsDevCmd`" -arch=x64 -host_arch=x64 >nul && set"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to initialize Visual Studio build environment."
    }
    foreach ($line in $envDump) {
        $separator = $line.IndexOf("=")
        if ($separator -gt 0) {
            $name = $line.Substring(0, $separator)
            $value = $line.Substring($separator + 1)
            Set-Item -LiteralPath "Env:$name" -Value $value
        }
    }
}

function Copy-CondaRuntimeDlls {
    param(
        [string]$PythonExe,
        [string]$Destination
    )

    $pythonRoot = Split-Path -Parent $PythonExe
    $libraryBin = Join-Path $pythonRoot "Library\bin"
    if (-not (Test-Path -LiteralPath $libraryBin)) {
        Write-Log "[INFO] Conda Library\bin not found; skipping conda runtime DLL copy."
        return
    }

    $dllPatterns = @(
        "pyside6*.dll",
        "shiboken6*.dll",
        "Qt6Core.dll",
        "Qt6Gui.dll",
        "Qt6Widgets.dll",
        "Qt6Network.dll",
        "Qt6Svg.dll",
        "double-conversion.dll",
        "pcre2-16.dll",
        "icu*.dll",
        "zlib.dll",
        "zlib-ng2.dll",
        "zstd.dll",
        "libzstd.dll",
        "libpng16.dll",
        "freetype.dll",
        "jpeg8.dll",
        "lcms2.dll",
        "lerc.dll",
        "libtiff.dll",
        "tiff.dll",
        "libwebp*.dll",
        "openjp2.dll",
        "deflate.dll",
        "brotli*.dll",
        "libbz2.dll",
        "libcrypto-3-x64.dll",
        "libssl-3-x64.dll",
        "libexpat.dll",
        "liblzma.dll",
        "libmpdec-4.dll",
        "libsharpyuv.dll",
        "ffi-*.dll"
    )

    $copied = @{}
    foreach ($pattern in $dllPatterns) {
        Get-ChildItem -LiteralPath $libraryBin -Filter $pattern -File -ErrorAction SilentlyContinue | ForEach-Object {
            if (-not $copied.ContainsKey($_.Name)) {
                Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $Destination $_.Name) -Force
                $copied[$_.Name] = $true
            }
        }
    }

    foreach ($packageDirName in @("PySide6", "shiboken6")) {
        $packageDir = Join-Path $Destination $packageDirName
        if (-not (Test-Path -LiteralPath $packageDir)) {
            continue
        }
        foreach ($dllName in @("pyside6*.dll", "shiboken6*.dll")) {
            Get-ChildItem -LiteralPath $Destination -Filter $dllName -File -ErrorAction SilentlyContinue | ForEach-Object {
                Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $packageDir $_.Name) -Force
            }
        }
    }

    Write-Log "[INFO] Copied $($copied.Count) conda runtime DLL(s) from: $libraryBin"
}

try {
    New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
    Set-Content -LiteralPath $LogPath -Value "" -Encoding UTF8

    Write-Log "[1/7] Root directory: $RootDir"
    Push-Location $RootDir
    $PushdDone = $true

    Write-Log "[INFO] Cleaning previous release output and temporary files..."
    Remove-PathIfExists $PortableRoot
    try {
        Remove-PathIfExists $TempRoot
    }
    catch {
        Write-Log ("[WARN] Previous temp folder could not be fully removed and will be retried at the end: " + $_.Exception.Message)
    }
    Remove-PathIfExists $LegacyBuildRoot
    Remove-PathIfExists (Join-Path $RootDir "semi_utils_qt_gui.egg-info")
    Remove-PathIfExists (Join-Path $RootDir "__pycache__")
    Remove-PathIfExists (Join-Path $RootDir "entity\__pycache__")
    Remove-PathIfExists (Join-Path $RootDir "enums\__pycache__")
    New-Item -ItemType Directory -Path $RunTempRoot -Force | Out-Null

    $ToolTemp = Join-Path $RunTempRoot "tool-temp"
    New-Item -ItemType Directory -Path $ToolTemp -Force | Out-Null
    $env:TEMP = $ToolTemp
    $env:TMP = $ToolTemp
    $env:NUITKA_CACHE_DIR = Join-Path $RunTempRoot "nuitka-cache"
    New-Item -ItemType Directory -Path $env:NUITKA_CACHE_DIR -Force | Out-Null

    foreach ($required in @("main_gui.py", "pyproject.toml", "config.yaml")) {
        if (-not (Test-Path -LiteralPath (Join-Path $RootDir $required))) {
            throw "$required not found in root directory."
        }
    }

    $env:PYTHONPATH = "$RootDir;$env:PYTHONPATH"

    Write-Log "[2/7] Selecting Python environment..."
    $pythonSelection = Select-Python
    $Py = $pythonSelection[0]
    $PySource = $pythonSelection[1]
    Write-Log "[INFO] Python source: $PySource"
    Write-Log "[INFO] Python executable: $Py"

    Write-Log "[3/7] Installing build dependencies..."
    $dependencyCheck = "import importlib.util, sys; modules=['nuitka','ordered_set','zstandard','PIL','yaml','dateutil','requests','PySide6']; missing=[m for m in modules if importlib.util.find_spec(m) is None]; print('Missing:', ', '.join(missing) if missing else 'none'); sys.exit(1 if missing else 0)"
    try {
        Run-Command $Py @("-c", $dependencyCheck)
    }
    catch {
        Write-Log "[WARN] Some dependencies are missing; installing them with pip."
        Run-Command $Py @("-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools")
        Run-Command $Py @(
            "-m", "pip", "install",
            "nuitka",
            "ordered-set",
            "zstandard",
            "pillow>=10.3.0",
            "pyyaml>=6.0.1",
            "python-dateutil>=2.8.2",
            "requests>=2.31.0",
            "PySide6>=6.8.1"
        )
    }
    Run-Command $Py @("-c", "import sys; print('Python:', sys.version); print('Executable:', sys.executable); from PySide6.QtCore import qVersion; print('PySide6 Qt:', qVersion())")

    Write-Log "[4/7] Verifying config.yaml has no local absolute paths..."
    Run-Command $Py @("-c", "from pathlib import Path; import re, sys; p=Path('config.yaml'); bad=[line for line in p.read_text(encoding='utf-8').splitlines() if re.search(r'[A-Za-z]:[\\/]', line)]; print('\n'.join(bad)); sys.exit(1 if bad else 0)")

    Write-Log "[5/7] Cleaning previous build output..."
    Remove-PathIfExists $NuitkaOut
    New-Item -ItemType Directory -Path $NuitkaOut -Force | Out-Null

    Write-Log "[6/7] Building portable standalone release with Nuitka..."
    Write-Log "[INFO] Release mode: standalone folder with $AppExeName. This keeps startup faster than one-file extraction."
    Write-Log "[INFO] Windows console mode: $ConsoleMode"
    $pythonDir = Split-Path -Parent $Py
    $pythonScriptsDir = Join-Path $pythonDir "Scripts"
    $env:PATH = "$pythonDir;$pythonScriptsDir;$env:PATH"
    $vsDevCmd = Find-VsDevCmd
    if ($vsDevCmd) {
        Import-VsDevEnvironment $vsDevCmd
    }
    else {
        Write-Log "[WARN] Visual Studio build environment was not found. Nuitka may fail if no compiler is available."
    }
    Run-Command $Py @(
        "-m", "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        "--enable-plugin=pyside6",
        "--windows-console-mode=$ConsoleMode",
        "--windows-icon-from-ico=logo.ico",
        "--output-dir=$NuitkaOut",
        "--output-filename=$AppExeName",
        "--include-data-file=config.yaml=config.yaml",
        "--include-data-file=example.jpg=example.jpg",
        "--include-data-file=logo.ico=logo.ico",
        "--include-data-dir=logos=logos",
        "--include-data-dir=exiftool=exiftool",
        "--include-data-file=fonts\Roboto-Regular.ttf=fonts\Roboto-Regular.ttf",
        "--include-data-file=fonts\Roboto-Bold.ttf=fonts\Roboto-Bold.ttf",
        "--include-data-file=fonts\Roboto-Light.ttf=fonts\Roboto-Light.ttf",
        "--include-data-file=fonts\Roboto-Medium.ttf=fonts\Roboto-Medium.ttf",
        "--nofollow-import-to=tkinter",
        "--nofollow-import-to=matplotlib",
        "--nofollow-import-to=numpy",
        "main_gui.py"
    )

    $DistDir = Join-Path $NuitkaOut "main_gui.dist"
    if (-not (Test-Path -LiteralPath $DistDir)) {
        $DistDir = Join-Path $NuitkaOut "SemiUtilsQt.dist"
    }
    if (-not (Test-Path -LiteralPath $DistDir)) {
        throw "Nuitka dist folder not found. Checked: $(Join-Path $NuitkaOut 'main_gui.dist') and $(Join-Path $NuitkaOut 'SemiUtilsQt.dist')"
    }
    Write-Log "[INFO] Nuitka dist folder: $DistDir"

    Write-Log "[7/7] Preparing release folder and zip..."
    New-Item -ItemType Directory -Path $PortableRoot -Force | Out-Null
    Copy-Item -LiteralPath $DistDir -Destination $ReleaseDir -Recurse -Force
    Copy-Item -LiteralPath "config.yaml" -Destination (Join-Path $ReleaseDir "config.yaml") -Force
    Copy-Item -LiteralPath "exiftool" -Destination (Join-Path $ReleaseDir "exiftool") -Recurse -Force
    Copy-Item -LiteralPath "fonts" -Destination (Join-Path $ReleaseDir "fonts") -Recurse -Force
    Copy-Item -LiteralPath "logos" -Destination (Join-Path $ReleaseDir "logos") -Recurse -Force
    Copy-CondaRuntimeDlls $Py $ReleaseDir
    New-Item -ItemType Directory -Path (Join-Path $ReleaseDir "output") -Force | Out-Null

    foreach ($required in @(
        $AppExeName,
        "config.yaml",
        "exiftool\exiftool.exe",
        "PySide6\qt-plugins\platforms\qwindows.dll",
        "Qt6Core.dll",
        "Qt6Gui.dll",
        "Qt6Widgets.dll"
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $ReleaseDir $required))) {
            throw "$required missing from release folder."
        }
    }
    foreach ($requiredPattern in @("pyside6*.dll", "shiboken6*.dll")) {
        if (-not (Get-ChildItem -LiteralPath $ReleaseDir -Filter $requiredPattern -File -ErrorAction SilentlyContinue | Select-Object -First 1)) {
            throw "$requiredPattern missing from release folder."
        }
    }

    $RunWithLog = @"
@echo off
cd /d "%~dp0"
set QT_DEBUG_PLUGINS=1
echo Starting SemiUtilsQt.exe...
echo Working directory: %CD%
$AppExeName > runtime.log 2>&1
echo Exit code: %ERRORLEVEL% >> runtime.log
type runtime.log
pause
"@
    Set-Content -LiteralPath (Join-Path $ReleaseDir "run_with_log.bat") -Value $RunWithLog -Encoding ASCII

    Write-Log "[CMD] powershell Compress-Archive"
    if (Test-Path -LiteralPath $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }
    Compress-Archive -LiteralPath $ReleaseDir -DestinationPath $ZipPath -CompressionLevel Optimal -Force

    Write-Log ""
    Write-Log "[OK] Fast-start portable exe:"
    Write-Log "     $(Join-Path $ReleaseDir $AppExeName)"
    Write-Log "[OK] Portable release folder:"
    Write-Log "     $ReleaseDir"
    Write-Log "[OK] Shareable zip:"
    Write-Log "     $ZipPath"
    Write-Log "[OK] Full build log:"
    Write-Log "     $LogPath"
    Write-Log ""
    Write-Log "Test by extracting the zip to another folder and running SemiUtilsQt.exe."
    $FinalExitCode = 0
}
catch {
    Write-Host ""
    Write-Host "[FAILED] Release build did not complete."
    Write-Host "[FAILED] Full details are in:"
    Write-Host "         $LogPath"
    Add-Content -LiteralPath $LogPath -Value "" -Encoding UTF8
    Add-Content -LiteralPath $LogPath -Value "[FAILED] Release build did not complete." -Encoding UTF8
    Add-Content -LiteralPath $LogPath -Value ("[ERROR] " + $_.Exception.Message) -Encoding UTF8
    Add-Content -LiteralPath $LogPath -Value ($_.ScriptStackTrace) -Encoding UTF8
    $FinalExitCode = 1
}
finally {
    $env:TEMP = $OldTemp
    $env:TMP = $OldTmp
    $env:NUITKA_CACHE_DIR = $OldNuitkaCacheDir
    $env:PATH = $OldPath
    if ($PushdDone) {
        Pop-Location
    }
    try {
        Remove-PathIfExists $RunTempRoot
        Remove-PathIfExists $TempRoot
        Remove-PathIfExists $LegacyBuildRoot
        Remove-PathIfExists (Join-Path $RootDir "semi_utils_qt_gui.egg-info")
        Remove-PathIfExists (Join-Path $RootDir "__pycache__")
        Remove-PathIfExists (Join-Path $RootDir "entity\__pycache__")
        Remove-PathIfExists (Join-Path $RootDir "enums\__pycache__")
    }
    catch {
        Add-Content -LiteralPath $LogPath -Value ("[WARN] Cleanup failed: " + $_.Exception.Message) -Encoding UTF8
    }
}

exit $FinalExitCode
