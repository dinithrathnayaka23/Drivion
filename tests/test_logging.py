import logging

from drivion.logging_setup import REDACTED, RedactingFilter, configure_logging

SECRET = "super-secret-value-42"


def test_registered_secret_is_redacted():
    f = RedactingFilter([SECRET])
    assert f.redact(f"calling API with {SECRET}") == f"calling API with {REDACTED}"


def test_key_shaped_strings_are_redacted_without_registration():
    f = RedactingFilter()
    assert "sk-abcdefghijklmnopqrstuvwx" not in f.redact("key sk-abcdefghijklmnopqrstuvwx used")
    assert "hunter2" not in f.redact("api_key=hunter2")


def test_short_secrets_are_not_used_for_redaction():
    f = RedactingFilter(["a"])
    assert f.redact("a banana") == "a banana"


def test_log_file_never_contains_secret(tmp_path):
    log_file = configure_logging("DEBUG", tmp_path / "logs", [SECRET])
    logger = logging.getLogger("drivion.test")
    logger.info("formatted arg: %s", SECRET)
    try:
        raise RuntimeError(f"provider rejected {SECRET}")
    except RuntimeError:
        logger.exception("request failed")
    for handler in logging.getLogger().handlers:
        handler.flush()

    content = log_file.read_text(encoding="utf-8")
    assert SECRET not in content
    assert content.count(REDACTED) >= 2
    assert "RuntimeError" in content  # traceback is still kept, just redacted


def test_reconfiguring_does_not_duplicate_handlers(tmp_path):
    configure_logging("INFO", tmp_path / "logs")
    configure_logging("INFO", tmp_path / "logs")
    ours = [h for h in logging.getLogger().handlers if not type(h).__module__.startswith("_pytest")]
    assert len(ours) == 2
