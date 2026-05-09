"""
run_production.py
تشغيل إنتاجي موصى به (بدون Flask dev server)
"""
import os

from modules import create_app


def main() -> None:
    app = create_app()

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5001"))
    threads = int(os.environ.get("WAITRESS_THREADS", "16"))

    try:
        from waitress import serve
    except ImportError as exc:
        raise RuntimeError(
            "waitress غير مثبتة. ثبّت الحزمة: pip install waitress"
        ) from exc

    conn_limit     = int(os.environ.get("WAITRESS_CONNECTION_LIMIT", "2000"))
    channel_timeout = int(os.environ.get("WAITRESS_CHANNEL_TIMEOUT", "120"))
    cleanup_interval = int(os.environ.get("WAITRESS_CLEANUP_INTERVAL", "30"))
    backlog = int(os.environ.get("WAITRESS_BACKLOG", "2048"))
    recv_bytes = int(os.environ.get("WAITRESS_RECV_BYTES", "8192"))
    send_bytes = int(os.environ.get("WAITRESS_SEND_BYTES", "18000"))
    outbuf_overflow = int(os.environ.get("WAITRESS_OUTBUF_OVERFLOW", "1048576"))
    inbuf_overflow = int(os.environ.get("WAITRESS_INBUF_OVERFLOW", "524288"))

    serve(
        app,
        host=host,
        port=port,
        threads=threads,
        backlog=backlog,
        recv_bytes=recv_bytes,
        send_bytes=send_bytes,
        connection_limit=conn_limit,
        channel_timeout=channel_timeout,
        cleanup_interval=cleanup_interval,
        outbuf_overflow=outbuf_overflow,
        inbuf_overflow=inbuf_overflow,
        expose_tracebacks=False,
        # إيقاف تشفير الـ headers الوارد لتسريع المعالجة
        asyncore_use_poll=True,
    )


if __name__ == "__main__":
    main()
