# Errors

Command failures and integration errors.

---

## [ERR-20260827-004] powershell_npm_ps1_policy

**Logged**: 2026-08-27T00:00:00Z
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
PowerShell refused to run `npm` because the shim resolves to `npm.ps1` and local script execution is disabled.

### Error
```text
npm.ps1 cannot be loaded because running scripts is disabled on this system.
```

### Context
- Command attempted from `frontend/`: `npm test -- tests/image-pane.test.tsx`
- The project itself was not failing yet; Windows blocked the PowerShell launcher.

### Suggested Fix
Use `npm.cmd` from PowerShell for npm scripts in this workspace.

### Metadata
- Reproducible: yes
- Related Files: frontend/package.json

### Resolution
- **Resolved**: 2026-08-27T00:00:00Z
- **Notes**: Re-ran the command with `npm.cmd`.

---

## [ERR-20260827-005] codex_mcp_visibility_mismatch

**Logged**: 2026-08-27T00:00:00Z
**Priority**: medium
**Status**: resolved
**Area**: config

### Summary
Codex wrote valid-looking MCP tables to its global config but the same CLI does not list or retrieve them.

### Error
```text
No MCP servers configured yet.
Error: No MCP server named 'context7' found.
```

### Context
- `C:\\Users\\user\\.codex\\config.toml` contains `mcp_servers.context7`, `github`, `playwright`, and `vercel` tables.
- Codex CLI version: 0.146.0-alpha.3.

### Suggested Fix
Determine the active Codex configuration layer and whether this CLI build has an MCP command/config visibility issue before any further registration attempts.

### Metadata
- Reproducible: yes
- Related Files: C:\Users\user\.codex\config.toml

### Resolution
- **Resolved**: 2026-08-27T00:00:00Z
- **Notes**: The sandbox CLI uses `C:\\Users\\CodexSandboxOffline\\.codex`, while approved configuration writes target `C:\\Users\\user\\.codex` for the real application.

---

## [ERR-20260827-004] profile_enumeration_denied

**Logged**: 2026-08-27T00:00:00Z
**Priority**: low
**Status**: resolved
**Area**: config

### Summary
Recursive user-profile enumeration was denied by the filesystem sandbox.

### Error
```text
Access to the path 'C:\\Users\\user' is denied.
```

### Context
- Targeted reads of known Codex and Claude configuration paths remain allowed.

### Suggested Fix
Use explicit candidate paths and environment inspection instead of recursive profile scans.

### Metadata
- Reproducible: yes
- Related Files: C:\Users\user\.codex\config.toml

### Resolution
- **Resolved**: 2026-08-27T00:00:00Z
- **Notes**: Continued with targeted configuration checks only.

---

## [ERR-20260827-003] mcp_batch_timeout

**Logged**: 2026-08-27T00:00:00Z
**Priority**: low
**Status**: resolved
**Area**: config

### Summary
A batch MCP-registration command exceeded its timeout after an interactive OAuth flow.

### Error
```text
command timed out after 30455 milliseconds
```

### Context
- Context7, GitHub, Playwright, and Vercel were registered before the timeout.
- Vercel OAuth completed during registration.
- Supabase must be checked independently rather than rerunning the whole batch.

### Suggested Fix
Verify persisted MCP entries after each OAuth-capable registration and add only the missing server in a separate command.

### Metadata
- Reproducible: yes
- Related Files: C:\Users\user\.codex\config.toml

### Resolution
- **Resolved**: 2026-08-27T00:00:00Z
- **Notes**: Switched to per-server verification and registration.

---

## [ERR-20260827-002] claude_plugin_inventory

**Logged**: 2026-08-27T00:00:00Z
**Priority**: low
**Status**: resolved
**Area**: config

### Summary
The enabled-plugin inventory assumed an array but Claude stores it as an object.

### Error
```text
TypeError: (s.enabledPlugins || []).join is not a function
```

### Context
- The operation was read-only and did not expose configuration values.

### Suggested Fix
Read enabled-plugin keys with `Object.keys()` and inspect only their manifest files.

### Metadata
- Reproducible: yes
- Related Files: C:\Users\user\.claude\settings.json

### Resolution
- **Resolved**: 2026-08-27T00:00:00Z
- **Notes**: Updated the inventory approach to use object keys.

---

## [ERR-20260827-001] targeted_configuration_inventory

**Logged**: 2026-08-27T00:00:00Z
**Priority**: low
**Status**: resolved
**Area**: config

### Summary
A recursive scan of the Claude directory timed out because it included extensive conversation history.

### Error
```text
command timed out after 10359 milliseconds
```

### Context
- The scan was intended to locate configuration files.
- It traversed Claude's session-history directories, which are not part of the migration scope.

### Suggested Fix
Inspect only known Claude and Codex configuration paths and exclude session-history directories.

### Metadata
- Reproducible: yes
- Related Files: C:\Users\user\.claude

### Resolution
- **Resolved**: 2026-08-27T00:00:00Z
- **Notes**: Replaced the broad recursive scan with a targeted configuration inventory.

---

## [ERR-20260827-003] repair_comparison_cli_test

**Logged**: 2026-08-27T00:00:00Z
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
The CLI forwarding assertion omitted the ``pathlib.Path`` import.

### Error
```text
NameError: name 'Path' is not defined
```

### Context
- The failure was isolated to `tests/test_run_repair_comparison.py`.
- The comparison implementation had already completed the CLI call correctly.

### Suggested Fix
Import `Path` beside the test module's other standard-library imports.

### Metadata
- Reproducible: yes
- Related Files: tests/test_run_repair_comparison.py

### Resolution
- **Resolved**: 2026-08-27T00:00:00Z
- **Notes**: Added the missing standard-library import and reran the focused suite.

---
