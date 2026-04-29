# One-click setup: creates GitHub repo, uploads code, configures secrets, kicks off the workflow.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Yad2 Cloud Monitor - GitHub Actions setup" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Auth
Write-Host "`n[1/6] Checking GitHub login..." -ForegroundColor Yellow
gh auth status 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Need to log in to GitHub. Browser will open..." -ForegroundColor Yellow
    gh auth login --web --scopes "repo,workflow"
}
$user = gh api user --jq .login
Write-Host "Logged in as: $user" -ForegroundColor Green

# 2. Init git repo
Write-Host "`n[2/6] Initializing git repo..." -ForegroundColor Yellow
if (-not (Test-Path ".git")) {
    git init -b main | Out-Null
    git config user.name $user
    git config user.email "$user@users.noreply.github.com"
}
git add . | Out-Null
git commit -m "initial commit" --allow-empty 2>$null | Out-Null

# 3. Create remote repo (private by default)
Write-Host "`n[3/6] Creating GitHub repo..." -ForegroundColor Yellow
$repoName = "yad2-cloud-monitor"
$existing = gh repo view "$user/$repoName" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Repo $user/$repoName already exists" -ForegroundColor Green
} else {
    gh repo create $repoName --private --source=. --push --description "Yad2 Prius monitor running on GitHub Actions" | Out-Null
    Write-Host "Created $user/$repoName" -ForegroundColor Green
}

# 4. Push if not already
Write-Host "`n[4/6] Pushing code..." -ForegroundColor Yellow
git remote remove origin 2>$null
git remote add origin "https://github.com/$user/$repoName.git" 2>$null
git push -u origin main --force

# 5. Set secrets
Write-Host "`n[5/6] Configuring secrets..." -ForegroundColor Yellow
"54d979bae7cc435ab73ea9149630a93a1d764c389151479d88" | gh secret set API_TOKEN --repo "$user/$repoName"
"7103103506" | gh secret set ID_INSTANCE --repo "$user/$repoName"
"972526940950" | gh secret set PHONE_TO_NOTIFY --repo "$user/$repoName"
Write-Host "Secrets set" -ForegroundColor Green

# 6. Trigger first run
Write-Host "`n[6/6] Triggering first run..." -ForegroundColor Yellow
Start-Sleep -Seconds 3
gh workflow run check.yml --repo "$user/$repoName"
Start-Sleep -Seconds 5
Write-Host "`nDone!" -ForegroundColor Green
Write-Host ""
Write-Host "Your monitor: https://github.com/$user/$repoName" -ForegroundColor Cyan
Write-Host "Live runs:    https://github.com/$user/$repoName/actions" -ForegroundColor Cyan
Write-Host ""
Write-Host "It will scan automatically every 10 minutes, 24/7, even with the computer off." -ForegroundColor Green
Write-Host "First WhatsApp message will arrive within ~2-3 minutes once the workflow finishes its first run." -ForegroundColor Green
