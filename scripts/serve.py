import uvicorn

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=8000,
        workers=1,
        ws="none",
        h11_max_incomplete_event_size=16384,
        limit_concurrency=100,
        backlog=128,
        timeout_keep_alive=5,
        timeout_graceful_shutdown=30,
        access_log=False,
        server_header=False,
        forwarded_allow_ips=",".join(settings.trusted_proxy_ips),
    )


if __name__ == "__main__":
    main()
