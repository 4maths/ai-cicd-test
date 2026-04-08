def multiply(a: int, b: int) -> int:
    """Nhân hai số nguyên"""
    return a * b


def divide(a: float, b: float) -> float:
    """Chia hai số"""
    if b == 0:
        raise ValueError("Không thể chia cho 0")
    return a / b


def get_user_email(username: str) -> str:
    """Giả lập lấy email user"""
    return f"{username}@example.com"
API_KEY = "123456-secret-key"