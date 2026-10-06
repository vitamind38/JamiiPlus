# Data Protection Impact Assessment (template)

Fill in before any real CHP uses the system. Facts below are what the software does; the
blanks are decisions for the project and the county. Have it reviewed by a data protection
lawyer and, if required, filed with the ODPC.

## 1. The processing

| | |
|---|---|
| Purpose | Let CHPs report barriers to care; route them to officers; tell CHPs what was done; measure response times |
| Controller / processor | _To decide: county, Ministry or project organisation_ |
| Lawful basis | _Consent of CHPs, plus public-interest task of the county? Confirm_ |
| Data subjects | CHPs (reporters); officers (users). **Patients are not data subjects by design**, but a voice note may mention one |
| Personal data held | CHP phone number, community health unit, language, consent date; officer name, phone, role; report text (redacted), voice notes (raw, up to 30 days), transcripts (redacted) |
| Sensitive data | Health data could appear in a voice note despite the prompt. Mitigations below |
| Location | One server in a Kenyan data centre: _provider_. Backups in a second Kenyan location: _provider_ |
| Retention | Voice notes 30 days; report text 2 years; one-time codes 1 day; SMS bodies 180 days; audit log _to decide_ |
| Recipients | County and sub-county health teams (own area only); national team (aggregates); reviewers (to tag reports) |

## 2. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation in the system |
|---|---|---|---|
| A patient is named in a voice note | Medium | High | Prompt at capture; rule-based redaction of text and transcripts; raw audio heard only by reviewers, every play logged, deleted after 30 days |
| A supervisor identifies and punishes a CHP | Medium | High | Pseudonyms only; no per-CHP metrics; stated promise; audit log |
| Unauthorised access to reports | Low | High | OTP login, lockout, role scoping, TLS, separate audit database |
| Data leaves Kenya | Low | High | All services on one Kenyan server; the model service has no network route out; app backups disabled; Sentry configured without PII |
| Reports pile up unanswered, CHPs lose trust | Medium | Medium | Pilot only with a committed officer; response time on every dashboard; queue alerts |
| Model mislabels reports | Medium | Low | No AI in phases 1–2; afterwards only above a pilot-set threshold, weekly human re-check, rollback |

## 3. Data subject rights

- Access: a CHP sees all their reports in the app.
- Erasure: in-app removal or `REMOVE <id>` by SMS; content deleted immediately.
- Withdrawal of consent: _process to define (deactivate account under Admin; reports kept as counts only?)_

## 4. Sign-off

| Role | Name | Date |
|---|---|---|
| Data protection officer | | |
| County health department | | |
| Project lead | | |
