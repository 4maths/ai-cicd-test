"""
ai_engine.py — LLM API wrapper cho AI CI/CD Assistant.

Ho tro: Gemini 1.5 Flash (chinh), Groq/Llama 3 (fallback).
Tat ca du lieu dau vao phai qua sanitize_data truoc khi gui len API.
"""

import os
import re
import json
import logging
import requests
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

def sanitize_data(text: str) -> str:
    """
    Che giau thong tin nhay cam truoc khi gui len LLM API.
    BAT BUOC chay truoc moi API call.

    Args:
        text: Noi dung can kiem tra va lam sach.

    Returns:
        Chuoi da duoc che giau cac thong tin nhay cam.
    """
    # Xoa IP address
    text = re.sub(
        r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
        '[IP_REDACTED]',
        text
    )
    # Xoa email
    text = re.sub(
        r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        '[EMAIL_REDACTED]',
        text
    )
    # Xoa AWS credentials
    text = re.sub(
        r'(AKIA|ASIA)[A-Z0-9]{16}',
        '[AWS_KEY_REDACTED]',
        text
    )
    # Xoa token/secret dang key=value
    text = re.sub(
        r'(?i)(token|secret|password|api_key|apikey)\s*=\s*\S+',
        r'\1=[REDACTED]',
        text
    )
    return text


# ---------------------------------------------------------------------------
# Gemini 1.5 Flash
# ---------------------------------------------------------------------------

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-1.5-flash:generateContent"
)


def call_gemini(prompt: str, max_tokens: int = 1000) -> Optional[str]:
    """
    Goi Gemini 1.5 Flash API va tra ve phan hoi dang chuoi.

    Args:
        prompt: Noi dung prompt da duoc sanitize.
        max_tokens: Gioi han so token trong phan hoi.

    Returns:
        Chuoi ket qua tu model, hoac None neu that bai.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY chua duoc thiet lap.")
        return None

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.2,
        },
    }

    try:
        response = requests.post(
            f"{GEMINI_API_URL}?key={api_key}",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except requests.exceptions.Timeout:
        logger.error("Gemini API timeout sau 30 giay.")
        return None
    except requests.exceptions.HTTPError as exc:
        logger.error("Gemini HTTP error: %s", exc)
        return None
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        logger.error("Khong the parse phan hoi Gemini: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Groq / Llama 3 (fallback)
# ---------------------------------------------------------------------------

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama3-70b-8192"


def call_groq(prompt: str, max_tokens: int = 1000) -> Optional[str]:
    """
    Goi Groq API (Llama 3) va tra ve phan hoi dang chuoi.

    Args:
        prompt: Noi dung prompt da duoc sanitize.
        max_tokens: Gioi han so token trong phan hoi.

    Returns:
        Chuoi ket qua tu model, hoac None neu that bai.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        logger.error("GROQ_API_KEY chua duoc thiet lap.")
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }

    try:
        response = requests.post(
            GROQ_API_URL,
            headers=headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except requests.exceptions.Timeout:
        logger.error("Groq API timeout sau 30 giay.")
        return None
    except requests.exceptions.HTTPError as exc:
        logger.error("Groq HTTP error: %s", exc)
        return None
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        logger.error("Khong the parse phan hoi Groq: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public interface — tu dong fallback
# ---------------------------------------------------------------------------

def call_llm(prompt: str, max_tokens: int = 1000) -> Optional[str]:
    """
    Goi LLM voi fallback tu dong: Gemini -> Groq.

    Du lieu dau vao se duoc sanitize truoc khi gui.

    Args:
        prompt: Noi dung prompt chua sanitize.
        max_tokens: Gioi han so token trong phan hoi.

    Returns:
        Chuoi ket qua tu model, hoac None neu ca hai deu that bai.
    """
    clean_prompt = sanitize_data(prompt)

    logger.info("Dang goi Gemini 1.5 Flash...")
    result = call_gemini(clean_prompt, max_tokens)
    if result:
        logger.info("Gemini thanh cong.")
        return result

    logger.warning("Gemini that bai, chuyen sang Groq...")
    result = call_groq(clean_prompt, max_tokens)
    if result:
        logger.info("Groq thanh cong.")
        return result

    logger.error("Ca Gemini va Groq deu that bai.")
    return None


def parse_json_response(raw: str) -> Optional[dict]:
    """
    Parse chuoi JSON tra ve tu LLM, xu ly truong hop co markdown fence.

    Args:
        raw: Chuoi phan hoi thô tu model.

    Returns:
        dict neu parse thanh cong, None neu that bai.
    """
    # Loai bo markdown code fence neu co
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error("JSON parse that bai: %s\nRaw response: %s", exc, raw[:200])
        return None
