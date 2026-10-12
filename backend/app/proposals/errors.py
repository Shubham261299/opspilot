"""Reasons an approval is refused until something is fixed."""


class NotReady(Exception):
    """Approving would act on something incomplete; the message says what to fix first."""

    code = "not_ready"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class OrderNotReady(NotReady):
    code = "order_not_ready"


class InvoiceNotReady(NotReady):
    code = "invoice_not_ready"


def not_ready(code: str, message: str) -> NotReady:
    """Rebuild the right error from its code (the approval agent stores errors as data)."""
    for cls in (OrderNotReady, InvoiceNotReady):
        if cls.code == code:
            return cls(message)
    return NotReady(message)
