# workflow-metadata-hygiene Specification

## Purpose
TBD - created by archiving change clean-orphaned-script-change-metadata. Update Purpose after archive.
## Requirements
### Requirement: Archived changes do not retain active recovery metadata
The repository SHALL keep an archived OpenSpec change only in its archive location and MUST NOT retain an active change directory whose remaining contents are stale Comet recovery metadata.

#### Scenario: Inspecting the active change list after cleanup
- **WHEN** a developer runs `openspec list --json` after an archived change's active artifacts have been removed
- **THEN** the archived change is absent from the active change list
- **AND** its archive directory remains available with the historical artifacts

### Requirement: Metadata cleanup preserves supported runtime scripts
Removing stale workflow metadata MUST NOT delete, rename, or change a supported runtime script or its documented archive reference.

#### Scenario: Checking the script inventory after cleanup
- **WHEN** a developer reviews the runtime script inventory and server sync manifest after metadata cleanup
- **THEN** every supported script entry remains present
- **AND** the archived change reference continues to point to the archive location
