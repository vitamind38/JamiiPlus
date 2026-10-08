"""Each role sees only its own level, and nothing changes without a logged-in person and a CSRF token."""

from helpers import csrf_of, post_report, web_login

from jamii_api.models import Report


def _tagged_report(client, make, db, unit, reviewer):
    chp = make.chp(unit)
    rid = post_report(client, chp, text="hakuna dawa").json()["id"]
    csrf = web_login(client, reviewer)
    client.post(f"/review/{rid}", data={"csrf": csrf, "final_theme": "stockout"})
    client.post("/logout", data={"csrf": csrf})
    db.expire_all()
    return db.get(Report, rid)


def test_pages_need_login(client):
    for path in ("/", "/review", "/issues", "/admin", "/alerts"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/login?next=")


def test_forms_need_csrf(client, make):
    officer = make.user("county", county="Nairobi")
    web_login(client, officer)
    r = client.post("/issues/1/own", data={})
    assert r.status_code == 400


def test_officers_only_see_their_area(client, make, db):
    home = make.unit(ward="Kawangware", sub_county="Dagoretti North", county="Nairobi")
    away = make.unit(ward="Kondele", sub_county="Kisumu Central", county="Kisumu")
    reviewer = make.user("reviewer")  # national review team
    here = _tagged_report(client, make, db, home, reviewer)
    there = _tagged_report(client, make, db, away, reviewer)

    cases = [
        (make.user("cha", unit=home), {here.issue_id}),
        (make.user("subcounty", sub_county="Dagoretti North", county="Nairobi"), {here.issue_id}),
        (make.user("county", county="Kisumu"), {there.issue_id}),
        (make.user("national"), {here.issue_id, there.issue_id}),
    ]
    for officer, visible in cases:
        csrf = web_login(client, officer)
        listing = client.get("/issues?status=all").text
        for issue_id in (here.issue_id, there.issue_id):
            shown = f'href="/issues/{issue_id}"' in listing
            assert shown == (issue_id in visible), (officer.role, issue_id)
            assert (client.get(f"/issues/{issue_id}").status_code == 200) == (issue_id in visible)
        client.post("/logout", data={"csrf": csrf})


def test_officers_without_review_rights_cannot_review_or_hear_audio(client, make, db):
    unit = make.unit()
    chp = make.chp(unit)
    rid = post_report(client, chp, audio=b"x" * 500).json()["id"]
    officer = make.user("county", county=unit.county)
    web_login(client, officer)
    assert client.get("/review").status_code == 403
    assert client.get(f"/audio/{rid}").status_code == 404


def test_reviewer_cannot_answer_issues(client, make, db):
    unit = make.unit()
    reviewer = make.user("reviewer")
    report = _tagged_report(client, make, db, unit, reviewer)
    csrf = web_login(client, reviewer)
    r = client.post(
        f"/issues/{report.issue_id}/preview", data={"csrf": csrf, "kind": "action_taken", "action_text": "x"}
    )
    assert r.status_code == 403


def test_reports_never_show_chp_phone(client, make, db):
    unit = make.unit()
    reviewer = make.user("reviewer")
    report = _tagged_report(client, make, db, unit, reviewer)
    officer = make.user("county", county=unit.county)
    web_login(client, officer)
    page = client.get(f"/issues/{report.issue_id}").text
    assert report.chp.phone not in page and report.chp.phone[4:] not in page
    assert "CHP-" in page


def test_admin_pages(client, make, db):
    admin = make.user("admin")
    csrf = web_login(client, admin)
    assert client.get("/admin").status_code == 200
    r = client.post(
        "/admin/units",
        data={
            "csrf": csrf,
            "code": "CHU-9",
            "name": "Test",
            "ward": "W",
            "sub_county": "S",
            "county": "C",
            "lat": "-1.28",
            "lon": "36.82",
        },
    )
    assert r.status_code == 200 or r.status_code == 303
    page = client.get("/admin").text
    assert "CHU-9" in page
    r = client.post(
        "/admin/themes",
        data={
            "csrf": csrf,
            "code": "Water Sanitation",
            "label_en": "Water",
            "label_sw": "Maji",
            "keywords": "maji, water",
        },
        follow_redirects=True,
    )
    assert "water_sanitation" in r.text
    # A second admin action with the same code is refused cleanly.
    r = client.post(
        "/admin/units",
        data={"csrf": csrf, "code": "CHU-9", "name": "Dup", "ward": "W", "sub_county": "S", "county": "C"},
        follow_redirects=True,
    )
    assert "already exists" in r.text


def test_non_admin_cannot_open_admin(client, make):
    web_login(client, make.user("national"))
    assert client.get("/admin").status_code == 403


def test_login_page_and_bad_code(client, make):
    officer = make.user("county", county="Nairobi")
    token = csrf_of(client.get("/login").text)
    client.post("/login", data={"phone": officer.phone, "csrf": token})
    r = client.post("/login/verify", data={"code": "000001", "csrf": token})
    assert r.status_code == 400 and "not right" in r.text


def test_open_redirect_is_blocked(client, make):
    officer = make.user("county", county="Nairobi")
    token = csrf_of(client.get("/login").text)
    client.post("/login", data={"phone": officer.phone, "csrf": token, "next": "//evil.example"})
    from helpers import last_code

    r = client.post("/login/verify", data={"code": last_code(officer.phone), "csrf": token}, follow_redirects=False)
    assert r.headers["location"] == "/"


def test_dashboard_renders_with_demo_data(client, make, db):
    from jamii_api.seed import demo_data

    demo_data(db)
    db.commit()
    officer = make.user("county", county="Nairobi")
    web_login(client, officer)
    page = client.get("/").text
    assert "Reports by barrier theme" in page and "Median days to first response" in page
    assert "<svg" in page and "Show as table" in page
    assert client.get("/?days=30").status_code == 200
    assert client.get("/alerts").status_code == 200


def test_security_headers(client):
    r = client.get("/login")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"


def test_health_and_metrics(client):
    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/readyz").json()["database"] is True
    body = client.get("/metrics").text
    assert "jamii_review_queue" in body and "jamii_http_requests_total" in body


def test_cors_allows_local_flutter_web_only(client):
    ok = client.options(
        "/api/v1/themes",
        headers={
            "Origin": "http://localhost:8686",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:8686"
    assert "access-control-allow-credentials" not in ok.headers
    bad = client.options(
        "/api/v1/themes", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"}
    )
    assert "access-control-allow-origin" not in bad.headers
