"""The whole MVP loop: a CHP reports, a person tags it, an officer answers, the CHP hears back."""

from helpers import bearer, post_report, web_login

from jamii_api.models import Classification, Issue, Report, Response, SmsOutbox
from jamii_api.sms import ConsoleBackend


def test_report_to_response_to_sms(client, make, db):
    unit = make.unit(ward="Kawangware")
    sw_chp = make.chp(unit, language="sw")
    en_chp = make.chp(unit, language="en")
    reviewer = make.user("reviewer", county="Nairobi", name="Rita Reviewer")
    officer = make.user("subcounty", sub_county="Dagoretti North", county="Nairobi", name="Peter Mwangi")

    # 1. Two CHPs report the same barrier.
    r1 = post_report(client, sw_chp, text="Hakuna ORS kwenye dispensary", theme_code="stockout").json()
    r2 = post_report(client, en_chp, text="No ORS or zinc this week").json()

    # 2. A reviewer tags both. The second joins the first one's issue.
    csrf = web_login(client, reviewer)
    page = client.get("/review")
    assert f"/review/{r1['id']}" in page.text and f"/review/{r2['id']}" in page.text
    item = client.get(f"/review/{r1['id']}")
    assert 'value="stockout" selected' in item.text  # the CHP's tap is pre-selected
    for rid in (r1["id"], r2["id"]):
        res = client.post(
            f"/review/{rid}", data={"csrf": csrf, "final_theme": "stockout", "grouping": "auto"}, follow_redirects=False
        )
        assert res.status_code == 303
    db.expire_all()
    a, b = db.get(Report, r1["id"]), db.get(Report, r2["id"])
    assert a.issue_id == b.issue_id is not None
    issue = db.get(Issue, a.issue_id)
    assert issue.report_count == 2 and issue.status == "received"
    assert db.get(Classification, a.classification.id).reviewed_by == reviewer.id
    client.post("/logout", data={"csrf": csrf})

    # 3. The sub-county officer previews, then releases, an action.
    csrf = web_login(client, officer)
    assert f"/issues/{issue.id}" in client.get("/issues").text
    # The resolution radio is always in the form; it must not leak into a non-resolving action.
    preview = client.post(
        f"/issues/{issue.id}/preview",
        data={"csrf": csrf, "kind": "action_taken", "action_text": "200 ORS packs delivered", "resolution": "actioned"},
    )
    assert preview.status_code == 200
    assert "acted on" not in preview.text
    assert "Hatua kuhusu Dawa na vifaa (Kawangware): 200 ORS packs delivered - Peter Mwangi" in preview.text
    assert "Action on Medicines &amp; supplies (Kawangware)" in preview.text
    assert ConsoleBackend.sent == [] or all(
        "Jamii Pulse: Your login code" in m or "kuingia" in m for _, m in ConsoleBackend.sent
    )  # nothing sent by previewing
    ConsoleBackend.sent.clear()
    res = client.post(
        f"/issues/{issue.id}/respond",
        data={"csrf": csrf, "kind": "action_taken", "action_text": "200 ORS packs delivered"},
        follow_redirects=False,
    )
    assert res.status_code == 303

    # 4. Each CHP gets one SMS in their own language.
    sent = dict(ConsoleBackend.sent)
    assert set(sent) == {sw_chp.phone, en_chp.phone}
    assert sent[sw_chp.phone].startswith("Jamii Pulse: Hatua kuhusu")
    assert sent[en_chp.phone].startswith("Jamii Pulse: Action on")
    db.expire_all()
    assert db.query(SmsOutbox).filter_by(status="sent").count() == 2
    resp = db.query(Response).one()
    assert resp.sms_sent and resp.recipients == 2 and resp.officer_id == officer.id
    issue = db.get(Issue, issue.id)
    assert issue.status == "action_taken" and issue.owner_id == officer.id and issue.first_response_at

    # 5. The CHP sees it in the app too.
    mine = client.get("/api/v1/reports/mine", headers=bearer(sw_chp)).json()
    assert mine[0]["status"] == "action_taken"
    assert mine[0]["responses"][0]["text"] == "200 ORS packs delivered"

    # 6. Closing without action still tells CHPs why.
    ConsoleBackend.sent.clear()
    client.post(
        f"/issues/{issue.id}/respond",
        data={
            "csrf": csrf,
            "kind": "resolved",
            "resolution": "not_actioned",
            "action_text": "County stock arrives next month",
        },
    )
    assert any("closed without action. Reason: County stock arrives next month" in m for _, m in ConsoleBackend.sent)
    db.expire_all()
    assert db.get(Issue, issue.id).status == "resolved"

    # 7. A new report after resolution starts a new issue.
    r3 = post_report(client, sw_chp, text="ORS imeisha tena").json()
    client.post("/logout", data={"csrf": csrf})
    csrf = web_login(client, reviewer)
    client.post(f"/review/{r3['id']}", data={"csrf": csrf, "final_theme": "stockout", "grouping": "auto"})
    db.expire_all()
    assert db.get(Report, r3["id"]).issue_id != issue.id


def test_voice_note_needs_a_typed_transcript(client, make, db):
    unit = make.unit()
    chp = make.chp(unit)
    reviewer = make.user("cha", unit=unit, can_review=True)
    rid = post_report(client, chp, audio=b"voice" * 200, theme_code="transport").json()["id"]
    csrf = web_login(client, reviewer)
    assert client.get(f"/audio/{rid}").status_code == 200
    client.post(f"/review/{rid}", data={"csrf": csrf, "final_theme": "transport"})
    db.expire_all()
    assert db.get(Report, rid).status == "needs_transcription"  # refused without a transcript
    client.post(
        f"/review/{rid}",
        data={"csrf": csrf, "final_theme": "transport", "transcript": "Boda ni 300 bob, Mama Akinyi alishindwa kwenda"},
    )
    db.expire_all()
    report = db.get(Report, rid)
    assert report.status == "grouped"
    assert report.transcript.model_version == "human"
    assert "Akinyi" not in report.transcript.text and "300" in report.transcript.text


def test_escalation_moves_the_issue_up(client, make, db):
    unit = make.unit()
    chp = make.chp(unit)
    cha = make.user("cha", unit=unit, can_review=True, name="Grace CHA")
    sub = make.user("subcounty", sub_county=unit.sub_county, county=unit.county)
    rid = post_report(client, chp, text="Posho haijalipwa miezi mitatu").json()["id"]
    csrf = web_login(client, cha)
    client.post(f"/review/{rid}", data={"csrf": csrf, "final_theme": "workload"})
    issue_id = db.get(Report, rid).issue_id
    ConsoleBackend.sent.clear()
    client.post(f"/issues/{issue_id}/respond", data={"csrf": csrf, "kind": "escalated"})
    assert "timu ya afya ya kaunti ndogo" in ConsoleBackend.sent[-1][1]
    db.expire_all()
    issue = db.get(Issue, issue_id)
    assert issue.level == "subcounty" and issue.status == "escalated"
    # The CHA can no longer answer it; the sub-county officer can.
    r = client.post(f"/issues/{issue_id}/preview", data={"csrf": csrf, "kind": "action_taken", "action_text": "x"})
    assert r.status_code == 403
    client.post("/logout", data={"csrf": csrf})
    csrf = web_login(client, sub)
    r = client.post(f"/issues/{issue_id}/preview", data={"csrf": csrf, "kind": "action_taken", "action_text": "Paid"})
    assert r.status_code == 200


def test_withdrawn_report_leaves_issue_and_gets_no_sms(client, make, db):
    unit = make.unit()
    a, b = make.chp(unit), make.chp(unit)
    reviewer = make.user("reviewer")
    officer = make.user("county", county=unit.county)
    ids = [post_report(client, c, text="hakuna dawa").json()["id"] for c in (a, b)]
    csrf = web_login(client, reviewer)
    for rid in ids:
        client.post(f"/review/{rid}", data={"csrf": csrf, "final_theme": "stockout"})
    client.post(f"/api/v1/reports/{ids[1]}/withdraw", headers=bearer(b))
    db.expire_all()
    issue = db.get(Issue, db.get(Report, ids[0]).issue_id)
    assert issue.report_count == 1
    client.post("/logout", data={"csrf": csrf})
    csrf = web_login(client, officer)
    ConsoleBackend.sent.clear()
    client.post(f"/issues/{issue.id}/respond", data={"csrf": csrf, "kind": "action_taken", "action_text": "Done"})
    assert [p for p, _ in ConsoleBackend.sent] == [a.phone]
