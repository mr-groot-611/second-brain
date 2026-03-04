"""
Custom exceptions for the second brain pipeline.
Each layer raises one of these so the message handler can give the user
a specific, actionable error message instead of a generic one.
"""


class GroqError(Exception):
    """Raised when a Groq API call fails."""
    def __init__(self, message: str = "", is_rate_limit: bool = False):
        super().__init__(message)
        self.is_rate_limit = is_rate_limit


class NotionError(Exception):
    """Raised when a Notion API call fails."""
    pass


class TelegramFileError(Exception):
    """Raised when downloading a file from Telegram fails."""
    pass
