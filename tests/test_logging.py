import logging

from log.logger import StructuredLogger


def test_structured_logger_masks_secrets_and_preserves_caller(caplog) -> None:
    raw_logger = logging.getLogger("test.context")
    structured_logger = StructuredLogger(raw_logger)

    with caplog.at_level(logging.INFO, logger="test.context"):
        structured_logger.info(  # noqa: PLE1205 - custom structured logger signature
            "kamis.request",
            "request started",
            cert_key="secret-value",
            run_id="run-1",
        )

    assert "secret-value" not in caplog.text
    assert "cert_key=***" in caplog.text
    assert "event=kamis.request" in caplog.text
    assert caplog.records[-1].pathname == __file__
