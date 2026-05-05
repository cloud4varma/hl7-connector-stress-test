"""
HL7 Stress Test Job

Author: Datla Sai Krishna Varma
Version: 1.0
Last Updated: 05-05-2026

Description:
This script performs high-throughput stress testing by generating synthetic HL7 messages,
encoding them, and sending them to a target API endpoint using HTTP POST requests.


Key Features:
- Generates randomized HL7 ORM messages
- Base64 encodes payloads for transport
- Supports ramp-up, steady-state, and ramp-down load profiles
- Configurable requests per minute (RPM)
- Concurrent execution using thread pool
- Detailed structured logging (JSON format)
- Latency and percentile tracking (p50, p95, p99)


"""
import os
import time
import uuid
import json
import base64
import random
import requests
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor

URL = os.getenv("TARGET_URL")
TOKEN = os.getenv("HL7_BEARER_TOKEN")

DURATION_SECONDS = int(os.getenv("DURATION_SECONDS", "900"))
RAMP_UP_SECONDS = int(os.getenv("RAMP_UP_SECONDS", "300"))
HOLD_SECONDS = int(os.getenv("HOLD_SECONDS", "480"))
RAMP_DOWN_SECONDS = int(os.getenv("RAMP_DOWN_SECONDS", "120"))

MAX_RPM = int(os.getenv("MAX_RPM", "10000"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "500"))
TIMEOUT_SECONDS = int(os.getenv("TIMEOUT_SECONDS", "30"))
LOG_EACH_REQUEST = os.getenv("LOG_EACH_REQUEST", "true").lower() == "true"
PROGRESS_INTERVAL_SECONDS = int(os.getenv("PROGRESS_INTERVAL_SECONDS", "30"))


def log_json(severity, message, **fields):
    print(json.dumps({
        "severity": severity,
        "message": message,
        "service": "hl7-stress-test",
        **fields
    }), flush=True)


def hl7_ts(dt):
    return dt.strftime("%Y%m%d%H%M%S")


def current_target_rpm(elapsed):
    if elapsed < RAMP_UP_SECONDS:
        return MAX_RPM * (elapsed / RAMP_UP_SECONDS)

    if elapsed < RAMP_UP_SECONDS + HOLD_SECONDS:
        return MAX_RPM

    ramp_down_elapsed = elapsed - RAMP_UP_SECONDS - HOLD_SECONDS
    remaining_ratio = max(0, 1 - ramp_down_elapsed / RAMP_DOWN_SECONDS)
    return MAX_RPM * remaining_ratio


def build_hl7_message():
    now = datetime.now(timezone.utc)
    order_time = now - timedelta(seconds=random.randint(0, 300))

    patient_id = str(random.randint(110000000, 119999999))
    visit_id = str(random.randint(200100000, 200199999))
    placer_order = str(random.randint(4100000000, 4199999999))
    control_id = f"{random.randint(500000, 999999)}.{random.randint(10000, 99999)}"

    order_code, order_name = random.choice([
        ("LAB79", "BLOOD GAS VENOUS"),
        ("CBC", "COMPLETE BLOOD COUNT"),
        ("BMP", "BASIC METABOLIC PANEL"),
        ("CMP", "COMPREHENSIVE METABOLIC PANEL"),
        ("TROP", "TROPONIN"),
    ])

    location = random.choice([
        "WAVMMCMS 7C MED SURG",
        "WAVMMCMS ED",
        "WAVMMCMS ICU",
        "WAVMMCMS LAB",
    ])

    return "\r".join([
        f"MSH|^~\\&|EPIC|WAVMMCMS||WAVMMCMLAB|{hl7_ts(now)}||ORM^O01|{control_id}|T|2.5",
        f"PID|1||{patient_id}^^^CSMRN^MR||TESTPATIENT^QA||19690709|U|||123 TEST ST^^SEATTLE^WA^98101^US||(555)555-5555^P^H",
        f"PV1|1|IP|{location}^^^^^^WAVMMCMS||||1100199995^INPATIENT^ATTENDING^PHYSICIAN^^^^NPI",
        f"ORC|NW|{placer_order}^EPC||{visit_id}|||^^^{hl7_ts(order_time)}^^R^^||{hl7_ts(now)}|EGLABTECH11^BEAKER^EPIC",
        f"OBR|1|{placer_order}^EPC|{random.randint(1000000000, 9999999999)}^Beaker|{order_code}^{order_name}||{hl7_ts(order_time)}|||||||||1100199995^INPATIENT^ATTENDING^PHYSICIAN^^^^NPI||||||||||Lab Collect",
    ]) + "\r"


def build_payload():
    now = datetime.now(timezone.utc)
    message_id = str(uuid.uuid4())

    encoded_hl7 = base64.b64encode(
        build_hl7_message().encode("utf-8")
    ).decode("utf-8")

    return {
        "attributes": {"source": "Rhapsody", "type": "HL7"},
        "data": encoded_hl7,
        "messageId": message_id,
        "message_id": message_id,
        "publishTime": now.isoformat().replace("+00:00", "Z"),
        "publish_time": now.isoformat().replace("+00:00", "Z"),
    }


def send_request(request_number):
    payload = build_payload()

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {TOKEN}",
    }

    start = time.time()

    try:
        response = requests.post(
            URL,
            headers=headers,
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )

        latency_ms = round((time.time() - start) * 1000, 2)
        success = 200 <= response.status_code < 300

        if LOG_EACH_REQUEST or not success:
            log_json(
                "INFO" if success else "ERROR",
                "request_completed",
                request_number=request_number,
                message_id=payload["messageId"],
                status_code=response.status_code,
                latency_ms=latency_ms,
                success=success,
                response_preview=response.text[:300] if not success else "",
            )

        return success, latency_ms

    except Exception as e:
        latency_ms = round((time.time() - start) * 1000, 2)

        log_json(
            "ERROR",
            "request_failed",
            request_number=request_number,
            message_id=payload["messageId"],
            latency_ms=latency_ms,
            error=str(e),
            success=False,
        )

        return False, latency_ms


def percentile(sorted_values, pct):
    if not sorted_values:
        return None
    index = round((pct / 100) * (len(sorted_values) - 1))
    return sorted_values[index]


def main():
    if not URL:
        raise RuntimeError("TARGET_URL is required")

    if not TOKEN:
        raise RuntimeError("HL7_BEARER_TOKEN is required")

    phase_total = RAMP_UP_SECONDS + HOLD_SECONDS + RAMP_DOWN_SECONDS
    if phase_total != DURATION_SECONDS:
        raise RuntimeError(
            f"Ramp phases must equal DURATION_SECONDS. Got {phase_total}, expected {DURATION_SECONDS}."
        )

    log_json(
        "INFO",
        "stress_test_started",
        target_url=URL,
        duration_seconds=DURATION_SECONDS,
        ramp_up_seconds=RAMP_UP_SECONDS,
        hold_seconds=HOLD_SECONDS,
        ramp_down_seconds=RAMP_DOWN_SECONDS,
        max_rpm=MAX_RPM,
        max_workers=MAX_WORKERS,
        timeout_seconds=TIMEOUT_SECONDS,
        log_each_request=LOG_EACH_REQUEST,
    )

    start_time = time.time()
    request_number = 0
    scheduled_requests = 0.0
    last_progress_second = -1

    completed = 0
    success_count = 0
    failure_count = 0
    latencies = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []

        while True:
            elapsed = time.time() - start_time
            if elapsed >= DURATION_SECONDS:
                break

            rpm = current_target_rpm(elapsed)
            rps = rpm / 60.0

            scheduled_requests += rps * 0.1
            to_send = int(scheduled_requests)
            scheduled_requests -= to_send

            for _ in range(to_send):
                request_number += 1
                futures.append(executor.submit(send_request, request_number))

            current_second = int(elapsed)
            if (
                PROGRESS_INTERVAL_SECONDS > 0
                and current_second > 0
                and current_second % PROGRESS_INTERVAL_SECONDS == 0
                and current_second != last_progress_second
            ):
                last_progress_second = current_second
                log_json(
                    "INFO",
                    "progress",
                    elapsed_seconds=round(elapsed, 1),
                    current_target_rpm=round(rpm, 2),
                    submitted_requests=request_number,
                    inflight_or_pending_futures=len(futures),
                )

            time.sleep(0.1)

        log_json(
            "INFO",
            "waiting_for_inflight_requests",
            submitted_requests=request_number,
        )

        for future in futures:
            success, latency_ms = future.result()
            completed += 1
            latencies.append(latency_ms)
            if success:
                success_count += 1
            else:
                failure_count += 1

    total_time = time.time() - start_time
    sorted_latencies = sorted(latencies)

    log_json(
        "INFO",
        "stress_test_finished",
        submitted_requests=request_number,
        completed_requests=completed,
        successful=success_count,
        failed=failure_count,
        actual_duration_seconds=round(total_time, 2),
        actual_messages_per_minute=round((completed / total_time) * 60, 2) if total_time else 0,
        p50_latency_ms=percentile(sorted_latencies, 50),
        p95_latency_ms=percentile(sorted_latencies, 95),
        p99_latency_ms=percentile(sorted_latencies, 99),
    )


if __name__ == "__main__":
    main()
