import json
import logging

from app.logging_config import JsonFormatter, new_request_id, request_id_var


def _log_line(msg: str, *args: object, **extra: object) -> dict[str, object]:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, msg, args, None)
    record.__dict__.update(extra)
    return json.loads(JsonFormatter().format(record))


def test_log_line_is_json_with_request_id_and_extra_fields() -> None:
    token = request_id_var.set("req-123")
    try:
        line = _log_line("stock upload %s", "done", upload_id=7)
    finally:
        request_id_var.reset(token)

    assert line["msg"] == "stock upload done"
    assert line["level"] == "info"
    assert line["request_id"] == "req-123"
    assert line["upload_id"] == 7


def test_log_line_outside_a_request_has_no_request_id() -> None:
    assert "request_id" not in _log_line("startup")


def test_uvicorn_colour_codes_are_not_logged() -> None:
    line = _log_line("Uvicorn running", color_message="\x1b[1mUvicorn running\x1b[0m")
    assert "color_message" not in line


def test_safe_incoming_request_id_is_reused() -> None:
    assert new_request_id("abc-123_X.9") == "abc-123_X.9"


def test_missing_or_unsafe_request_id_is_replaced() -> None:
    for incoming in (None, "", "has spaces", "x" * 65, '{"inject": 1}'):
        request_id = new_request_id(incoming)
        assert request_id != incoming
        assert len(request_id) == 32
