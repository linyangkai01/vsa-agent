# Project Agent Instructions

## Development Workflow

- Git development is local-first for this single-developer project:
  - Use local temporary development branches or worktrees as needed.
  - Choose branches by default for ordinary single-threaded changes because they are lighter and easier to clean up.
  - Choose worktrees when parallel development is actually useful, such as keeping a stable `master` runtime while testing a feature branch, comparing two implementations side by side, or preserving a long-running experiment without blocking the main workspace.
  - Avoid creating extra branches or worktrees when a small documentation, configuration, or prompt tweak can be completed safely on the current clean `master`.
  - When a change is complete, merge it back into local `master`.
  - Push `master` to the remote repository.
  - Do not use remote feature branches or Pull Requests as the normal completion path.
  - Remote repository state should normally contain only `master`.
- Parallel development should be used only when work is genuinely independent:
  - Keep the main session responsible for coordination, integration, verification, Git cleanup, and final merge back to local `master`.
  - Do not create unrelated parallel branches, worktrees, or agent sessions.
- If local code changes are intended to run on a project server, and the project documentation or current task explicitly identifies that server as the validation environment, sync the updated code to the server and run the required server-side validation before marking the work complete.
- The mapped server project at `Z:\vsa-agent` is an explicitly approved write/sync target for this project. When the runtime sandbox allows access to that path, agents may write updated project files there for server sync without asking for separate per-command approval.
- If sandbox permissions are downgraded later, `Z:\vsa-agent` still needs to be included by the host runtime as a writable root. This instruction records project approval but cannot by itself expand the Codex filesystem sandbox.

## End-Of-Turn Reporting

- Every final response MUST include a concise next-step suggestion.

## Documentation Hygiene

- Keep active development status easy to find in `docs/DEVELOPMENT_STATUS.md`.
- Keep accepted capability requirements under `docs/specs/`.
- Keep durable design, runtime, and validation documentation under `docs/` with descriptive names.
- Do not add Comet, Superpowers, OpenSpec workflow metadata, or skill lock files unless the user explicitly re-enables those workflows.
- Avoid leaving stale plan/design/status documents that make it unclear what is active.
