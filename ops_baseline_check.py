import argparse
import json
import sqlite3
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Tuple

from modules.config import DB_PATH


def _http_get(url: str, timeout: float = 5.0) -> Dict[str, object]:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="ignore")
            status = int(response.getcode())
        elapsed_ms = (time.perf_counter() - started) * 1000
        return {
            "ok": True,
            "status": status,
            "latency_ms": round(elapsed_ms, 2),
            "body": body,
        }
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return {
            "ok": False,
            "status": None,
            "latency_ms": round(elapsed_ms, 2),
            "error": str(exc),
        }


def _safe_instant_check(raw: Dict[str, object], include_body: bool) -> Dict[str, object]:
    out = {
        "ok": raw.get("ok"),
        "status": raw.get("status"),
        "latency_ms": raw.get("latency_ms"),
    }
    if include_body and "body" in raw:
        out["body"] = raw.get("body")
    if "error" in raw:
        out["error"] = raw.get("error")
    return out


def _load_probe(base_url: str, path: str, requests_count: int, workers: int) -> Dict[str, object]:
    latencies = []
    statuses: Dict[str, int] = {}
    failures = 0
    started = time.perf_counter()

    def hit() -> Tuple[bool, int, float]:
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(f"{base_url}{path}", timeout=5.0) as response:
                response.read(64)
                code = int(response.getcode())
            return True, code, (time.perf_counter() - t0) * 1000
        except urllib.error.HTTPError as exc:
            return False, int(exc.code), (time.perf_counter() - t0) * 1000
        except Exception:
            return False, -1, (time.perf_counter() - t0) * 1000

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(hit) for _ in range(requests_count)]
        for future in as_completed(futures):
            ok, status, elapsed = future.result()
            latencies.append(elapsed)
            key = str(status)
            statuses[key] = statuses.get(key, 0) + 1
            if not ok:
                failures += 1

    latencies.sort()
    duration = time.perf_counter() - started

    def p95(values):
        if not values:
            return 0.0
        idx = int(0.95 * (len(values) - 1))
        return values[idx]

    return {
        "requests": requests_count,
        "workers": workers,
        "ok": requests_count - failures,
        "failed": failures,
        "rps": round(requests_count / duration, 2) if duration > 0 else 0.0,
        "latency_ms": {
            "min": round(min(latencies), 2) if latencies else 0.0,
            "avg": round(statistics.mean(latencies), 2) if latencies else 0.0,
            "p95": round(p95(latencies), 2),
            "max": round(max(latencies), 2) if latencies else 0.0,
        },
        "statuses": statuses,
    }


def _stuck_state_check() -> Dict[str, object]:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        queries = {
            "pending_approvals": "SELECT COUNT(*) FROM approval_requests WHERE status='pending'",
            "stale_pending_approvals_24h": (
                "SELECT COUNT(*) FROM approval_requests "
                "WHERE status='pending' "
                "AND ((julianday('now')-julianday(requested_at))*24)>=24"
            ),
            "queue_pending": "SELECT COUNT(*) FROM execution_queue WHERE status='pending'",
            "queue_failed": "SELECT COUNT(*) FROM execution_queue WHERE status='failed'",
            "unread_notifications": "SELECT COUNT(*) FROM notifications WHERE is_read=0",
        }
        out: Dict[str, object] = {}
        for key, sql in queries.items():
            try:
                out[key] = int(conn.execute(sql).fetchone()[0])
            except Exception as exc:
                out[key] = f"error: {exc}"
        return out
    finally:
        conn.close()


def _is_zero_stuck(stuck_state: Dict[str, object]) -> bool:
    for value in stuck_state.values():
        if not isinstance(value, int):
            return False
        if value != 0:
            return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Operational baseline check: health/ready, load probe, stuck-state."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:5001", help="Backend base URL")
    parser.add_argument("--health-requests", type=int, default=200)
    parser.add_argument("--health-workers", type=int, default=20)
    parser.add_argument("--ready-requests", type=int, default=100)
    parser.add_argument("--ready-workers", type=int, default=10)
    parser.add_argument("--include-bodies", action="store_true", help="Include instant check response bodies")
    parser.add_argument("--output", default="", help="Optional report file path (json)")
    parser.add_argument("--max-health-p95-ms", type=float, default=50.0)
    parser.add_argument("--max-ready-p95-ms", type=float, default=170.0)
    parser.add_argument("--max-failures", type=int, default=0)
    parser.add_argument("--require-zero-stuck", action="store_true")
    args = parser.parse_args()

    output: Dict[str, object] = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "base_url": args.base_url,
    }

    instant_health = _http_get(f"{args.base_url}/healthz")
    instant_ready = _http_get(f"{args.base_url}/readyz")
    output["instant_checks"] = {
        "healthz": _safe_instant_check(instant_health, include_body=args.include_bodies),
        "readyz": _safe_instant_check(instant_ready, include_body=args.include_bodies),
    }

    can_probe = output["instant_checks"]["healthz"].get("ok") and output["instant_checks"]["readyz"].get("ok")
    if can_probe:
        output["load_probe"] = {
            "/healthz": _load_probe(
                args.base_url,
                "/healthz",
                requests_count=args.health_requests,
                workers=args.health_workers,
            ),
            "/readyz": _load_probe(
                args.base_url,
                "/readyz",
                requests_count=args.ready_requests,
                workers=args.ready_workers,
            ),
        }
    else:
        output["load_probe"] = {
            "skipped": "healthz/readyz not reachable; start backend then rerun"
        }

    output["stuck_state"] = _stuck_state_check()

    verdict = {
        "pass": True,
        "reasons": [],
        "thresholds": {
            "max_health_p95_ms": args.max_health_p95_ms,
            "max_ready_p95_ms": args.max_ready_p95_ms,
            "max_failures": args.max_failures,
            "require_zero_stuck": bool(args.require_zero_stuck),
        },
    }

    if not instant_health.get("ok"):
        verdict["pass"] = False
        verdict["reasons"].append("healthz instant check failed")
    if not instant_ready.get("ok"):
        verdict["pass"] = False
        verdict["reasons"].append("readyz instant check failed")

    if isinstance(output.get("load_probe"), dict) and "/healthz" in output["load_probe"] and "/readyz" in output["load_probe"]:
        h = output["load_probe"]["/healthz"]
        r = output["load_probe"]["/readyz"]
        total_failed = int(h.get("failed", 0)) + int(r.get("failed", 0))
        if total_failed > args.max_failures:
            verdict["pass"] = False
            verdict["reasons"].append(f"load failures exceeded threshold: {total_failed} > {args.max_failures}")

        health_p95 = float(h.get("latency_ms", {}).get("p95", 0.0))
        ready_p95 = float(r.get("latency_ms", {}).get("p95", 0.0))
        if health_p95 > args.max_health_p95_ms:
            verdict["pass"] = False
            verdict["reasons"].append(
                f"healthz p95 exceeded threshold: {health_p95}ms > {args.max_health_p95_ms}ms"
            )
        if ready_p95 > args.max_ready_p95_ms:
            verdict["pass"] = False
            verdict["reasons"].append(
                f"readyz p95 exceeded threshold: {ready_p95}ms > {args.max_ready_p95_ms}ms"
            )

    if args.require_zero_stuck and not _is_zero_stuck(output["stuck_state"]):
        verdict["pass"] = False
        verdict["reasons"].append("stuck_state is not all-zero")

    output["verdict"] = verdict

    report_json = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(report_json, encoding="utf-8")

    print(report_json)

    if not verdict["pass"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
