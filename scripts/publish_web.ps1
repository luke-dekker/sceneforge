# Publish dist/web (Godot Web export of the walker) to GitHub Pages.
#
#   .\scripts\publish_web.ps1            # push build -> gh-pages, enable Pages on first run
#
# Build first (headless):
#   $g = "$env:USERPROFILE\tools\Godot\Godot_v4.7.1-stable_win64_console.exe"
#   & $g --headless --path godot --import
#   & $g --headless --path godot --export-release "Web" ../dist/web/index.html
#
# The gh-pages branch holds ONLY the build (orphan history, force-pushed each
# time); main is never touched. Site: https://luke-dekker.github.io/sceneforge/
$ErrorActionPreference = "Stop"
$repo = "luke-dekker/sceneforge"
$root = Split-Path $PSScriptRoot -Parent
$web = Join-Path $root "dist\web"
if (-not (Test-Path (Join-Path $web "index.pck"))) { throw "no build at $web - export first" }
$big = Get-ChildItem $web | Where-Object { $_.Length -gt 100MB }
if ($big) { throw "GitHub rejects files over 100 MB: $($big.Name -join ', ')" }

$stage = Join-Path $env:TEMP "sceneforge-ghpages"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory $stage | Out-Null
Copy-Item "$web\*" $stage -Recurse
New-Item -ItemType File (Join-Path $stage ".nojekyll") | Out-Null

Push-Location $stage
try {
    git init -q -b gh-pages
    git add -A
    git commit -q -m "walker web build $(Get-Date -Format s)"
    git remote add origin "https://github.com/$repo.git"
    git push --force origin gh-pages
} finally { Pop-Location }

# Enable Pages the first time (404 = not configured yet); later runs just redeploy.
$null = gh api "repos/$repo/pages" 2>$null
if ($LASTEXITCODE -ne 0) {
    gh api -X POST "repos/$repo/pages" -f "source[branch]=gh-pages" -f "source[path]=/" | Out-Null
    Write-Host "Pages enabled."
}
Write-Host "Deploying - usually live within ~1-2 min at:"
gh api "repos/$repo/pages" --jq '.html_url'
