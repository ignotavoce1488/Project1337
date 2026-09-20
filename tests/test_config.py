import pytest
from pydantic import ValidationError

from slovech.core.config import Settings


@pytest.mark.parametrize(
    "values",
    [
        {"environment": "prod"},
        {"environment": "production", "domain": "http://example.com"},
        {"environment": "production", "domain": "https://example.com", "bot_token": ""},
        {"domain": "https://user:password@example.com"},
        {"domain": "https://example.com/path"},
        {"auth_max_age": 0},
        {"max_upload_bytes": -1},
        {"admin_secret": "short"},
    ],
)
def test_invalid_configuration_fails(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_import_configuration_does_not_create_directories(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", audio_dir=tmp_path / "audio")
    assert not settings.data_dir.exists()
    settings.prepare()
    assert settings.data_dir.is_dir()


def test_validation_errors_do_not_echo_secrets():
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, environment="invalid", bot_token="private-token")
    assert "private-token" not in str(error.value)


def test_log_formatter_redacts_configured_credentials():
    import logging

    from slovech.core.logging import JsonFormatter

    record = logging.LogRecord(
        "test", logging.ERROR, __file__, 1, "Failed URL?key=%s", ("secret",), None
    )
    assert "secret" not in JsonFormatter(["secret"]).format(record)
