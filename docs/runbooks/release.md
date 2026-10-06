# Release checklist

1. CI green on `main`; staging deployed automatically and `jamii e2e` passed in the deploy log.
2. **On a real low-end Android phone, against staging:**
   - [ ] fresh install shows the privacy notice in Kiswahili
   - [ ] log in with a code by SMS
   - [ ] record a 30-second voice note in airplane mode; it shows "Waiting to send"
   - [ ] turn the network on; it sends without a duplicate
   - [ ] a reviewer tags it; an officer answers; the phone gets the SMS and the app shows "Action taken"
   - [ ] the same by USSD on a basic phone
3. Tag: `git tag vX.Y.Z && git push --tags`. Production deploy waits for a named approver.
4. After deploy: dashboards load, `/readyz` is green, one test SMS reaches a team phone.
5. Rollback if needed: `infra/scripts/deploy.sh --rollback` (migrations stay backwards compatible for one release).
