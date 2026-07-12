class DomainError(Exception):
    code = "BAD_USER_INPUT"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFoundError(DomainError):
    code = "NOT_FOUND"


class ConflictError(DomainError):
    code = "CONFLICT"


class InvalidTransitionError(DomainError):
    code = "INVALID_STATUS_TRANSITION"


class OverpaymentError(DomainError):
    code = "OVERPAYMENT"


class IdempotencyConflictError(DomainError):
    code = "IDEMPOTENCY_CONFLICT"
