# Reviewer Artifact Guide (Multi-Model 32)

This guide maps saved experiment artifacts to their current role in the paper pipeline.
- Paper draft: `paper\paper_draft.md`
- Submission checklist: `paper\submission_checklist.md`

## Environment

- Python: `3.13.11`
- Platform: `Windows-11-10.0.26100-SP0`
- Working directory: `C:\Users\Admin\VSCodeProjects\Post-Hoc Minimal Patch Suggestion via Execution Intervention`
- Selected distributions:
  - `httpx==0.28.1`
  - `litellm==1.82.6`
  - `openai==2.26.0`
  - `pydantic==2.12.4`
  - `tau2==1.0.0`

## Artifact Entries

### paper_bundle_multimodel_32

- Type: `paper_bundle`
- Path: `artifacts\paper_bundle_multimodel_32`
- Domains: `['airline', 'retail']`
- Corpus entry count: `32`
- Strict SRR: `0.40625`
- Oracle SRR: `0.40625`
- Available files:
  - `paper_bundle_summary.json`
  - `strict_autopsy_report.json`
  - `oracle_autopsy_report.json`

### paper_tables

- Type: `paper_tables`
- Path: `artifacts\paper_bundle_multimodel_32\paper_tables`
- Experiment count: `2`
- Main result rows: `2`
- Synthetic localization rows: `0`
- Available files:
  - `paper_tables.json`
  - `paper_tables.md`

### paper_case_studies_multimodel_32

- Type: `case_studies`
- Path: `artifacts\paper_case_studies_multimodel_32`
- Selected case count: `6`
- Recovered case count: `14`
- Source artifact count: `2`
- Available files:
  - `case_studies.json`
  - `case_studies.md`

