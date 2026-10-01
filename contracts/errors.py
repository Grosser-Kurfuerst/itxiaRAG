class DomainError(Exception):
    def __init__(self, code, message, status=400, fields=None, retryable=False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.fields = fields or {}
        self.retryable = retryable
