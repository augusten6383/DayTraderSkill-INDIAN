# Makes the slash commands (/trader-swing, /trader-risk ...) work inside this project.
#
# Each skill lives ONCE, in its trader-* folder at the project root. Claude Code looks for
# project skills under .claude\skills, so this script puts a folder link (junction) there
# for every skill, pointing back at the root folder. There are no copies to keep in step.
#
# Run it once after cloning, and again after adding a new skill folder:
#     powershell -ExecutionPolicy Bypass -File link_skills.ps1
#
# The links are not stored in git (.claude/skills/ is ignored).
# To remove a link use:  cmd /c rmdir .claude\skills\<name>
# Do NOT use Remove-Item -Recurse on a link: old PowerShell versions delete the real files.

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$links = Join-Path $root ".claude\skills"
New-Item -ItemType Directory -Force -Path $links | Out-Null

Get-ChildItem -Path $root -Directory | Where-Object { Test-Path (Join-Path $_.FullName "SKILL.md") } | ForEach-Object {
    $link = Join-Path $links $_.Name
    if (Test-Path $link) {
        $item = Get-Item $link -Force
        if ($item.LinkType -eq "Junction") {
            Write-Output ("ok       {0}" -f $_.Name)
        } else {
            Write-Output ("SKIPPED  {0}: .claude\skills\{0} is a real folder, not a link. Compare it with the root folder, delete it, then run this again." -f $_.Name)
        }
    } else {
        New-Item -ItemType Junction -Path $link -Target $_.FullName | Out-Null
        Write-Output ("linked   {0}" -f $_.Name)
    }
}
