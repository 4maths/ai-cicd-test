"""
ai_engine.py — LLM API wrapper cho AI CI/CD Assistant.

Chi dung: Gemini 1.5 Flash.
Tat ca du lieu dau vao phai qua sanitize_data truoc khi gui len API.
"""

import os
import re
import json
import logging
import requests
import time
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
# Gemini API (Model name tu env)
# ---------------------------------------------------------------------------

def call_gemini(prompt: str, max_tokens: int = 1000) -> Optional[str]:
    """
    Goi Gemini API va tra ve phan hoi dang chuoi.

    Model name duoc lay tu LLM_MODEL env variable.
    Co retry logic cho 429 (rate limit) errors.
    Doc tham khao: https://ai.google.dev/gemini-api/docs/models/gemini

    Args:
        prompt: Noi dung prompt da duoc sanitize.
        max_tokens: Gioi han so token trong phan hoi.

    Returns:
        Chuoi ket qua tu model, hoac None neu that bai.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    model_name = os.getenv("LLM_MODEL", "gemini-2.0-flash")
    
    if not api_key:
        logger.error("GEMINI_API_KEY chua duoc thiet lap.")
        return None

    api_url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.2,
        },
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(
                f"{api_url}?key={api_key}",
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
            if exc.response.status_code == 429:  # Rate limit
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) + 1  # Exponential backoff: 2s, 5s, 9s
                    logger.warning("Rate limit (429). Retry sau %ds...", wait_time)
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error("Vua het so lan retry cho rate limit. Gemini HTTP error: %s", exc)
                    return None
            else:
                logger.error("Gemini HTTP error: %s", exc)
                return None
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            logger.error("Khong the parse phan hoi Gemini: %s", exc)
            return None
    
    return None



# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def call_llm(prompt: str, max_tokens: int = 1000) -> Optional[str]:
    """
    Goi Gemini API (model tu LLM_MODEL env).

    Du lieu dau vao se duoc sanitize truoc khi gui.

    Args:
        prompt: Noi dung prompt chua sanitize.
        max_tokens: Gioi han so token trong phan hoi.

    Returns:
        Chuoi ket qua tu model, hoac None neu that bai.
    """
    clean_prompt = sanitize_data(prompt)

    logger.info("Dang goi Gemini...")
    result = call_gemini(clean_prompt, max_tokens)
    if result:
        logger.info("Gemini thanh cong.")
        return result

    logger.error("Gemini that bai.")
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
