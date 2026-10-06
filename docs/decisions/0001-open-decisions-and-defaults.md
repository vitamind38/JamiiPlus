# 0001: Open decisions and the defaults the code assumes

Status: **proposed**, 6 Oct 2026. The build guide says to settle these before writing code.
The code was written so that none of them is baked in: each is a setting, a data row or a
deployment choice. This page records the default chosen for each, and where to change it.

| Decision | Default in the code | Where to change it | Before pilot |
|---|---|---|---|
| Standalone app or eCHIS V3 module | Standalone app beside eCHIS; no eCHIS integration at all in the MVP | Architecture; the API is the seam a future module would call | Confirm with the Ministry's digital health team |
| Pilot location | None. Units, wards, sub-counties and counties are data entered under Admin | Admin → Units | Choose one sub-county with a committed county officer |
| First languages | Kiswahili and English in the app, SMS and USSD. Report language is recorded per report, so a local language can be added | `mobile/lib/l10n/*.arb`, `api/src/jamii_api/messages.py` | Pick the local language; speech-to-text target follows |
| Hosting provider | Docker Compose on one Kenyan server; no provider-specific services | `infra/` | Confirm GPU price only when speech-to-text is ready (phase 3) |
| Who owns the data | Not encoded. Consent text says data is stored in Kenya and seen by county teams | Privacy notice (`mobile/lib/l10n`), DPIA | Written agreement with the county |
| Sustainability | Nothing proprietary: open-source stack, one repository, one server | n/a | Decide before investing beyond the pilot |
| Who reviews the queue | Both are supported: any officer can be given review rights, and a `reviewer` role exists for a central team | Admin → people → "Can work the review queue" | Decide staffing and target response times |

## Other choices made where the guide left room

- **Admin and review UI:** server-rendered pages in the API (Jinja templates, no JavaScript
  build). One service to deploy; works on an officer's phone browser.
- **In-app dashboards and Metabase both exist.** Each officer must see only their own level,
  and Metabase's open-source edition cannot restrict rows per person. So scoped dashboards are
  built into the officer web app; Metabase reads de-identified SQL views for analysts.
- **Issues group reports by theme and ward.** A new report joins the open issue for its theme
  in its ward; a reviewer can split it into a new issue. Resolved issues are never reopened:
  a later report starts a new one.
- **New issues start with the CHA.** `JAMII_ISSUE_DEFAULT_LEVEL=cha`. Officers escalate
  CHA → sub-county → county → national. Set it to `subcounty` if CHAs will not answer.
- **Every report goes to a person in phases 1 and 2**, including one where the CHP only tapped
  a category; their tap is pre-selected so it is one click. That builds the labelled set.
- **The model never overrides the CHP.** In assisted mode, if the CHP chose a category and the
  model disagrees, the report goes to a person however confident the model is.
- **Confidence thresholds default to 1.01**, which means "never auto-accept". The model only
  pre-fills reviewers' choices until `ml/scripts/thresholds.py` recommends a value from pilot data.
- **Retention:** raw audio 30 days (plus a 37-day storage-level backstop in MinIO); report text
  2 years. Both are settings; confirm them in the DPIA.
- **Supervisors never see CHP identity.** CHPs appear as a stable pseudonym (`CHP-3F9A1C`).
  There is no "unmask" feature. Admins see masked phone numbers only.
- **The audit log is a separate database** that the app role can insert into and read but not
  change. If it is unreachable, the event is written to the application log instead and the
  request still succeeds.
- **SMS replies:** SMS-channel reports get an immediate "received" SMS; app and USSD users see
  "received" on screen. Every later status change (escalated, action taken, resolved) goes
  out by SMS to every CHP whose report is in the issue, in their language, after the officer
  has seen the exact text.
