"""Each role sees only its own level. Every query for reports or issues goes through here."""

from sqlalchemy import ColumnElement, and_, false, true

from jamii_api.models import Issue, Level, Report, Role, SpikeAlert, User

OFFICER_ROLES = {Role.CHA, Role.SUBCOUNTY, Role.COUNTY, Role.NATIONAL}
RANK = {Level.CHA: 0, Level.SUBCOUNTY: 1, Level.COUNTY: 2, Level.NATIONAL: 3}


def _effective_level(user: User) -> Level:
    if user.role in OFFICER_ROLES:
        return Level(user.role)
    # Reviewers and admins: a county if one is set, otherwise everything.
    if user.county and user.sub_county:
        return Level.SUBCOUNTY
    if user.county:
        return Level.COUNTY
    return Level.NATIONAL


def _area_filter(user: User, ward_col, sub_county_col, county_col) -> ColumnElement[bool]:
    level = _effective_level(user)
    if level == Level.CHA:
        chu = user.chu
        if chu is None:
            return false()
        return and_(ward_col == chu.ward, sub_county_col == chu.sub_county, county_col == chu.county)
    if level == Level.SUBCOUNTY:
        return and_(sub_county_col == user.sub_county, county_col == user.county)
    if level == Level.COUNTY:
        return county_col == user.county
    return true()


def report_filter(user: User) -> ColumnElement[bool]:
    if _effective_level(user) == Level.CHA:
        return Report.chu_id == user.chu_id
    return _area_filter(user, Report.ward, Report.sub_county, Report.county)


def issue_filter(user: User) -> ColumnElement[bool]:
    return _area_filter(user, Issue.ward, Issue.sub_county, Issue.county)


def alert_filter(user: User) -> ColumnElement[bool]:
    return _area_filter(user, SpikeAlert.ward, SpikeAlert.sub_county, SpikeAlert.county)


def in_scope_issue(user: User, issue: Issue) -> bool:
    level = _effective_level(user)
    if level == Level.NATIONAL:
        return True
    if level == Level.COUNTY:
        return issue.county == user.county
    if level == Level.SUBCOUNTY:
        return issue.county == user.county and issue.sub_county == user.sub_county
    chu = user.chu
    return chu is not None and (issue.ward, issue.sub_county, issue.county) == (chu.ward, chu.sub_county, chu.county)


def in_scope_report(user: User, report: Report) -> bool:
    level = _effective_level(user)
    if level == Level.CHA:
        return report.chu_id == user.chu_id
    if level == Level.SUBCOUNTY:
        return report.county == user.county and report.sub_county == user.sub_county
    if level == Level.COUNTY:
        return report.county == user.county
    return True


def can_review(user: User) -> bool:
    return user.active and (user.can_review or user.role == Role.REVIEWER)


def can_act_on(user: User, issue: Issue) -> bool:
    """Officers answer issues at their own level or below, inside their area."""
    if not user.active or user.role not in OFFICER_ROLES:
        return False
    return RANK[Level(user.role)] >= RANK[Level(issue.level)] and in_scope_issue(user, issue)


def is_admin(user: User) -> bool:
    return user.active and user.role == Role.ADMIN
