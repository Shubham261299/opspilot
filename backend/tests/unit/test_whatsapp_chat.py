from datetime import datetime
from pathlib import Path

import pytest

from app.intake.whatsapp import IST, ChatFormatError, parse_chat

SHOP = "Sharma Traders"


@pytest.fixture(scope="module")
def sample(sample_data_dir: Path) -> str:
    return (sample_data_dir / "whatsapp_orders_export.txt").read_text(encoding="utf-8")


def test_the_sample_export_has_30_messages_in_19_customer_threads(sample: str) -> None:
    chat = parse_chat(sample, SHOP)
    assert (len(chat.messages), len(chat.threads), chat.system_lines) == (30, 19, 1)
    assert chat.threads[0].sender == "Ramesh Electricals"


def test_a_line_without_a_timestamp_continues_the_message(sample: str) -> None:
    om_sai = parse_chat(sample, SHOP).threads[1]
    assert om_sai.messages[0].text == "Sir 6a switch 200 pcs\n6a socket 100 pcs\nplate 3m 50"
    assert om_sai.messages[0].line == 5


def test_a_later_correction_is_in_the_same_thread(sample: str) -> None:
    om_sai = parse_chat(sample, SHOP).threads[1]
    assert [m.sent_at for m in om_sai.messages] == [
        datetime(2026, 9, 22, 10, 5, tzinfo=IST),
        datetime(2026, 9, 24, 9, 50, tzinfo=IST),
    ]


def test_chat_times_are_indian_time(sample: str) -> None:
    first = parse_chat(sample, SHOP).messages[0]
    assert first.sent_at.isoformat() == "2026-09-22T09:12:00+05:30"  # 03:42 UTC


def test_a_shop_reply_belongs_to_the_customer_who_wrote_last(sample: str) -> None:
    royal = next(t for t in parse_chat(sample, SHOP).threads if t.sender == "Royal Hardware")
    assert [m.from_shop for m in royal.messages] == [False, True, False]
    assert "Shop: 200 coil? Itna stock nahi hai" in royal.transcript()


def test_media_is_shown_to_the_model_as_a_photo(sample: str) -> None:
    light = next(t for t in parse_chat(sample, SHOP).threads if t.sender == "New Light House")
    assert "Customer: [photo]" in light.transcript()


def test_12_and_24_hour_clocks() -> None:
    chat = parse_chat(
        "01/10/26, 12:05 am - A: one\n01/10/26, 12:30 pm - A: two\n01/10/2026, 18:45 - A: three",
        SHOP,
    )
    assert [m.sent_at.hour for m in chat.messages] == [0, 12, 18]


def test_text_that_is_not_an_export_is_refused() -> None:
    with pytest.raises(ChatFormatError):
        parse_chat("hello\nworld", SHOP)
