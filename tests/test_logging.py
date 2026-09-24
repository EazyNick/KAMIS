import logging

from log.context_logger import ContextLogger


def test_context_logger_masks_secrets(caplog) -> None:
    raw_logger = logging.getLogger("test.context")
    context_logger = ContextLogger(raw_logger)

    with caplog.at_level(logging.INFO, logger="test.context"):
        context_logger.info(  # noqa: PLE1205 - custom structured logger signature
            "kamis.request",
            "request started",
            cert_key="secret-value",
            run_id="run-1",
        )

    assert "secret-value" not in caplog.text
    assert "cert_key=***" in caplog.text
    assert "event=kamis.request" in caplog.text
