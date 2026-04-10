from __future__ import annotations

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)


def build_result(
    target_url: str,
    status_code: int | None,
    latency_ms: int | None,
    health_status: str,
    decision: str,
    summary: str,
    checks: list[str],
) -> dict:
    return {
        "target_url": target_url,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "health_status": health_status,
        "decision": decision,
        "summary": summary,
        "checks": checks,
    }


def format_guard_report(result: dict) -> str:
    checks_text = "\n".join(f"- {item}" for item in result.get("checks", []))

    return f"""## AI Deploy Guard

**Decision:** {result.get("decision", "UNKNOWN")}  
**Target URL:** {result.get("target_url", "N/A")}  
**Status code:** {result.get("status_code", "N/A")}  
**Latency:** {result.get("latency_ms", "N/A")} ms  
**Health status:** {result.get("health_status", "unknown")}  

### Summary
{result.get("summary", "Không có tóm tắt.")}

### Checks
{checks_text if checks_text else "- Không có check nào."}
"""


def run_deploy_guard() -> int:
    target_url = os.getenv("DEPLOY_GUARD_URL", "").strip()
    timeout_str = os.getenv("DEPLOY_GUARD_TIMEOUT", "5").strip()
    max_latency_str = os.getenv("DEPLOY_GUARD_MAX_LATENCY_MS", "1000").strip()
    expect_text = os.getenv("DEPLOY_GUARD_EXPECT_TEXT", "").strip()

    if not target_url:
        logger.error("Thiếu biến môi trường DEPLOY_GUARD_URL.")
        return 1

    try:
        timeout = float(timeout_str)
    except ValueError:
        logger.error("DEPLOY_GUARD_TIMEOUT không hợp lệ: %s", timeout_str)
        return 1

    try:
        max_latency_ms = int(max_latency_str)
    except ValueError:
        logger.error("DEPLOY_GUARD_MAX_LATENCY_MS không hợp lệ: %s", max_latency_str)
        return 1

    logger.info("Bắt đầu kiểm tra deploy cho URL: %s", target_url)

    checks: list[str] = []

    try:
        start = time.perf_counter()
        response = requests.get(target_url, timeout=timeout)
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        status_code = response.status_code
        body_text = response.text.strip()

        if status_code == 200:
            checks.append("Health endpoint trả về HTTP 200.")
        else:
            checks.append(f"Health endpoint trả về HTTP {status_code}.")

        checks.append(f"Latency đo được: {elapsed_ms} ms.")

        if elapsed_ms > max_latency_ms:
            checks.append(
                f"Latency vượt ngưỡng cho phép ({elapsed_ms} ms > {max_latency_ms} ms)."
            )
        else:
            checks.append(
                f"Latency nằm trong ngưỡng cho phép ({elapsed_ms} ms <= {max_latency_ms} ms)."
            )

        if expect_text:
            if expect_text.lower() in body_text.lower():
                checks.append(f'Body response chứa chuỗi mong đợi: "{expect_text}".')
            else:
                checks.append(f'Body response không chứa chuỗi mong đợi: "{expect_text}".')

        if status_code != 200:
            result = build_result(
                target_url=target_url,
                status_code=status_code,
                latency_ms=elapsed_ms,
                health_status="unhealthy",
                decision="BLOCK",
                summary="Service sau deploy không trả về trạng thái HTTP 200.",
                checks=checks,
            )
            print(format_guard_report(result))
            return 1

        if expect_text and expect_text.lower() not in body_text.lower():
            result = build_result(
                target_url=target_url,
                status_code=status_code,
                latency_ms=elapsed_ms,
                health_status="degraded",
                decision="WARN",
                summary="Service trả về 200 nhưng nội dung body không đúng như kỳ vọng.",
                checks=checks,
            )
            print(format_guard_report(result))
            return 0

        if elapsed_ms > max_latency_ms:
            result = build_result(
                target_url=target_url,
                status_code=status_code,
                latency_ms=elapsed_ms,
                health_status="degraded",
                decision="WARN",
                summary="Service hoạt động nhưng latency sau deploy vượt ngưỡng cho phép.",
                checks=checks,
            )
            print(format_guard_report(result))
            return 0

        result = build_result(
            target_url=target_url,
            status_code=status_code,
            latency_ms=elapsed_ms,
            health_status="healthy",
            decision="APPROVE",
            summary="Service phản hồi bình thường sau deploy.",
            checks=checks,
        )
        print(format_guard_report(result))
        return 0

    except requests.exceptions.Timeout:
        result = build_result(
            target_url=target_url,
            status_code=None,
            latency_ms=None,
            health_status="unhealthy",
            decision="BLOCK",
            summary="Health check bị timeout sau deploy.",
            checks=["Request timeout khi gọi health endpoint."],
        )
        print(format_guard_report(result))
        return 1

    except requests.exceptions.RequestException as exc:
        result = build_result(
            target_url=target_url,
            status_code=None,
            latency_ms=None,
            health_status="unhealthy",
            decision="BLOCK",
            summary="Không thể kết nối tới service sau deploy.",
            checks=[f"Lỗi request: {exc}"],
        )
        print(format_guard_report(result))
        return 1