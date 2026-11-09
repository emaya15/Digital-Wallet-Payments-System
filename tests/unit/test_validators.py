import pytest

from app.utils.validators import (
    is_simple_pin,
    is_valid_account_number,
    is_valid_ifsc,
    is_valid_pan,
    mask_account_number,
    mask_pan,
    mask_phone,
    normalize_phone,
    validate_password_strength,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("9876543210", "9876543210"),
        ("+919876543210", "9876543210"),
        ("91 98765 43210", "9876543210"),
        ("09876543210", "9876543210"),
        ("9123456789", "9123456789"),
    ],
)
def test_normalize_phone_valid(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["", "12345", "5876543210", "98765432101", "abcdefghij"])
def test_normalize_phone_invalid(raw):
    with pytest.raises(ValueError):
        normalize_phone(raw)


def test_pan_validation():
    assert is_valid_pan("ABCDE1234F")
    assert not is_valid_pan("abcde1234f")
    assert not is_valid_pan("ABCDE12345")
    assert not is_valid_pan("ABCD1234EF")


def test_ifsc_validation():
    assert is_valid_ifsc("HDFC0001234")
    assert is_valid_ifsc("SBIN0A12345")
    assert not is_valid_ifsc("HDFC1001234")
    assert not is_valid_ifsc("HDF0001234")
    assert not is_valid_ifsc("hdfc0001234")


def test_account_number_validation():
    assert is_valid_account_number("123456789012")
    assert not is_valid_account_number("12345678")  # too short
    assert not is_valid_account_number("1234567890123456789")  # too long
    assert not is_valid_account_number("111111111111")  # all same digit
    assert not is_valid_account_number("12345abc9012")


@pytest.mark.parametrize(
    "pin", ["0000", "1111", "1234", "4321", "0123", "6789", "1212", "1122", "2468", "1357", "2580"]
)
def test_simple_pins_rejected(pin):
    assert is_simple_pin(pin)


@pytest.mark.parametrize("pin", ["4826", "7391", "1359", "9042", "5017"])
def test_strong_pins_accepted(pin):
    assert not is_simple_pin(pin)


@pytest.mark.parametrize("pin", ["123", "12345", "abcd", ""])
def test_malformed_pin_counts_as_simple(pin):
    assert is_simple_pin(pin)


def test_password_strength():
    assert validate_password_strength("Passw0rd!") == "Passw0rd!"
    for bad in ["short1", "allletters", "12345678"]:
        with pytest.raises(ValueError):
            validate_password_strength(bad)


def test_masking():
    assert mask_phone("9876543210") == "98XXXXXX10"
    assert mask_account_number("4321") == "XXXXXXXX4321"
    assert mask_pan("ABCDE1234F") == "XXXXXX234F"
