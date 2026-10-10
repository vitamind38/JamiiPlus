"""The draft barrier taxonomy and synthetic demo data.

The eight service barriers from the concept note, plus "other". The labels and keywords
are a draft for the phase 0 workshop (docs/taxonomy.md) and live in the theme table once
loaded, where people can change them without a code release.
"""

import random
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from jamii_api.config import get_settings
from jamii_api.db.base import utcnow
from jamii_api.models import (
    Channel,
    Chp,
    Classification,
    CommunityHealthUnit,
    Issue,
    IssueStatus,
    Report,
    ReportStatus,
    Resolution,
    Response,
    ResponseKind,
    Role,
    Theme,
    User,
)
from jamii_api.redaction import redact
from jamii_api.services import issues

THEMES = [
    (
        "stockout",
        "Medicines & supplies",
        "Dawa na vifaa",
        "Medicines, test kits or CHP kit items missing at the facility or in the kit.",
        [
            "dawa",
            "imeisha",
            "zimeisha",
            "hakuna dawa",
            "stock",
            "out of stock",
            "ors",
            "zinc",
            "amoxicillin",
            "rdt",
            "mrdt",
            "test kit",
            "kit",
            "vifaa",
            "gloves",
            "glavu",
            "medicine",
            "drugs",
            "supplies",
            "vidonge",
            "sindano",
            "condom",
            "family planning",
            "upangaji uzazi",
        ],
    ),
    (
        "transport",
        "Distance & transport",
        "Umbali na usafiri",
        "Households cannot reach care because of distance, cost of fare, roads or no ambulance.",
        [
            "mbali",
            "umbali",
            "usafiri",
            "boda",
            "nauli",
            "fare",
            "transport",
            "far",
            "distance",
            "road",
            "barabara",
            "ambulance",
            "ambulensi",
            "kutembea",
            "walk",
            "kilomita",
            "km",
            "mto",
            "river",
        ],
    ),
    (
        "cost",
        "Cost of care",
        "Gharama ya matibabu",
        "Households are charged, or cannot afford, care that should be accessible.",
        [
            "pesa",
            "gharama",
            "bei",
            "cost",
            "money",
            "lipa",
            "kulipa",
            "fee",
            "charge",
            "sha",
            "nhif",
            "bima",
            "insurance",
            "ksh",
            "shilingi",
            "ghali",
            "expensive",
            "afford",
        ],
    ),
    (
        "staffing",
        "Staff shortage",
        "Uhaba wa wahudumu",
        "Facilities are closed, understaffed or overcrowded when households arrive.",
        [
            "nurse",
            "muuguzi",
            "daktari",
            "doctor",
            "staff",
            "wahudumu",
            "imefungwa",
            "closed",
            "foleni",
            "queue",
            "absent",
            "mgomo",
            "strike",
            "msongamano",
            "overcrowded",
            "hakuna mtu",
        ],
    ),
    (
        "referral",
        "Referral feedback",
        "Rufaa na majibu",
        "Referrals are not completed, or the CHP never hears what happened.",
        [
            "rufaa",
            "referral",
            "refer",
            "referred",
            "feedback",
            "majibu",
            "hakuenda",
            "hakurudi",
            "ufuatiliaji",
            "follow up",
            "followup",
        ],
    ),
    (
        "training",
        "Training & supervision",
        "Mafunzo na usimamizi",
        "CHPs lack training, refreshers or supportive supervision.",
        [
            "mafunzo",
            "training",
            "usimamizi",
            "supervision",
            "supervisor",
            "msimamizi",
            "refresher",
            "sijui",
            "module",
            "hajakuja",
            "mentorship",
        ],
    ),
    (
        "workload",
        "Workload & stipend",
        "Mzigo wa kazi na posho",
        "Stipends late or unpaid, too many households, or missing working tools.",
        [
            "posho",
            "stipend",
            "allowance",
            "malipo",
            "haijalipwa",
            "unpaid",
            "mzigo",
            "workload",
            "kaya nyingi",
            "households",
            "uchovu",
            "airtime",
            "bundles",
            "simu",
            "phone",
            "uniform",
            "motisha",
            "bag",
        ],
    ),
    (
        "social",
        "Cultural & social",
        "Mila na jamii",
        "Beliefs, stigma, misinformation or family decisions delay care-seeking.",
        [
            "mila",
            "culture",
            "imani",
            "belief",
            "kanisa",
            "church",
            "mganga",
            "herbalist",
            "unyanyapaa",
            "stigma",
            "mume",
            "husband",
            "anakataa",
            "kukataa",
            "refuse",
            "uvumi",
            "rumour",
            "myth",
            "chanjo",
            "vaccine",
        ],
    ),
    ("other", "Other", "Mengineyo", "Anything that fits no theme yet. Reviewed for new themes.", []),
]


def seed_themes(db: Session) -> int:
    existing = set(db.scalars(select(Theme.code)))
    added = 0
    for order, (code, en, sw, desc, keywords) in enumerate(THEMES):
        if code not in existing:
            db.add(
                Theme(
                    code=code,
                    label_en=en,
                    label_sw=sw,
                    description=desc,
                    keywords=keywords,
                    sort_order=(order + 1) * 10 if code != "other" else 1000,
                )
            )
            added += 1
    db.flush()
    return added


_UNITS = [
    ("CHU-0001", "Kawangware CHU", "Kawangware", "Dagoretti North", "Nairobi"),
    ("CHU-0002", "Gatina CHU", "Gatina", "Dagoretti North", "Nairobi"),
    ("CHU-0003", "Kileleshwa CHU", "Kileleshwa", "Dagoretti North", "Nairobi"),
]

_SAMPLES = [
    ("stockout", "Hakuna ORS wala zinc kwenye dispensary tangu wiki mbili. Mama Wanjiku alirudishwa bila dawa."),
    ("stockout", "mRDT kits zimeisha, siwezi kupima malaria nyumbani"),
    ("transport", "Kituo ni mbali sana, nauli ya boda ni 300 bob, wamama wajawazito hawaendi kliniki"),
    ("cost", "Wanaambiwa walipe Ksh 500 kwa kadi ya kliniki ingawa ni bure"),
    ("staffing", "Dispensary ilikuwa imefungwa Jumamosi, hakuna muuguzi"),
    ("referral", "Nilipeleka rufaa tatu wiki hii na sijapata majibu yoyote. Call me on 0712345678"),
    ("workload", "Posho ya miezi mitatu haijalipwa, CHPs wanakata tamaa"),
    ("social", "Baadhi ya familia wanakataa chanjo kwa sababu ya uvumi kanisani"),
    ("training", "Hatujapata mafunzo ya refresher kuhusu danger signs mwaka huu"),
]


def demo_data(db: Session, reports_per_chp: int = 6, seed: int = 7) -> dict[str, int]:
    """Synthetic records for local development and staging. Never real people or places' patients."""
    rng = random.Random(seed)
    seed_themes(db)
    units = []
    for code, name, ward, sub, county in _UNITS:
        u = db.scalar(select(CommunityHealthUnit).where(CommunityHealthUnit.code == code))
        if u is None:
            u = CommunityHealthUnit(code=code, name=name, ward=ward, sub_county=sub, county=county)
            db.add(u)
        units.append(u)
    db.flush()

    people = [
        ("+254700000001", "Demo Admin", Role.ADMIN, None, None, None, False),
        ("+254700000002", "Grace Achieng (CHA)", Role.CHA, units[0], None, None, True),
        ("+254700000003", "Peter Mwangi (Sub-county)", Role.SUBCOUNTY, None, "Dagoretti North", "Nairobi", False),
        ("+254700000004", "Amina Hassan (County)", Role.COUNTY, None, None, "Nairobi", False),
        ("+254700000005", "Review Team", Role.REVIEWER, None, None, "Nairobi", True),
    ]
    for phone, name, role, unit, sub, county, reviews in people:
        if db.scalar(select(User).where(User.phone == phone)) is None:
            db.add(
                User(
                    phone=phone,
                    name=name,
                    role=role,
                    chu_id=unit.id if unit else None,
                    sub_county=(unit.sub_county if unit else sub),
                    county=(unit.county if unit else county),
                    can_review=reviews,
                )
            )

    chps = []
    for n in range(9):
        phone = f"+2547100000{n:02d}"
        chp = db.scalar(select(Chp).where(Chp.phone == phone))
        if chp is None:
            chp = Chp(
                phone=phone,
                chu_id=units[n % len(units)].id,
                language="en" if n % 4 == 0 else "sw",
                consent_version=get_settings().consent_version,
                consented_at=utcnow(),
            )
            db.add(chp)
        chps.append(chp)
    db.flush()

    created = 0
    now = utcnow()
    for chp in chps:
        db.refresh(chp)
        for _ in range(reports_per_chp):
            theme, text = rng.choice(_SAMPLES)
            when = now - timedelta(days=rng.randint(0, 80), hours=rng.randint(0, 23))
            report = Report(
                chp_id=chp.id,
                channel=rng.choice([Channel.APP, Channel.SMS, Channel.USSD]),
                language=chp.language,
                chu_id=chp.chu_id,
                ward=chp.chu.ward,
                sub_county=chp.chu.sub_county,
                county=chp.chu.county,
                chp_theme_code=theme,
                raw_text=redact(text).text,
                redaction="rules",
                status=ReportStatus.NEEDS_TAGGING,
                reported_at=when,
                created_at=when,
                text_expires_at=when + timedelta(days=730),
            )
            db.add(report)
            db.flush()
            # Two in three are already tagged and grouped, so dashboards have something to show.
            if rng.random() < 0.66:
                db.add(Classification(report_id=report.id, final_theme=theme, reviewed_at=when))
                issues.group(db, report, theme)
            created += 1
    db.flush()

    # Some issues already have an officer response, so response times have something to show.
    officer = db.scalar(select(User).where(User.role == Role.SUBCOUNTY))
    responded = 0
    for issue in db.scalars(select(Issue).where(Issue.status == IssueStatus.RECEIVED).order_by(Issue.id)):
        if rng.random() < 0.5:
            continue
        at = min(issue.last_reported_at + timedelta(days=rng.randint(1, 9)), now)  # never in the future
        resolved = rng.random() < 0.4
        db.add(
            Response(
                issue_id=issue.id,
                officer_id=officer.id,
                kind=ResponseKind.RESOLVED if resolved else ResponseKind.ACTION_TAKEN,
                action_text="Demo: supplies requested from the sub-county store",
                sms_text="(demo, not sent)",
                recipients=issue.report_count,
                sms_sent=True,
                created_at=at,
            )
        )
        issue.status = IssueStatus.RESOLVED if resolved else IssueStatus.ACTION_TAKEN
        issue.resolution = Resolution.ACTIONED if resolved else None
        issue.resolved_at = at if resolved else None
        issue.first_response_at = at
        issue.owner_id = officer.id
        responded += 1
    db.flush()
    return {"units": len(units), "chps": len(chps), "reports": created, "issues_answered": responded}
