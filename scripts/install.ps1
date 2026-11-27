$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot

try {
    New-Item -ItemType Directory -Force ".agents\skills", ".claude\skills" | Out-Null

    foreach ($LinkParent in @(".agents\skills", ".claude\skills")) {
        $LinkPath = Join-Path $LinkParent "coc-strategist"
        if (Test-Path $LinkPath) {
            cmd /c rmdir "$LinkPath" 2>$null
            if (Test-Path $LinkPath) {
                Remove-Item -Recurse -Force $LinkPath
            }
        }
        Push-Location $LinkParent
        try {
            # SPEC §2: Windows junction without admin; run inside parent dir so ..\..\skills\coc-strategist resolves accurately
            cmd /c mklink /J coc-strategist ..\..\skills\coc-strategist
        } finally {
            Pop-Location
        }
    }

    python -m pip install -r skills/coc-strategist/scripts/requirements.txt
} finally {
    Pop-Location
}
