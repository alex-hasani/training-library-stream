[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$allowlistPath = Join-Path $root '.public-allowlist'

$allowlist = @(
    Get-Content -LiteralPath $allowlistPath | ForEach-Object { $_.Trim() } |
        Where-Object { $_ -and -not $_.StartsWith('#') }
)
$tracked = @(& git -C $root ls-files)

$unexpected = @($tracked | Where-Object { $_ -notin $allowlist })
if ($unexpected) {
    throw "Public release contains unallowlisted files:`n$($unexpected -join "`n")"
}

$forbidden = @($tracked | Where-Object {
    $_ -match '^(app-data|cache|data|media|libraries|courses|course-library|transcodes)/' -or
    $_ -match '\.(mkv|mp4|avi|mov|wmv|webm|m4v|mp3|flac|wav|aac|m4a|ogg|jpg|jpeg|png|gif|bmp|webp|heic|pdf|docx?|xlsx?|pptx?|db|sqlite|sqlite3|zip|7z|rar)$'
})
if ($forbidden) {
    throw "Public release contains prohibited content:`n$($forbidden -join "`n")"
}

$scanFiles = @($tracked | Where-Object { $_ -notin @('web/hls.min.js', 'tools/verify-public-release.ps1') } | ForEach-Object { Join-Path $root $_ })
$patterns = @(
    'home-pc',
    'tail[0-9a-z]{6,}',
    '[A-Z]:\\',
    'C:\\Users',
    'password\s*=',
    '(api[_-]?key|token)\s*=',
    'ghp_',
    'github_pat_'
)
$matches = @(Select-String -LiteralPath $scanFiles -Pattern $patterns -CaseSensitive:$false)
if ($matches) {
    $details = $matches | ForEach-Object { "$($_.Path):$($_.LineNumber): $($_.Line.Trim())" }
    throw "Public release contains private deployment or credential indicators:`n$($details -join "`n")"
}

Write-Output "Public release scan passed: $($tracked.Count) allowlisted files; no prohibited content detected."
