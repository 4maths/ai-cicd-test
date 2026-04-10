import json
import logging
import os
import re
import time
from typing import Optional

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def sanitize_data(text: str) -> str:
    """
    Che bớt dữ liệu nhạy cảm trước khi gửi prompt ra ngoài.
    """
    if not text:
        return text

    # Xóa IP address
    text = re.sub(
        r"\b\d{1,3}(?:\.\d{1,3}){3}\b",
        "[IP_REDACTED]",
        text,
    )

    # Xóa email
    text = re.sub(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        "[EMAIL_REDACTED]",
        text,
    )

    # Xóa AWS access key
    text = re.sub(
        r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        "[AWS_KEY_REDACTED]",
        text,
    )

    # Xóa bearer token
    text = re.sub(
        r"(?i)\bBearer\s+[A-Za-z0-9._\-]+\b",
        "Bearer [REDACTED]",
        text,
    )

    # Xóa token/secret/password/api_key dạng key=value hoặc key: value
    text = re.sub(
        r"(?i)\b(token|secret|password|api_key|apikey|access_token|refresh_token|github_token)\b\s*[:=]\s*['\"]?\S+['\"]?",
        r"\1=[REDACTED]",
        text,
    )

    return text


def call_groq(prompt: str, max_tokens: int = 1000) -> Optional[str]:
    """
    Gọi Groq Chat Completions API và trả về nội dung text từ model.
    """
    api_key = os.getenv("GROQ_API_KEY", "")
    model_name = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

    if not api_key:
        logger.error("GROQ_API_KEY chưa được thiết lập.")
        return None

    logger.debug("Groq API config: model=%s", model_name)

    api_url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "max_completion_tokens": max_tokens,
        "temperature": 0.2,
    }

    max_retries = 3

    for attempt in range(max_retries):
        try:
            response = requests.post(
                api_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()

            choices = data.get("choices")
            if not choices or not isinstance(choices, list):
                logger.error("Phản hồi Groq không có trường 'choices' hợp lệ: %s", str(data)[:300])
                return None

            message = choices[0].get("message", {})
            content = message.get("content")
            if not content:
                logger.error("Phản hồi Groq không chứa nội dung message.content hợp lệ.")
                return None

            return content

        except requests.exceptions.Timeout:
            logger.error("Groq API timeout sau 30 giây.")
            return None

        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None

            if status_code == 429:
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) + 1
                    logger.warning("Rate limit (429). Retry sau %d giây...", wait_time)
                    time.sleep(wait_time)
                    continue

                logger.error("Hết số lần retry vì rate limit (429): %s", exc)
                return None

            logger.error("Groq HTTP error: %s", exc)
            return None

        except (KeyError, IndexError, json.JSONDecodeError, ValueError) as exc:
            logger.error("Không thể parse phản hồi Groq: %s", exc)
            return None

        except requests.exceptions.RequestException as exc:
            logger.error("Lỗi request tới Groq: %s", exc)
            return None

    return None


def call_llm(prompt: str, max_tokens: int = 1000) -> Optional[str]:
    """
    Hàm wrapper chung để sanitize dữ liệu rồi gọi LLM provider.
    """
    clean_prompt = sanitize_data(prompt)

    logger.info("Đang gọi Groq.")
    result = call_groq(clean_prompt, max_tokens=max_tokens)

    if result:
        logger.info("Groq trả kết quả thành công.")
        return result

    logger.error("Groq thất bại.")
    return None


def parse_json_response(raw: str) -> Optional[dict]:
    """
    Parse phản hồi text từ LLM thành JSON object.

    Hỗ trợ cả trường hợp model bọc JSON trong code fence hoặc chèn text thừa
    trước/sau object JSON.
    """
    if not raw:
        return None

    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        candidate = match.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            logger.error("JSON parse thất bại sau fallback: %s\nRaw response: %s", exc, raw[:300])
            return None

    logger.error("JSON parse thất bại. Raw response: %s", raw[:300])
    return None