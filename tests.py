import pytest
from app import multiply, divide, get_user_email


def test_multiply():
    assert multiply(2, 3) == 6


def test_multiply_with_zero():
    assert multiply(5, 0) == 0


def test_multiply_negative():
    assert multiply(-2, 3) == -6


def test_divide():
    assert divide(10, 2) == 5


def test_divide_float():
    assert divide(7, 2) == 10


def test_divide_by_zero():
    with pytest.raises(ValueError, match="Không thể chia cho 0"):
        divide(10, 0)


def test_get_user_email():
    assert get_user_email("user") == "user@example.com"


def test_get_user_email_empty_username():
    assert get_user_email("") == "@example.com"