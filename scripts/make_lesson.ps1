<#
.SYNOPSIS
One command from an expert take to a reviewed, voiced lesson (Windows PowerShell 5.1 or 7).

.DESCRIPTION
New lesson (from the repo root):
  scripts\make_lesson.ps1 -Video takes\fold2.mov -Id fortune-teller-v2 -Title "Fold a fortune teller" `
      -Template lessons\templates\fortune-teller.steps.json

  1. server.teach: normalize, find steps with Claude from the frames (plus local Whisper narration when the
     take has speech; the template's step list is a strong prior when given), cut clips, pick reference
     frames, rewrite titles and check questions from each step's frames (--retitle), self-test; every step
     that fails the self-test becomes manual (--strict-self-test).
  2. scripts\contact_sheet.py --lesson: lessons\<id>\review\sheet.jpg, one row per step (first, middle,
     reference, last frame) to judge the cut points.
  3. server.voice --mode auto: narration replaces the take's audio when it has no usable speech, else is
     mixed over it. Skipped with -NoVoice.
  4. scripts\lesson_lint.py, then the step table.

-Boundaries vision|legacy: vision cuts each step right after the model sees it DONE (pass 1 on contact sheets of
the whole take, pass 2 at 0.25 s around each cut; log in review/boundaries.json, cut strips on the sheet). It is the
default with -NoSpeech; with -Recut it only re-picks reference frames at the human-edited cuts.

Add -NoSpeech for a silent or near-silent take: Whisper is skipped (on room noise it invents lines that would
steer the steps and fill the captions), so Claude sees the frames only.

After looking at the sheet, edit "start"/"end" (and titles) in lessons\<id>\lesson.json, then:
  scripts\make_lesson.ps1 -Id fortune-teller-v2 -Recut

-Recut rebuilds from the edited lesson.json: recut, every reference frame chosen again (-KeepRefTimes keeps
ref_time values that still fall inside their step, for hand-set ones), questions from the new frames
(-Retitle also rewrites titles), self-test, sheet, voiceover, lint, table.

Lessons go to $env:HANDOVER_LESSONS, else <repo>\lessons. A new build never overwrites an existing id.
Exit code: 0 done, 1 a stage failed or lint reported FAIL, 2 bad arguments.
#>
[CmdletBinding()]
param(
    [string]$Video,
    [Parameter(Mandatory = $true)][string]$Id,
    [string]$Title,
    [string]$Template,
    [switch]$NoVoice,
    [switch]$NoSpeech,
    [ValidateSet('', 'vision', 'legacy')][string]$Boundaries = '',
    [switch]$Recut,
    [switch]$Retitle,
    [switch]$KeepRefTimes
)

# Continue, not Stop: Windows PowerShell 5.1 turns any stderr line of a native command (python logging) into a
# terminating error when output is redirected. Failures are caught from $LASTEXITCODE instead.
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Py = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Py)) { $Py = Join-Path $Root '.venv/bin/python' }
if (-not (Test-Path $Py)) { $Py = 'python' }

function Step([string]$text) { Write-Host ''; Write-Host "== $text" -ForegroundColor Cyan }
function Fail([string]$text, [int]$code = 1) { Write-Host "error: $text" -ForegroundColor Red; exit $code }
function Run([string]$what) {
    # runs the python command in $args; stops the script when it fails
    & $Py @args
    if ($LASTEXITCODE -ne 0) { Fail "$what failed (exit $LASTEXITCODE)" }
}

# Same cleaning as server.teach.sanitize_id, so the folder is known up front.
$Clean = ($Id.ToLower() -replace '[^a-z0-9-]+', '-') -replace '-{2,}', '-'
$Clean = $Clean.Trim('-')
if ($Clean -notmatch '^[a-z0-9][a-z0-9_-]{0,63}$') { Fail "lesson id '$Id' is not usable; use letters, digits and dashes" 2 }
if ($Clean -ne $Id) { Write-Host "note: lesson id cleaned to '$Clean'" }

$Lessons = if ($env:HANDOVER_LESSONS) { $env:HANDOVER_LESSONS } else { Join-Path $Root 'lessons' }
$Dir = Join-Path $Lessons $Clean
# Steps come from Claude: frames only, plus the local Whisper transcript when the take has speech.
if (-not $env:HANDOVER_TEACH_PROVIDER) { $env:HANDOVER_TEACH_PROVIDER = 'claude' }
# -NoSpeech: the take is silent. Skips Whisper, which turns room noise into made-up lines ("it's like triangle")
# that would steer the step boundaries and end up in the captions.
if ($NoSpeech) { $env:HANDOVER_TRANSCRIBE = 'off' }
# Boundaries: vision (the model finds when each step is DONE, two calls, HANDOVER_TEACH_BOUNDARY_MODEL) is the
# default for -NoSpeech takes and for a -Recut of a lesson built that way; legacy is the one-call extraction.
if (-not $Boundaries) {
    if ($Recut) { $Boundaries = if (Test-Path (Join-Path $Dir 'review/boundaries.json')) { 'vision' } else { 'legacy' } }
    else { $Boundaries = if ($NoSpeech) { 'vision' } else { 'legacy' } }
}
Write-Host "boundaries: $Boundaries"

$t0 = Get-Date

if ($Recut) {
    if (-not (Test-Path (Join-Path $Dir 'lesson.json'))) { Fail "no lesson.json in $Dir; build it first without -Recut" 2 }
    if ($Video -or $Template) { Write-Host 'note: -Recut uses the times in lesson.json; -Video and -Template are ignored' }
    Step "Recut $Dir from lesson.json"
    $recutArgs = @('-m', 'server.teach', '--recut', $Dir, '--strict-self-test', '--boundaries', $Boundaries)
    if (-not $KeepRefTimes) { $recutArgs += '--repick' }
    if ($Retitle) { $recutArgs += '--retitle' }
    Run 'recut' @recutArgs
}
else {
    if (-not $Video) { Fail 'give -Video <take> for a new lesson (or -Recut to rebuild an existing one)' 2 }
    if (-not (Test-Path $Video -PathType Leaf)) { Fail "no such video: $Video" 2 }
    if (Test-Path $Dir) { Fail "$Dir already exists. Use -Recut to rebuild it, or pick a new -Id." 2 }
    if ($Template -and -not (Test-Path $Template -PathType Leaf)) { Fail "no such template: $Template" 2 }
    if (-not $Title) { $Title = $Clean }
    $VideoPath = (Resolve-Path $Video).Path
    Step "Build $Clean `"$Title`" from $VideoPath"
    $buildArgs = @('-m', 'server.teach', $VideoPath, '--id', $Clean, '--title', $Title, '--strict-self-test',
                   '--boundaries', $Boundaries)
    # legacy: titles and questions are rewritten from each step's frames (Haiku). vision: the boundary model already
    # wrote title, question and tip from the done frame, so only the questions are checked against the references.
    if ($Boundaries -eq 'legacy' -or $Retitle) { $buildArgs += '--retitle' }
    if ($Template) { $buildArgs += @('--prior', (Resolve-Path $Template).Path) }
    Run 'teach' @buildArgs
}

Step 'Contact sheet'
Run 'contact sheet' 'scripts/contact_sheet.py' '--lesson' $Dir

if ($NoVoice) {
    Write-Host 'voiceover skipped (-NoVoice)'
}
else {
    Step 'Voiceover'
    # auto: replace the take's audio when it has no usable speech, else mix the narration over it
    & $Py -m server.voice $Dir --mode auto
    if ($LASTEXITCODE -ne 0) { Write-Host "warning: voiceover failed (exit $LASTEXITCODE); the clips keep the take's audio" -ForegroundColor Yellow }
}

Step 'Lint'
& $Py scripts/lesson_lint.py $Dir
$lint = $LASTEXITCODE

Step 'Steps'
Run 'step table' '-m' 'server.teach' '--table' $Dir

$rel = $Dir
if ($Dir.StartsWith($Root)) { $rel = $Dir.Substring($Root.Length).TrimStart('\', '/') }
$secs = [int]((Get-Date) - $t0).TotalSeconds
Write-Host ''
Write-Host "Done in $secs s: $Dir"
Write-Host "Review the cuts:  $(Join-Path $Dir 'review\sheet.jpg')"
Write-Host "Move a boundary:  edit start/end in $rel\lesson.json, then"
Write-Host "                  scripts\make_lesson.ps1 -Id $Clean -Recut"
if ($lint -ne 0) { Fail 'lesson_lint reported FAIL; see above' }
exit 0
