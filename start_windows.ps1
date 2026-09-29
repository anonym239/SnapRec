<#
  SnapRec-Starter für Windows (Quellcode-Version)

  1. Sucht ein passendes Python (ab 3.9, mit Tkinter).
  2. Fehlt es: erkennt Windows-Version und Prozessor (x64 / ARM64 / 32-Bit),
     ermittelt bei python.org die neueste stabile Python-Version und installiert
     sie automatisch - ohne Admin-Rechte, nur für den aktuellen Benutzer.
  3. Legt eine eigene Umgebung (.venv) an, installiert die Pakete und startet SnapRec.

  Tipp: Die fertige SnapRec-Setup.exe braucht das alles nicht - dort ist Python schon enthalten.

  Aufruf:  start_windows.bat            (normal)
           start_windows.ps1 -DryRun    (nur anzeigen, was passieren würde)
#>
param(
    [switch]$DryRun,
    [Parameter(ValueFromRemainingArguments = $true)] $AppArgs
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
Set-Location -LiteralPath $PSScriptRoot

$MinVersion = [version]'3.9'

function Say($text, $color = 'Gray') { Write-Host "  $text" -ForegroundColor $color }

function Test-Python($exe, $extra = @()) {
    # Gibt die Version zurück, wenn Python brauchbar ist (inkl. Tkinter), sonst $null
    try {
        $out = & $exe @extra -c "import sys, tkinter; print('%d.%d.%d' % sys.version_info[:3])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) {
            $v = [version]($out | Select-Object -Last 1).Trim()
            if ($v -ge $MinVersion) { return $v }
        }
    } catch {}
    return $null
}

function Resolve-PythonExe($exe, $extra) {
    if ($exe -eq 'py') {
        return (& py -3 -c "import sys; print(sys.executable)" 2>$null | Select-Object -Last 1).Trim()
    }
    return $exe
}

function Find-Python {
    # Schnell zuerst: py-Launcher und python im PATH (Store-Platzhalter überspringen)
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $v = Test-Python 'py' @('-3')
        if ($v) { return @{ Exe = (Resolve-PythonExe 'py'); Version = $v } }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike '*\WindowsApps\*') {
        $v = Test-Python $cmd.Source @()
        if ($v) { return @{ Exe = $cmd.Source; Version = $v } }
    }
    # Dann die üblichen Installationsordner - nur direkt, ohne ganze Laufwerke zu durchsuchen
    $roots = @("$env:LOCALAPPDATA\Programs\Python\Python3*", "$env:ProgramFiles\Python3*",
               "${env:ProgramFiles(x86)}\Python3*")
    $dirs = foreach ($r in $roots) { Get-Item -Path $r -ErrorAction SilentlyContinue }
    foreach ($d in ($dirs | Sort-Object Name -Descending)) {
        $exe = Join-Path $d.FullName 'python.exe'
        if (Test-Path $exe) {
            $v = Test-Python $exe @()
            if ($v) { return @{ Exe = $exe; Version = $v } }
        }
    }
    return $null
}

function Get-Arch {
    $a = $env:PROCESSOR_ARCHITEW6432
    if (-not $a) { $a = $env:PROCESSOR_ARCHITECTURE }
    switch ($a) {
        'ARM64' { return 'arm64' }
        'AMD64' { return 'amd64' }
        default { return 'win32' }
    }
}

function Get-InstallerUrl($version, $arch) {
    $base = "https://www.python.org/ftp/python/$version"
    if ($arch -eq 'win32') { return "$base/python-$version.exe" }
    return "$base/python-$version-$arch.exe"
}

function Test-Url($url) {
    try {
        $r = Invoke-WebRequest -Uri $url -Method Head -UseBasicParsing -TimeoutSec 20
        return $r.StatusCode -eq 200
    } catch { return $false }
}

function Get-StableVersions {
    # Alle veröffentlichten, stabilen Python-3-Versionen (neueste zuerst)
    $versions = @()
    try {
        $data = Invoke-RestMethod -Uri 'https://www.python.org/api/v2/downloads/release/?is_published=true' -TimeoutSec 30
        foreach ($r in $data) {
            if (-not $r.pre_release -and $r.name -match '^Python (3\.\d+\.\d+)$') { $versions += [version]$Matches[1] }
        }
    } catch {
        Say "python.org-API nicht erreichbar, lese Download-Seite ..." 'DarkGray'
    }
    if (-not $versions) {
        $html = (Invoke-WebRequest -Uri 'https://www.python.org/downloads/windows/' -UseBasicParsing -TimeoutSec 30).Content
        foreach ($m in [regex]::Matches($html, 'Python (3\.\d+\.\d+) - ')) { $versions += [version]$m.Groups[1].Value }
    }
    return $versions | Sort-Object -Unique -Descending
}

function Select-BestPython($arch) {
    # Neueste Reihe, die schon ein Fehlerbehebungs-Update hat (x.y.1+) -
    # so gibt es sicher fertige Pakete (numpy, Pillow ...) dafür.
    $all = Get-StableVersions
    if (-not $all) { throw 'Konnte die Python-Versionen nicht von python.org laden.' }
    $series = $all | Group-Object { "$($_.Major).$($_.Minor)" } |
        Sort-Object { [version]$_.Name } -Descending
    foreach ($s in $series) {
        $newest = $s.Group | Sort-Object -Descending | Select-Object -First 1
        if ($newest.Build -lt 1) { continue }   # ganz neue Reihe (x.y.0) - noch abwarten
        foreach ($v in ($s.Group | Sort-Object -Descending)) {
            $url = Get-InstallerUrl $v $arch
            if (Test-Url $url) { return @{ Version = $v; Url = $url } }
        }
    }
    throw 'Kein passendes Python-Installationsprogramm gefunden.'
}

function Install-Python {
    $os = [Environment]::OSVersion.Version
    if ($os.Major -lt 10) { throw 'SnapRec braucht Windows 10 oder 11.' }
    $arch = Get-Arch
    Say "Windows $($os.Major) (Build $($os.Build)), Prozessor: $arch"
    Say 'Suche die neueste stabile Python-Version ...'
    $best = Select-BestPython $arch
    Say "Gewählt: Python $($best.Version)" 'Cyan'
    Say "Quelle:  $($best.Url)" 'DarkGray'
    if ($DryRun) { return $null }

    $file = Join-Path $env:TEMP "python-$($best.Version)-snaprec.exe"
    Say 'Lade herunter ...'
    Invoke-WebRequest -Uri $best.Url -OutFile $file -UseBasicParsing -TimeoutSec 600
    $sig = Get-AuthenticodeSignature -FilePath $file
    if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
        Remove-Item $file -ErrorAction SilentlyContinue
        throw 'Die heruntergeladene Datei ist nicht korrekt von der Python Software Foundation signiert - abgebrochen.'
    }
    Say 'Installiere Python (ohne Admin-Rechte, nur für diesen Benutzer) ...'
    $installArgs = @('/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1',
              'InstallLauncherAllUsers=0', 'Include_tcltk=1', 'Include_pip=1',
              'Include_test=0', 'Include_doc=0', 'Shortcuts=0')
    $p = Start-Process -FilePath $file -ArgumentList $installArgs -Wait -PassThru
    Remove-Item $file -ErrorAction SilentlyContinue
    if ($p.ExitCode -ne 0) {
        throw "Python-Installation fehlgeschlagen (Code $($p.ExitCode)). Auf Schul-PCs ist das manchmal gesperrt - nimm dann einfach die SnapRec-Setup.exe, dort ist Python schon enthalten."
    }
    return Find-Python
}

Write-Host ''
Write-Host '  SnapRec wird vorbereitet' -ForegroundColor Magenta
Write-Host ''
try {
    $py = Find-Python
    if ($py) {
        Say "Python $($py.Version) gefunden: $($py.Exe)" 'Green'
        if ($DryRun) { Say '(Probelauf: prüfe trotzdem, welche Version installiert würde)' 'DarkGray'; Install-Python | Out-Null }
    } else {
        Say 'Kein passendes Python gefunden - wird jetzt automatisch installiert.' 'Yellow'
        $py = Install-Python
        if (-not $DryRun -and -not $py) { throw 'Python wurde installiert, aber nicht gefunden. Bitte das Fenster schließen und neu starten.' }
    }
    if ($DryRun) { Say 'Probelauf beendet - nichts wurde verändert.' 'Green'; exit 0 }

    if (-not (Test-Path '.venv\Scripts\python.exe')) {
        Say 'Richte SnapRec ein (einmalig, dauert kurz) ...'
        & $py.Exe -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Konnte die Umgebung (.venv) nicht anlegen.' }
        & .venv\Scripts\python.exe -m pip install --disable-pip-version-check -q --upgrade pip
        & .venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r requirements.txt
        if ($LASTEXITCODE -ne 0) {
            Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue
            throw 'Pakete konnten nicht installiert werden (Internet/Proxy?).'
        }
    }
    Say 'Starte SnapRec ...' 'Green'
    Start-Process -FilePath '.venv\Scripts\pythonw.exe' -ArgumentList (@('-m', 'snaprec') + @($AppArgs | Where-Object { $_ }))
    exit 0
} catch {
    Write-Host ''
    Say "Fehler: $($_.Exception.Message)" 'Red'
    Say 'Alternative: SnapRec-Setup.exe von https://github.com/anonym239/SnapRec/releases (Python ist dort schon enthalten).' 'Yellow'
    exit 1
}
