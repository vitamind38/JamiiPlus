import pytest

from jamii_api.redaction import NAME, NUMBER, redact
from jamii_api.security import InvalidPhone, normalize_phone, pseudonym


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("Call me on 0712345678 tomorrow", "345678"),
        ("namba yake ni +254 712 345 678", "345"),
        ("simu 0712-345-678", "345"),
        ("ID number 23456789", "23456789"),
        ("household 104523", "104523"),
    ],
)
def test_numbers_are_masked(text, secret):
    out = redact(text)
    assert NUMBER in out.text
    assert secret not in out.text


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        ("nauli ni 300 bob", "300"),
        ("walilipa Ksh 15000 kwa upasuaji", "15000"),
        ("Ksh. 2,500 for the card", "2,500"),
        ("watoto 12 hawajapata chanjo", "12"),
        ("tangu 2026", "2026"),
    ],
)
def test_amounts_and_small_numbers_are_kept(text, kept):
    assert kept in redact(text).text


@pytest.mark.parametrize(
    "text",
    [
        "Mama Wanjiku alirudishwa bila dawa",
        "Mzee Otieno hawezi kutembea",
        "jina lake ni achieng na mtoto wake",
        "her name is Mary Atieno",
        "anaitwa kamau",
        "Bi. Akinyi alilipa",
        "mtoto wa Juma ana homa",
    ],
)
def test_names_are_masked(text):
    out = redact(text)
    assert NAME in out.text
    assert out.masked >= 1


def test_lowercase_honorific_without_name_is_left_alone():
    assert redact("mama mjamzito hakupata huduma").text == "mama mjamzito hakupata huduma"


def test_email_masked_and_empty_text():
    assert "[EMAIL]" in redact("write to chp@example.org").text
    assert redact(None).text == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0712345678", "+254712345678"),
        ("0712 345 678", "+254712345678"),
        ("254712345678", "+254712345678"),
        ("+254 112 345 678", "+254112345678"),
        ("712345678", "+254712345678"),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["", "12345", "+255712345678", "0812345678"])
def test_normalize_phone_rejects(raw):
    with pytest.raises(InvalidPhone):
        normalize_phone(raw)


def test_pseudonym_is_stable_and_opaque():
    assert pseudonym(5) == pseudonym(5)
    assert pseudonym(5) != pseudonym(6)
    assert pseudonym(5).startswith("CHP-")
    assert len(pseudonym(5)) == len("CHP-") + 6
