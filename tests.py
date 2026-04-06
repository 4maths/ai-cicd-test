"""
Test file đơn giản để demo CI/CD
"""


def add(a: int, b: int) -> int:
    """Cộng hai số"""
    return a + b


def subtract(a: int, b: int) -> int:
    """Trừ hai số"""
    return a - b


def test_add():
    """Test hàm add"""
    assert add(1, 2) == 3
    assert add(0, 0) == 0
    assert add(-1, 1) == 0


def test_subtract():
    """Test hàm subtract"""
    assert subtract(5, 3) == 2
    assert subtract(0, 0) == 0
    assert subtract(-1, 1) == -2
    assert subtract(10, 5) == 1
    