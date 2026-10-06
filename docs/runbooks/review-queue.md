# Review queue growing

Reports do not reach issues, dashboards or officers until reviewed. A long queue breaks the "you said, we did" promise.

1. Dashboard → "Waiting for review", or `/review` as a reviewer: which queue is long (redaction, transcript, theme)?
2. Transcripts: voice notes take the longest. Ask CHAs with review rights to help, or add a reviewer (Admin → Add person → role `reviewer`).
3. In assisted mode, a jump in the queue with no jump in reports means the model service is down or less confident: check `/v1/models` on the model service and the `ModelAgreementLow` alert.
4. Record the weekly queue size and agreement rate in the weekly review (see the build guide).
