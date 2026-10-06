"""Fixed SMS and USSD wording in Swahili and English. No text here is machine-generated."""

LEVEL_NAMES = {
    "sw": {
        "cha": "Msaidizi wa Afya ya Jamii (CHA)",
        "subcounty": "timu ya afya ya kaunti ndogo",
        "county": "timu ya afya ya kaunti",
        "national": "Wizara ya Afya",
    },
    "en": {
        "cha": "community health assistant",
        "subcounty": "sub-county health team",
        "county": "county health team",
        "national": "Ministry of Health",
    },
}

STATUS_NAMES = {
    "sw": {
        "received": "Imepokelewa",
        "escalated": "Imepelekwa juu",
        "action_taken": "Hatua imechukuliwa",
        "resolved": "Imetatuliwa",
        "withdrawn": "Imeondolewa",
    },
    "en": {
        "received": "Received",
        "escalated": "Escalated",
        "action_taken": "Action taken",
        "resolved": "Resolved",
        "withdrawn": "Withdrawn",
    },
}

_SMS = {
    "sw": {
        "ack": "Jamii Pulse: Asante. Ripoti #{report_id} imepokelewa. Tutakujulisha hatua itakayochukuliwa.",
        "not_registered": "Jamii Pulse: Namba hii haijasajiliwa. Tafadhali wasiliana na CHA wako.",
        "empty": "Jamii Pulse: Tuma maelezo mafupi ya tatizo. Mfano: 1 Hakuna dawa ya ORS kituoni.",
        "escalated": "Jamii Pulse: Ripoti yako kuhusu {theme} ({ward}) imepelekwa kwa {level}. Ref #{issue_id}.",
        "action_taken": "Jamii Pulse: Hatua kuhusu {theme} ({ward}): {text} - {officer}",
        "resolved_actioned": "Jamii Pulse: {theme} ({ward}) limetatuliwa: {text} - {officer}",
        "resolved_not_actioned": (
            "Jamii Pulse: Ripoti kuhusu {theme} ({ward}) imefungwa bila hatua. Sababu: {text} - {officer}"
        ),
        "otp": "Jamii Pulse: Nambari yako ya kuingia ni {code}. Inaisha baada ya dakika {minutes}. Usimpe mtu.",
        "withdrawn": "Jamii Pulse: Ripoti #{report_id} imeondolewa kama ulivyoomba.",
    },
    "en": {
        "ack": "Jamii Pulse: Thank you. Report #{report_id} received. We will tell you what action is taken.",
        "not_registered": "Jamii Pulse: This number is not registered. Please contact your CHA.",
        "empty": "Jamii Pulse: Send a short description of the problem. Example: 1 No ORS at the facility.",
        "escalated": "Jamii Pulse: Your report on {theme} ({ward}) has been escalated to the {level}. Ref #{issue_id}.",
        "action_taken": "Jamii Pulse: Action on {theme} ({ward}): {text} - {officer}",
        "resolved_actioned": "Jamii Pulse: {theme} ({ward}) resolved: {text} - {officer}",
        "resolved_not_actioned": (
            "Jamii Pulse: Report on {theme} ({ward}) closed without action. Reason: {text} - {officer}"
        ),
        "otp": "Jamii Pulse: Your login code is {code}. It expires in {minutes} minutes. Do not share it.",
        "withdrawn": "Jamii Pulse: Report #{report_id} has been removed as you asked.",
    },
}

_USSD = {
    "sw": {
        "menu": "CON Jamii Pulse\n1. Ripoti tatizo\n2. Hali ya ripoti zangu\n3. Language: English",
        "pick_theme": "CON Chagua aina ya tatizo:",
        "describe": "CON Eleza tatizo kwa ufupi (usitaje majina ya wagonjwa). Tuma 0 kuruka:",
        "confirm": "CON Tuma ripoti kuhusu {theme}?\n1. Ndiyo\n2. Hapana",
        "sent": "END Asante. Ripoti #{report_id} imepokelewa. Utapata SMS hatua ikichukuliwa.",
        "cancelled": "END Ripoti haikutumwa.",
        "no_reports": "END Bado hujatuma ripoti.",
        "status_header": "END Ripoti zako:",
        "lang_changed": "END Lugha imebadilishwa kuwa Kiingereza.",
        "invalid": "END Chaguo si sahihi. Jaribu tena.",
        "not_registered": "END Namba hii haijasajiliwa. Wasiliana na CHA wako.",
        "rate_limited": "END Umetuma ripoti nyingi sana. Jaribu tena baadaye.",
    },
    "en": {
        "menu": "CON Jamii Pulse\n1. Report a problem\n2. My report status\n3. Lugha: Kiswahili",
        "pick_theme": "CON Choose the type of problem:",
        "describe": "CON Describe the problem briefly (do not name patients). Send 0 to skip:",
        "confirm": "CON Send report on {theme}?\n1. Yes\n2. No",
        "sent": "END Thank you. Report #{report_id} received. You will get an SMS when action is taken.",
        "cancelled": "END Report not sent.",
        "no_reports": "END You have not sent any reports yet.",
        "status_header": "END Your reports:",
        "lang_changed": "END Language changed to Kiswahili.",
        "invalid": "END Invalid choice. Please try again.",
        "not_registered": "END This number is not registered. Contact your CHA.",
        "rate_limited": "END You have sent too many reports. Try again later.",
    },
}

SMS_MAX_CHARS = 459  # three segments


def lang(code: str | None) -> str:
    return "en" if code == "en" else "sw"


def sms(key: str, language: str | None, **kw: object) -> str:
    text = _SMS[lang(language)][key].format(**kw)
    return text if len(text) <= SMS_MAX_CHARS else text[: SMS_MAX_CHARS - 1] + "…"


def ussd(key: str, language: str | None, **kw: object) -> str:
    return _USSD[lang(language)][key].format(**kw)


def level_name(level: str, language: str | None) -> str:
    return LEVEL_NAMES[lang(language)].get(level, level)


def status_name(status: str, language: str | None) -> str:
    return STATUS_NAMES[lang(language)].get(status, status)
