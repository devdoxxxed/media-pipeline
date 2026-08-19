from app.analysis.plate import _find_plate


def test_valid_plate():
    assert _find_plate("Vehicle registration KA01AB1234") == "KA01AB1234"


def test_invalid_plate():
    assert _find_plate("Vehicle registration INVALID123") is None


def test_date_is_not_plate():
    assert _find_plate("Tuesday 17 FEB 2026") is None