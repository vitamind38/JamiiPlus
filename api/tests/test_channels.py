from jamii_api.models import Report
from jamii_api.sms import ConsoleBackend

SMS = "/channels/africastalking/sms/inbound?token=test-token"
USSD = "/channels/africastalking/ussd?token=test-token"


def ussd(client, chp, text, session="s1"):
    r = client.post(
        USSD, data={"sessionId": session, "serviceCode": "*384*1234#", "phoneNumber": chp.phone, "text": text}
    )
    assert r.status_code == 200
    assert len(r.text) <= 182
    return r.text


def test_callbacks_need_the_token(client):
    assert client.post("/channels/africastalking/ussd", data={"sessionId": "x", "phoneNumber": "1"}).status_code == 403
    assert client.post("/channels/africastalking/sms/inbound?token=wrong", data={"from": "1"}).status_code == 403


def test_sms_report_with_theme_number(client, make, db):
    chp = make.chp(make.unit())
    r = client.post(SMS, data={"from": chp.phone, "to": "12345", "text": "JAMII 1 Hakuna ORS, simu 0712345678"})
    assert r.status_code == 200
    report = db.query(Report).one()
    assert report.channel == "sms" and report.chp_theme_code == "stockout"
    assert "0712345678" not in report.raw_text and report.raw_text.startswith("Hakuna ORS")
    assert ConsoleBackend.sent[-1] == (
        chp.phone,
        f"Jamii Pulse: Asante. Ripoti #{report.id} imepokelewa. Tutakujulisha hatua itakayochukuliwa.",
    )


def test_sms_from_unknown_number_gets_one_reply_a_day(client, db):
    for _ in range(3):
        client.post(SMS, data={"from": "+254799000111", "text": "hello"})
    assert len(ConsoleBackend.sent) == 1
    assert db.query(Report).count() == 0


def test_sms_status_and_remove(client, make, db):
    chp = make.chp(make.unit(), language="en")
    client.post(SMS, data={"from": chp.phone, "text": "No transport for referrals"})
    rid = db.query(Report).one().id
    client.post(SMS, data={"from": chp.phone, "text": "status"})
    assert ConsoleBackend.sent[-1][1] == f"Jamii Pulse: #{rid} Received"
    client.post(SMS, data={"from": chp.phone, "text": f"REMOVE {rid}"})
    db.expire_all()
    assert db.get(Report, rid).status == "withdrawn"
    assert "removed" in ConsoleBackend.sent[-1][1]


def test_empty_sms_gets_instructions(client, make, db):
    chp = make.chp(make.unit())
    client.post(SMS, data={"from": chp.phone, "text": "JAMII"})
    assert db.query(Report).count() == 0
    assert "Tuma maelezo mafupi" in ConsoleBackend.sent[-1][1]


def test_ussd_full_report(client, make, db):
    chp = make.chp(make.unit())
    assert ussd(client, chp, "").startswith("CON Jamii Pulse")
    page1 = ussd(client, chp, "1")
    assert page1.startswith("CON Chagua") and "1. Dawa na vifaa" in page1
    assert ussd(client, chp, "1*2").startswith("CON Eleza")
    assert "Umbali na usafiri" in ussd(client, chp, "1*2*Barabara imeharibika")
    done = ussd(client, chp, "1*2*Barabara imeharibika*1")
    assert done.startswith("END Asante")
    report = db.query(Report).one()
    assert report.channel == "ussd" and report.chp_theme_code == "transport"
    assert report.raw_text == "Barabara imeharibika"
    # The gateway repeating the final request does not create a second report.
    ussd(client, chp, "1*2*Barabara imeharibika*1")
    assert db.query(Report).count() == 1


def test_ussd_pages_skip_and_cancel(client, make, db):
    chp = make.chp(make.unit())
    page1 = ussd(client, chp, "1")
    if "0. Zaidi" in page1:
        page2 = ussd(client, chp, "1*0")
        assert "9. Mengineyo" in page2
        assert ussd(client, chp, "1*0*9").startswith("CON Eleza")
    assert ussd(client, chp, "1*3*0*2", session="s2").startswith("END Ripoti haikutumwa")
    assert db.query(Report).count() == 0
    assert ussd(client, chp, "1*3*0*1", session="s3").startswith("END Asante")
    assert db.query(Report).one().raw_text is None  # 0 skipped the description


def test_ussd_status_language_and_unknown(client, make, db):
    chp = make.chp(make.unit())
    assert ussd(client, chp, "2") == "END Bado hujatuma ripoti."
    assert "Kiingereza" in ussd(client, chp, "3")
    db.expire_all()
    assert ussd(client, chp, "").startswith("CON Jamii Pulse\n1. Report a problem")
    assert ussd(client, chp, "7").startswith("END Invalid")
    r = client.post(USSD, data={"sessionId": "z", "phoneNumber": "+254799999999", "text": ""})
    assert r.text.startswith("END Namba hii haijasajiliwa")


def test_delivery_report_updates_outbox(client, make, db):
    from jamii_api.models import SmsOutbox

    chp = make.chp(make.unit())
    client.post(SMS, data={"from": chp.phone, "text": "hakuna dawa"})
    row = db.query(SmsOutbox).one()
    client.post(
        "/channels/africastalking/sms/delivery?token=test-token", data={"id": row.provider_id, "status": "Success"}
    )
    db.expire_all()
    assert db.get(SmsOutbox, row.id).delivery_status == "Success"
