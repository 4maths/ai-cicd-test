import pytest
from app import multiply, divide, get_user_email


def test_multiply():
    assert multiply(2, 3) == 6

def test_divide_by_zero():
    with pytest.raises(ValueError, match="Không thể chia cho 0"):
        divide(10, 0)


def test_get_user_email():
    assert get_user_email("user") == "user@example.com"


def test_get_user_email_empty_username():
    assert get_user_email("") == "@example.com"
api_key = "fake-test-secret"