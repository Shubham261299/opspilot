class IntakeError(Exception):
    """The whole file can't be processed, e.g. it isn't an Excel file or has no header row.

    Problems with single rows are never raised; they become issues instead.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
