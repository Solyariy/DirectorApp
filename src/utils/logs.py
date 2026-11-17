import functools
import os
import sys
import traceback

import structlog

from src.utils.order import get_log_id

# NO_COLOR (no-color.org) drops ANSI codes, e.g. in containers
RENDERER = structlog.dev.ConsoleRenderer(
    sort_keys=False,
    colors="NO_COLOR" not in os.environ,
)
TIMESTAMPER = structlog.processors.TimeStamper(fmt="%H:%M:%S")

# --- Configure structlog ---
# Events go through stdlib logging, so Django's LOGGING (logging_config)
# decides levels and output for them and for Django's own records alike.
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        TIMESTAMPER,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

main_logger = structlog.get_logger("MainLogger")


def logging_config(level: str) -> dict:
    """Django LOGGING: every record rendered by structlog to stdout."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "structlog": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processor": RENDERER,
                # Django's own (non-structlog) records get the same fields.
                "foreign_pre_chain": [
                    structlog.processors.add_log_level,
                    TIMESTAMPER,
                ],
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
                "formatter": "structlog",
            },
        },
        "root": {"handlers": ["console"], "level": level.upper()},
        "loggers": {
            # Django adds its own handlers here; keep one console output.
            "django": {"handlers": [], "propagate": True},
            # SQL queries only when explicitly asked for.
            "django.db.backends": {"level": "WARNING"},
        },
    }


def inject_traceback(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        f = sys._getframe(kwargs.get("increase_depth", 1))
        loc, line = f.f_code.co_filename, f.f_lineno
        loc = loc[loc.find("src") :]
        func(
            *args,
            **kwargs,
            msg_location=(loc, line),
        )

    return wrapper


class Logger:
    """
    basic wrapper around project logger
    use it for convenience
    """

    # @staticmethod
    # def _get_kyiv_time() -> str:
    #     tz_kyiv = ZoneInfo("Europe/Kyiv")
    #     return datetime.now(tz_kyiv).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _get_caller_name(increase_depth: int = 0) -> str:
        """Gets the name of the method that called the logger."""
        return f"[{sys._getframe(2 + increase_depth).f_code.co_name}]"

    @staticmethod
    @inject_traceback
    def info(
        msg: str,
        *,
        msg_location: tuple[str, int] = None,
        increase_depth: int = 1,
        event: str = "",
        **kwargs,
    ):
        main_logger.info(
            event
            + Logger._get_caller_name(increase_depth)
            + str(msg_location),
            log_id=get_log_id(),
            msg=msg,
            **kwargs,
        )

    @staticmethod
    @inject_traceback
    def debug(
        msg: str,
        *,
        msg_location: tuple[str, int] = None,
        increase_depth: int = 1,
        event: str = "",
        **kwargs,
    ):
        main_logger.debug(
            event
            + Logger._get_caller_name(increase_depth)
            + str(msg_location),
            log_id=get_log_id(),
            msg=msg,
            **kwargs,
        )

    @staticmethod
    @inject_traceback
    def warning(
        msg: str,
        *,
        error: Exception = None,
        msg_location: tuple[str, int] = None,
        increase_depth: int = 1,
        event: str = "",
        **kwargs,
    ):
        main_logger.warning(
            event
            + Logger._get_caller_name(increase_depth)
            + str(msg_location),
            log_id=get_log_id(),
            msg=msg,
            error=error,
            **kwargs,
        )

    @staticmethod
    @inject_traceback
    def error(
        msg: str,
        *,
        error: Exception = None,
        msg_location: tuple[str, int] = None,
        increase_depth: int = 1,
        event: str = "",
        **kwargs,
    ):
        main_logger.error(
            event
            + Logger._get_caller_name(increase_depth)
            + str(msg_location),
            log_id=get_log_id(),
            msg=msg,
            error=error,
            **kwargs,
            traceback=traceback.format_exc(),
        )


class LoggerMixin:
    @property
    def _log_prefix(self) -> str:
        class_name = self.__class__.__name__
        return f"[{class_name}]"

    def log_info(self, msg: str, **kwargs):
        Logger.info(
            event=self._log_prefix,
            msg=msg,
            increase_depth=2,
            **kwargs,
        )

    def log_warning(self, msg: str, error: Exception = None, **kwargs):
        Logger.warning(
            event=self._log_prefix,
            msg=msg,
            error=error,
            increase_depth=2,
            **kwargs,
        )

    def log_error(self, msg: str, *, error: Exception, **kwargs):
        Logger.error(
            event=self._log_prefix,
            msg=msg,
            error=error,
            increase_depth=2,
            **kwargs,
        )
