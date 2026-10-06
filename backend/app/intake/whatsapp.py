"""WhatsApp chat export -> messages and per-customer threads. Pure code, no LLM.

An exported chat looks like:

    22/09/26, 10:05 am - Om Sai Hardware: Sir 6a switch 200 pcs
    6a socket 100 pcs                      <- a line without a timestamp continues the message
    22/09/26, 11:02 am - New Light House: <Media omitted>
    22/09/26, 9:00 am - Messages and calls are end-to-end encrypted. ...   <- a system line

Each customer's messages, plus the shop's replies to them, become one thread, so a
correction sent later ("1.5 wala 20 nahi 15 karo") is read together with the order it
corrects. A shop reply belongs to the customer who wrote just before it.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

MEDIA = "<Media omitted>"
# Chat times are the phone's local time. India has one time zone and no daylight saving, so a
# fixed offset is exact (and needs no time-zone database, which Windows doesn't ship).
IST = timezone(timedelta(hours=5, minutes=30), "IST")
# "22/09/26, 10:05 am - " (day first; 12- or 24-hour clock)
_STAMP = re.compile(
    r"^(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>\d{2,4}), "
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?:\s?(?P<ampm>[ap]\.?m\.?))? - (?P<rest>.*)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ChatMessage:
    sent_at: datetime
    sender: str
    text: str  # continuation lines joined with "\n"
    line: int  # line number in the export where the message starts
    from_shop: bool

    @property
    def is_media(self) -> bool:
        return self.text.strip() == MEDIA


@dataclass
class Thread:
    """One customer's messages and the shop's replies to them, in order."""

    sender: str
    messages: list[ChatMessage] = field(default_factory=list)

    def transcript(self) -> str:
        """The thread as the LLM reads it: "[22 Sep 10:05] Customer: ..." per message."""
        lines = []
        for message in self.messages:
            who = "Shop" if message.from_shop else "Customer"
            text = "[photo]" if message.is_media else message.text
            lines.append(f"[{message.sent_at:%d %b %H:%M}] {who}: {text}")
        return "\n".join(lines)


@dataclass(frozen=True)
class Chat:
    messages: tuple[ChatMessage, ...]
    threads: tuple[Thread, ...]  # in order of each customer's first message
    system_lines: int  # lines from WhatsApp itself (encryption notice ...), skipped


class ChatFormatError(ValueError):
    pass


def parse_chat(text: str, shop_name: str) -> Chat:
    messages: list[ChatMessage] = []
    system_lines = 0
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.lstrip("﻿").rstrip()
        match = _STAMP.match(line)
        if match is None:
            if messages and line:
                last = messages[-1]
                messages[-1] = ChatMessage(
                    last.sent_at, last.sender, f"{last.text}\n{line}", last.line, last.from_shop
                )
            continue
        sender, sep, body = match["rest"].partition(": ")
        if not sep:
            system_lines += 1  # "Messages and calls are end-to-end encrypted..."
            continue
        sender = sender.strip()
        messages.append(
            ChatMessage(_timestamp(match), sender, body.strip(), number, sender == shop_name)
        )
    if not messages:
        raise ChatFormatError("No WhatsApp messages found. Export the chat 'Without media'.")
    return Chat(tuple(messages), _threads(messages), system_lines)


def _timestamp(match: re.Match[str]) -> datetime:
    year = int(match["year"])
    hour = int(match["hour"])
    ampm = (match["ampm"] or "").lower().replace(".", "")
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    return datetime(
        year + 2000 if year < 100 else year,
        int(match["month"]),
        int(match["day"]),
        hour,
        int(match["minute"]),
        tzinfo=IST,
    )


def _threads(messages: list[ChatMessage]) -> tuple[Thread, ...]:
    threads: dict[str, Thread] = {}
    last_customer: str | None = None
    for message in messages:
        if message.from_shop:
            if last_customer is not None:  # a reply to whoever wrote last
                threads[last_customer].messages.append(message)
            continue
        last_customer = message.sender
        threads.setdefault(message.sender, Thread(message.sender)).messages.append(message)
    return tuple(threads.values())
