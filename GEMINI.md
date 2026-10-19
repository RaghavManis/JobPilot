# Antigravity Agent Guidelines: JobPilot Project

## 1. Tool Execution & Autonomous Development Policy

- **Default Preference: Auto-Execute Routine Commands**
  - Always proactively execute routine development commands without asking the user for confirmation or permission.
  - This includes:
    - File reading, inspection, editing, and creation.
    - Package management (`npm install`, `pip install`, `npm run build`).
    - Test execution (`pytest`, python test scripts, Playwright verification).
    - Port checks, process inspections, and service checks (`netstat`, `Get-Process`).
    - Server startup and background runner tasks (`start.ps1`, `uvicorn`, `serve_mock.py`).
    - Debugging, log verification, and browser automation diagnostics.
  - Do NOT pause or prompt the user with questions like "Would you like me to run this command?" or "May I proceed?". Execute immediately.
  - When an operation or test fails, analyze the error, debug, apply the necessary fix, and re-test autonomously. Drive the task to 100% completion before stopping.

## 2. Essential Safety Guardrails

- **Strict Confirmation Required For**:
  - Deleting entire project directories or non-project directories.
  - Destructive git operations (e.g., `git reset --hard`, `git clean -fd`, `git push --force`).
  - Dropping production databases or removing unversioned credentials/keys.
- All non-destructive, project-scoped changes are pre-approved.

## 3. Persistent Project Rules

- When modifying backend or frontend components, always test and verify the changes end-to-end.
- Keep the local visible browser automation (`headless=False`) functioning and responsive.
- Maintain documentation integrity and preserve existing comments.
