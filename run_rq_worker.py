"""
run_rq_worker.py
تشغيل عامل RQ للمهام الخلفية عند QUEUE_BACKEND=rq.
"""
import os


def main() -> None:
    redis_url = os.environ.get("REDIS_URL", "")
    queue_name = os.environ.get("RQ_DEFAULT_QUEUE", "default")

    if not redis_url:
        raise RuntimeError("REDIS_URL غير مضبوط. لا يمكن تشغيل RQ Worker.")

    try:
        import redis
        from rq import Connection, Worker
    except ImportError as exc:
        raise RuntimeError("الحزم rq/redis غير مثبتة. نفّذ: pip install -r requirements.txt") from exc

    conn = redis.Redis.from_url(redis_url)
    with Connection(conn):
        worker = Worker([queue_name])
        worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
