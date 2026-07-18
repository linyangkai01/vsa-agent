# Frontend quality fixer report

## Status

`DONE_WITH_CONCERNS`

## Root-cause findings

- `dashboard/__tests__/DashboardComponent.test.tsx` is a tracked baseline test from `a15922c`, but it was missing the closing `describe` brace. Dashboard ESLint and Prettier both reported a parse error at line 71.
- Dashboard's Jest config/test dependencies are not declared in the dashboard workspace. A direct dashboard Jest run therefore reports that `jest-environment-jsdom` cannot be found. No manifest dependency change was committed because the local Node 24/npm 12 install could not produce a compatible lock update without a large unrelated lockfile rewrite; the package should be completed with the repository's Node 22/npm 10 toolchain.
- `SearchHeader.tsx` contained two unescaped JSX quotes at the tooltip text, reported as `react/no-unescaped-entities` errors.
- `Home.tsx` fallback components were named in the existing change, but the changed JSX indentation did not match the file's formatter. The fallback blocks were minimally indented; the file still has pre-existing formatting debt when checked as a whole.
- Root `npm run lint` remains red only in the unrelated `apps/nemo-agent-toolkit-ui/pages/_document.tsx` (`@next/no-sync-scripts`). It was not changed.

## Changes

- Added the missing closing `});` to the dashboard test.
- Escaped the SearchHeader tooltip quotes as `&quot;`.
- Corrected indentation in the six named Home fallback components.

## Verification

- Dashboard ESLint after fix: `0 errors, 1 existing warning` (the parse error is gone).
- Search ESLint after fix: `0 errors, 3 existing warnings` (the two quote errors are gone).
- VSS app lint: `0 errors, 5 existing warnings`.
- Task22 fixtures/spec Prettier: passed before this probe; Home remains affected by baseline formatter debt.
- Dashboard Jest RED was reproduced before the manifest attempt: missing `jest-environment-jsdom`; after the syntax fix it could not be rerun because npm12 left the local node_modules incomplete. No NODE_PATH or global package workaround was used.

## Concerns

- Complete dashboard Jest enablement requires adding test-only workspace devDependencies and lock entries using the repository's supported Node 22/npm 10 toolchain, then running the dashboard test script.
- `frontend/original-ui/package-lock.json` was restored to the pre-task ESLint diff (`41 additions/38 deletions`) after an npm12 lockfile rewrite was discarded.
