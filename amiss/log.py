# Copyright 2024-2025 SURF.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from logging import Filter, LogRecord, config, getLogger

import structlog

from amiss.settings import settings


class UvicornAccessLogFilter(Filter):
    """Uvicorn's access log filter."""

    def filter(self, record: LogRecord) -> bool:
        """Filter out messages for certain endpoints.

        Currently only filter out /healthcheck access messages.
        """
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            if record.args[2] in ["/healthcheck"]:
                return False
        return True


def init() -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso")
    pre_chain = [
        # add the log level and a timestamp to non-structlog log entries
        structlog.stdlib.add_log_level,
        timestamper,
    ]

    config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": True,
            "formatters": {
                "plain": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "processors": [
                        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                        structlog.dev.ConsoleRenderer(colors=False),
                    ],
                    "foreign_pre_chain": pre_chain,
                },
                "colored": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "processors": [
                        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                        structlog.dev.ConsoleRenderer(colors=True),
                    ],
                    "foreign_pre_chain": pre_chain,
                },
            },
            "handlers": {
                "default": {
                    "level": "DEBUG",
                    "class": "logging.StreamHandler",
                    "formatter": "colored",
                },
                "file": {
                    "level": "DEBUG",
                    "class": "logging.handlers.WatchedFileHandler",
                    "filename": "amiss.log",
                    "formatter": "plain",
                },
            },
            "loggers": {
                "": {
                    "handlers": ["default", "file"],
                    "level": settings.LOG_LEVEL,
                    "propagate": True,
                },
                "uvicorn.access": {
                    "handlers": ["default", "file"],
                    "level": settings.LOG_LEVEL,
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": ["default", "file"],
                    "level": settings.LOG_LEVEL,
                    "propagate": False,
                },
            },
        }
    )

    uvicorn_access_logger = getLogger("uvicorn.access")
    uvicorn_access_logger.addFilter(UvicornAccessLogFilter())

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.PositionalArgumentsFormatter(),
            timestamper,
            structlog.processors.StackInfoRenderer(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
