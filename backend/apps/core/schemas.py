from ninja import Schema


class ErrorOut(Schema):
    """Every error response: a plain-language Polish message that can be shown to the person as is."""

    detail: str
