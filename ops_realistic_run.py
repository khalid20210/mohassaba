import argparse
import json
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Dict, List


PUBLIC_FLOW = [
    "/",
    "/auth/login",
    "/auth/register",
    "/auth/landing-metrics",
    "/healthz",
    "/readyz",
    "/privacy-policy",
    "/terms-of-use",
]


def _percentile(sorted_values: List[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    idx = int(q * (len(sorted_values) - 1))
    return sorted_values[idx]


def _new_session_client():
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", "ops-realistic-run/1.0")]
    return opener


def _single_request(opener, base_url: str, path: str, timeout: float) -> Dict[str, object]:
    started = time.perf_counter()
    try:
        with opener.open(f"{base_url}{path}", timeout=timeout) as response:
            response.read(256)
            code = int(response.getcode())
        elapsed = (time.perf_counter() - started) * 1000
        return {"ok": 200 <= code < 400, "status": code, "latency_ms": elapsed, "path": path}
    except urllib.error.HTTPError as exc:
        elapsed = (time.perf_counter() - started) * 1000
        return {"ok": False, "status": int(exc.code), "latency_ms": elapsed, "path": path}
    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000
        return {"ok": False, "status": -1, "latency_ms": elapsed, "path": path, "error": str(exc)}


def _user_journey(base_url: str, requests_per_user: int, timeout: float, think_ms: int):
    opener = _new_session_client()
    results = []
    # بداية بجولة شبه واقعية: index -> login -> landing metrics
    warmup = ["/", "/auth/login", "/auth/landing-metrics"]
    for path in warmup:
        results.append(_single_request(opener, base_url, path, timeout))

    extra = max(0, requests_per_user - len(warmup))
    for _ in range(extra):
        path = random.choice(PUBLIC_FLOW)
        results.append(_single_request(opener, base_url, path, timeout))
        if think_ms > 0:
            time.sleep(think_ms / 1000.0)
    return results


def run_simulation(base_url: str, users: int, requests_per_user: int, timeout: float, think_ms: int):
    started = time.perf_counter()
    all_results = []

    with ThreadPoolExecutor(max_workers=users) as executor:
        futures = [
            executor.submit(_user_journey, base_url, requests_per_user, timeout, think_ms)
            for _ in range(users)
        ]
        for future in as_completed(futures):
            all_results.extend(future.result())

    elapsed = time.perf_counter() - started

    by_path: Dict[str, Dict[str, object]] = {}
    status_totals: Dict[str, int] = {}
    failed = 0

    for item in all_results:
        path = str(item["path"])
        code = str(item.get("status"))
        ms = float(item.get("latency_ms") or 0.0)
        ok = bool(item.get("ok"))

        status_totals[code] = status_totals.get(code, 0) + 1
        if not ok:
            failed += 1

        bucket = by_path.setdefault(path, {"latencies": [], "total": 0, "failed": 0, "statuses": {}})
        bucket["latencies"].append(ms)
        bucket["total"] += 1
        if not ok:
            bucket["failed"] += 1
        bucket["statuses"][code] = bucket["statuses"].get(code, 0) + 1

    per_path_report = {}
    for path, bucket in by_path.items():
        latencies = sorted(bucket["latencies"])
        per_path_report[path] = {
            "requests": int(bucket["total"]),
            "failed": int(bucket["failed"]),
            "latency_ms": {
                "min": round(min(latencies), 2) if latencies else 0.0,
                "avg": round(statistics.mean(latencies), 2) if latencies else 0.0,
                "p95": round(_percentile(latencies, 0.95), 2),
                "max": round(max(latencies), 2) if latencies else 0.0,
            },
            "statuses": bucket["statuses"],
        }

    total_requests = len(all_results)
    return {
        "base_url": base_url,
        "users": users,
        "requests_per_user": requests_per_user,
        "total_requests": total_requests,
        "total_failed": failed,
        "success_rate": round(((total_requests - failed) / total_requests) * 100, 2) if total_requests else 0.0,
        "duration_sec": round(elapsed, 2),
        "rps": round(total_requests / elapsed, 2) if elapsed > 0 else 0.0,
        "statuses": status_totals,
        "by_path": per_path_report,
    }


def main():
    parser = argparse.ArgumentParser(description="Realistic multi-flow public traffic simulation.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5001")
    parser.add_argument("--users", type=int, default=30)
    parser.add_argument("--requests-per-user", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=6.0)
    parser.add_argument("--think-ms", type=int, default=30)
    parser.add_argument("--min-success-rate", type=float, default=99.0)
    parser.add_argument("--max-failed-requests", type=int, default=2)
    parser.add_argument("--max-timeout-errors", type=int, default=1)
    parser.add_argument("--output", default="", help="Optional report file path (json)")
    args = parser.parse_args()

    # تحقق أولي بسيط قبل بدء الضغط
    precheck = {}
    opener = _new_session_client()
    for path in ["/healthz", "/readyz"]:
        precheck[path] = _single_request(opener, args.base_url, path, args.timeout)

    if not precheck["/healthz"].get("ok"):
        result = {
            "precheck": precheck,
            "error": "backend health check failed; start backend then rerun",
        }
        report = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(report, encoding="utf-8")
        print(report)
        sys.exit(2)

    report = run_simulation(
        base_url=args.base_url,
        users=args.users,
        requests_per_user=args.requests_per_user,
        timeout=args.timeout,
        think_ms=args.think_ms,
    )

    timeout_errors = int(report.get("statuses", {}).get("-1", 0))
    success_rate = float(report.get("success_rate", 0.0))
    total_failed = int(report.get("total_failed", 0))

    verdict = {
        "pass": True,
        "reasons": [],
        "thresholds": {
            "min_success_rate": args.min_success_rate,
            "max_failed_requests": args.max_failed_requests,
            "max_timeout_errors": args.max_timeout_errors,
        },
    }

    if success_rate < args.min_success_rate:
        verdict["pass"] = False
        verdict["reasons"].append(
            f"success rate below threshold: {success_rate}% < {args.min_success_rate}%"
        )
    if total_failed > args.max_failed_requests:
        verdict["pass"] = False
        verdict["reasons"].append(
            f"failed requests exceeded threshold: {total_failed} > {args.max_failed_requests}"
        )
    if timeout_errors > args.max_timeout_errors:
        verdict["pass"] = False
        verdict["reasons"].append(
            f"timeout/network errors exceeded threshold: {timeout_errors} > {args.max_timeout_errors}"
        )

    output = {"precheck": precheck, "simulation": report, "verdict": verdict}
    report_json = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(report_json, encoding="utf-8")
    print(report_json)

    if not verdict["pass"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
