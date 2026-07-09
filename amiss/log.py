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
        # Add the log level and a timestamp to the event_dict if the log entry
        # is not from structlog.
        structlog.stdlib.add_log_level,
        # Add extra attributes of LogRecord objects to the event dictionary
        # so that values passed in the extra parameter of log methods pass
        # through to log output.
        # structlog.stdlib.ExtraAdder(), # disabled to remove color_message= from uvicorn logs
        timestamper,
    ]

    # def extract_from_record(_, __, event_dict):
    #     """Extract thread and process names and add them to the event dict."""
    #     record = event_dict["_record"]
    #     event_dict["thread_name"] = record.threadName
    #     event_dict["process_name"] = record.processName
    #     return event_dict

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
                        # extract_from_record,
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

    # logging.getLogger("uvicorn.error").disabled = True
    # logging.getLogger("uvicorn.access").disabled = True

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.PositionalArgumentsFormatter(),
            timestamper,
            structlog.processors.StackInfoRenderer(),
            # structlog.processors.format_exc_info,  # structlog.dev.ConsoleRenderer now formats exceptions itself
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
