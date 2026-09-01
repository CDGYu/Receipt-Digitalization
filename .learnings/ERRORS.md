# Errors

Command failures and integration errors.

---

## [ERR-20260901-001] npm-powershell-shim

**Logged**: 2026-09-01T14:29:34.8094642+08:00
**Priority**: medium
**Status**: pending
**Area**: tests

### Summary
PowerShell blocked `npm.ps1` when running frontend tests from this workspace.

### Error
```text
npm : File C:\Program Files\nodejs\npm.ps1 cannot be loaded because running scripts is disabled on this system.
```

### Context
- Command attempted: `npm test -- --run tests/image-pane.test.tsx`
- Environment: Windows PowerShell in `frontend`
- Workaround: use `npm.cmd` for Node package scripts.

### Suggested Fix
Run package scripts through `npm.cmd` in this PowerShell environment, or change the user-level execution policy outside this project.

### Metadata
- Reproducible: yes
- Related Files: frontend/package.json

---
