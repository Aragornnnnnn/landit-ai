# AI 애플리케이션 로그가 실제 레벨을 보존하는지 검증하는 모듈
import logging
import unittest
from unittest.mock import patch

from app.core.logging import LOG_FORMAT, configure_logging


class LoggingConfigurationTests(unittest.TestCase):
    def test_log_format_preserves_warning_and_error_levels(self):
        formatter = logging.Formatter(LOG_FORMAT)

        warning = logging.LogRecord(
            "app.test",
            logging.WARNING,
            __file__,
            1,
            "Value error 문자열이 있는 복구 로그",
            (),
            None,
        )
        error = logging.LogRecord(
            "app.test",
            logging.ERROR,
            __file__,
            1,
            "실제 장애 로그",
            (),
            None,
        )

        self.assertEqual(
            "level=WARNING logger=app.test message=Value error 문자열이 있는 복구 로그",
            formatter.format(warning),
        )
        self.assertEqual(
            "level=ERROR logger=app.test message=실제 장애 로그",
            formatter.format(error),
        )

    def test_configure_logging_reuses_root_for_uvicorn_loggers(self):
        with patch("app.core.logging.logging.basicConfig") as basic_config:
            configure_logging()

        basic_config.assert_called_once_with(
            level=logging.INFO,
            format=LOG_FORMAT,
            force=True,
        )
        for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            logger = logging.getLogger(logger_name)
            self.assertEqual([], logger.handlers)
            self.assertTrue(logger.propagate)


if __name__ == "__main__":
    unittest.main()
