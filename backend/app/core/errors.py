class SatQueryError(Exception):
    """Base class. Carries a machine code + a user-readable message. Never fabricate a result."""
    code = "satquery_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidAOIError(SatQueryError):
    code = "invalid_aoi"


class NoImageryError(SatQueryError):
    code = "no_imagery"


class InsufficientValidPixelsError(SatQueryError):
    code = "insufficient_valid_pixels"


class MissingBandError(SatQueryError):
    code = "missing_band"


class InvalidDateError(SatQueryError):
    code = "invalid_date"


class UnsupportedQueryError(SatQueryError):
    code = "unsupported_query"


class InsufficientDataError(SatQueryError):
    code = "insufficient_data"


class CaptionModelUnavailableError(SatQueryError):
    code = "caption_model_unavailable"


class CaptionGenerationError(SatQueryError):
    code = "caption_generation_failed"
