## 1. Completed Baseline

- [x] 1.1 Consolidate committed runtime settings into `config.yaml`.
- [x] 1.2 Add ignored `config.local.yaml` support with deep-merge loading and redacted config print behavior.
- [x] 1.3 Remove redundant DashScope/test config files and `.env.dashscope.video*` project config.
- [x] 1.4 Make DashScope live acceptance runners resolve API keys, base URLs, model names, and profiles from unified runtime config.
- [x] 1.5 Preserve LF line endings for shell/config/docs files through `.gitattributes`.
- [x] 1.6 Add live-video runner artifacts, trace logging, shared long-video understanding, QA output, and report output.
- [x] 1.7 Add unit coverage for config resolution, local secrets, runner behavior, trace logging, video understanding, and report artifacts.

## 2. Documentation Cleanup

- [x] 2.1 Create OpenSpec proposal, design, capability spec, and task checklist for the current config/live-video work.
- [x] 2.2 Add a current project status document with completed work, verified evidence, known gaps, and next development tasks.
- [x] 2.3 Update live API validation docs to clarify the current live-video runner boundary.

## 3. Remaining Development Tasks

- [x] 3.1 Add graph-mode live-video acceptance runner support that executes the TopAgent graph with per-flow checkpoint thread IDs.
- [x] 3.2 Add a post-run trace validator that reads a run directory and reports whether the open replacement business flow met the intended NVIDIA-style VSA requirements.
- [x] 3.3 Add lightweight timing/cost metrics for video chunks, model calls, QA, report generation, and total runtime.
- [x] 3.4 Decide whether report quality improvements belong in the next change or should wait until graph-mode acceptance is stable.

Decision: defer report quality improvements until shared-mode metrics, graph-mode
acceptance, and post-run validation are stable. Report quality should be handled
in a later focused change rather than mixed into config/live-video close-out.
