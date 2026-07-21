# AI와 Uvicorn 로그가 실제 로그 레벨을 출력하도록 구성하는 모듈
import logging


LOG_FORMAT = "level=%(levelname)s logger=%(name)s message=%(message)s"


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format=LOG_FORMAT,
        force=True,
    )
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        logger.propagate = True
