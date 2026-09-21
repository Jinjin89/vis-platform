class DataError(RuntimeError):
    def __init__(self, message: str, code: str = "DATA_UNAVAILABLE", status: int = 409) -> None:
        super().__init__(message)
        self.code, self.status = code, status
