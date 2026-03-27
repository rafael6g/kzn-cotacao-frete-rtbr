import logging
import sys
from app.core.config import get_settings

settings = get_settings()


def setup_logging() -> None:
    level = logging.DEBUG if not settings.is_production else logging.INFO

    fmt = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt=date_fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Reduz verbosidade de libs externas
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
