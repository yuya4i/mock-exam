@echo off
REM ===========================================================================
REM Register a Windows Task Scheduler job that re-heals quiz-app host ports
REM after the GPU PC resumes from sleep (Docker Desktop / WSL2 drops the
REM host->container port proxy on resume; see docs/operations/remote-gpu.md).
REM
REM Trigger : Microsoft-Windows-Power-Troubleshooter EventID 1 (system resumed)
REM Action  : wsl.exe -> bash -> scripts/resume-heal.sh  (idempotent)
REM Runs    : as the interactive user (/IT), only when logged on -> no stored
REM           password; the session exists (locked) after a WoL resume.
REM
REM GPU-PC specific values — adjust if your box differs:
REM   /RU t4k1h            Windows username that owns the WSL distro
REM   -d Ubuntu            WSL distro name (wsl -l -q)
REM   -u sna               Linux user inside WSL
REM   path                 repo location inside WSL
REM
REM Run this from a normal (non-elevated) cmd: just double-click or
REM   cmd /c install-resume-task.cmd
REM Remove with:  schtasks /Delete /TN "quizgpu-resume-restart" /F
REM ===========================================================================
schtasks /Create /TN "quizgpu-resume-restart" /SC ONEVENT /EC System ^
  /MO "*[System[Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and EventID=1]]" ^
  /TR "wsl.exe -d Ubuntu -u sna -e bash -lc \"/home/sna/workspace/quiz-app/scripts/resume-heal.sh\"" ^
  /RU t4k1h /IT /RL LIMITED /F
