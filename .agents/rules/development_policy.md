# JobPilot Auto-Execution Rule

---
description: Automatically execute routine development commands without prompting for permission
trigger: always_on
---

## Autonomous Command Execution & Self-Healing Policy

The user has explicitly pre-approved ALL routine development, operational, testing, debugging, and service commands.

### Mandates:
1. **Zero Conversational Permission Requests**: Never ask "May I run this?", "Would you like me to proceed?", "Should I execute this?", or pause to request approval for routine development actions. Proactively trigger tools and commands immediately.
2. **Autonomous End-to-End Troubleshooting**: When a command, test, or operation fails, analyze the error, debug, apply the fix, and re-run automatically. Continue through the complete lifecycle until the issue is verified and resolved.
3. **Pre-Approved Actions**:
   - File creation, modification, refactoring, and code inspection.
   - Package management (`pip`, `npm`, virtualenv).
   - Test execution (`pytest`, Playwright scripts, curl checks).
   - Process inspection, port diagnostics, server startup, and restarts (`start.ps1`, `uvicorn`, background tasks).
4. **Escalate Only Genuine Decisions**:
   - Stop to ask only if an ambiguous business/design decision requires human choice, unversioned credentials/secrets are needed, or an action is irrecoverably destructive (e.g. deleting directories outside the workspace or forced git resets).
