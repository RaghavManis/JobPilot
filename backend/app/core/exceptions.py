class JobPilotException(Exception):
    """Base exception for JobPilot application errors."""
    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class BrowserException(JobPilotException):
    """Raised when a Playwright or browser interaction error occurs."""
    pass


class LLMProviderException(JobPilotException):
    """Raised when an LLM provider generation or API error occurs."""
    pass


class SessionException(JobPilotException):
    """Raised when an application or browser session error occurs."""
    pass


class FormExtractionException(JobPilotException):
    """Raised when DOM element parsing or synthetic ID injection fails."""
    pass
