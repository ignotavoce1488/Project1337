import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def __init__(self, secrets=()):
        super().__init__()
        self.secrets = tuple(secret for secret in secrets if secret)

    def format(self, record):
        # Exception text/tracebacks may include provider URLs containing credentials.
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "[REDACTED]")
        item = {
            "time": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }
        if record.exc_info:
            item["exception_type"] = record.exc_info[0].__name__
        return json.dumps(item, ensure_ascii=False)


def configure_logging():
    handler = logging.StreamHandler()
    from slovech.core.config import get_settings

    settings = get_settings()
    secrets = [
        settings.bot_token.get_secret_value(),
        settings.admin_secret.get_secret_value(),
        settings.openrouter_api_key.get_secret_value(),
        *settings.gemini_api_keys.get_secret_value().split(","),
    ]
    handler.setFormatter(JsonFormatter(secret.strip() for secret in secrets))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    for name in ("httpx", "httpcore", "aiogram.event"):
        logging.getLogger(name).setLevel(logging.WARNING)
