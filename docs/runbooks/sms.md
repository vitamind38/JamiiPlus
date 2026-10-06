# SMS failing or backed up

1. Admin has no SMS screen by design; check the outbox in the database:
   `docker compose ... exec postgres psql -U postgres jamii -c "select status, last_error, count(*) from sms_outbox group by 1,2"`.
2. `AT 405` = Africa's Talking balance is empty: top up. `AT 403/404` = bad or unsupported number: fix the CHP's number under Admin. `network:`/`provider 5xx` = retried automatically with backoff.
3. Queued but not moving: the worker or beat is down (see workers.md), or run `python -m jamii_workers.jobs flush_outbox`.
4. A CHP says they never got an update: the issue page lists each response and how many CHPs it went to.
