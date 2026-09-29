class IntakeError(Exception):
    """The whole file can't be processed, e.g. it isn't an Excel file or has no header row.

    Problems with single rows are never raised; they become issues instead.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class UploadRejected(IntakeError):
    """The file couldn't be processed; it was saved as a 'failed' upload and nothing else."""

    def __init__(self, code: str, message: str, upload_id: int) -> None:
        super().__init__(code, message)
        self.upload_id = upload_id
