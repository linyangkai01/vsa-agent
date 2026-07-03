# Project Agent Instructions

## Development Workflow

- All project-development work MUST be managed through the `comet` skill workflow, including Git branch handling, implementation planning, verification, archiving, and development-document updates.
- Git development is local-first for this single-developer project:
  - Use local temporary development branches or worktrees as needed.
  - Choose branches by default for ordinary single-threaded changes because they are lighter and easier to clean up.
  - Choose worktrees when parallel development is actually useful, such as keeping a stable `master` runtime while testing a feature branch, comparing two implementations side by side, or preserving a long-running experiment without blocking the main workspace.
  - Avoid creating extra branches or worktrees when a small documentation, configuration, or prompt tweak can be completed safely on the current clean `master`.
  - When a change is complete, merge it back into local `master`.
  - Push `master` to the remote repository.
  - Do not use remote feature branches or Pull Requests as the normal completion path.
  - Remote repository state should normally contain only `master`.
- If local code changes are intended to run on a project server, and the project documentation or current task explicitly identifies that server as the validation environment, sync the updated code to the server and run the required server-side validation before marking the work complete.

## End-Of-Turn Reporting

- Every final response MUST include a concise next-step suggestion.
- If the current work is blocked by a Comet decision point, the next-step suggestion MUST name the exact decision needed.

## Documentation Hygiene

- Keep active development status easy to find in `docs/DEVELOPMENT_STATUS.md`.
- Use OpenSpec `openspec/specs/` for current accepted capability requirements.
- Use OpenSpec archives for completed changes.
- Avoid leaving stale plan/design/status documents that make it unclear what is active.
