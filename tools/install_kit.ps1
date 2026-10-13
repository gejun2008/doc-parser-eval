# Copy benchmark-kit into the ocr-benchmark-dataset repository (step 1 of docs/working/copilot-prompt-install-kit.md).
# Pure file copy: no installs, no tests, no commit. ASCII only so Windows PowerShell 5.1 reads it correctly.
#
# Usage (run from anywhere; the kit source is the folder this script was unzipped with):
#   powershell -ExecutionPolicy Bypass -File <unzipped>\tools\install_kit.ps1 -DS D:\work\ocr-benchmark-dataset
# Then review the printed git status and commit yourself.
param(
    [Parameter(Mandatory = $true)][string]$DS,          # ocr-benchmark-dataset repository root
    [string]$Branch = "add-eval-kit"
)
$ErrorActionPreference = "Stop"
$KIT = Join-Path (Split-Path -Parent $PSScriptRoot) "benchmark-kit"
if (-not (Test-Path "$KIT\eval\__main__.py")) { throw "benchmark-kit not found at $KIT" }
if (-not (Test-Path "$DS\.git")) { throw "$DS is not a git repository" }
Set-Location $DS

# 1. branch (create, or switch if it already exists)
git show-ref --verify --quiet "refs/heads/$Branch"
if ($LASTEXITCODE -eq 0) { git switch $Branch } else { git switch -c $Branch }

# 2. data/, gt/, metadata/ must be untouched
$dirty = git status --short -- data gt metadata
if ($dirty) {
    Write-Host "data/ gt/ metadata/ have changes (not made by this script):" -ForegroundColor Red
    $dirty | Select-Object -First 20 | ForEach-Object { Write-Host "  $_" }
    throw "Restore them first: git restore -- data gt metadata  (and git clean -n -- data gt metadata)"
}

# 3. copy kit files
Copy-Item -Recurse -Force "$KIT\eval" $DS
New-Item -ItemType Directory -Force "$DS\.github\skills\ocr-benchmark", "$DS\docs" | Out-Null
Copy-Item -Force "$KIT\.github\skills\ocr-benchmark\SKILL.md" "$DS\.github\skills\ocr-benchmark\"
Copy-Item -Force "$KIT\docs\protocol.md" "$DS\docs\"
if (-not (Test-Path "$DS\docs\README-previous.md")) {
    Copy-Item -Force "$DS\README.md" "$DS\docs\README-previous.md"   # keep the old README verbatim
}
Copy-Item -Force "$KIT\README.md" "$DS\README.md"

# 4. .gitignore: append kit lines that are not there yet
if (-not (Test-Path "$DS\.gitignore")) { New-Item -ItemType File "$DS\.gitignore" | Out-Null }
$have = Get-Content "$DS\.gitignore"
Get-Content "$KIT\.gitignore" | Where-Object { $_ -and ($have -notcontains $_) } | Add-Content "$DS\.gitignore"

# 5. show what will be committed
git add -A
Write-Host "`nStaged changes (expect only eval/, .github/, docs/, README.md, .gitignore):" -ForegroundColor Cyan
git status --short | Select-Object -First 40
$other = git status --short | Where-Object { $_ -notmatch '\s(eval/|\.github/|docs/|README\.md|\.gitignore)' }
if ($other) {
    Write-Host "`nUnexpected paths staged - check before committing:" -ForegroundColor Yellow
    $other | ForEach-Object { Write-Host "  $_" }
}
Write-Host "`nIf the list looks right:  git commit -m `"Add evaluation kit: scorers, protocol, Copilot skill`"" -ForegroundColor Green
