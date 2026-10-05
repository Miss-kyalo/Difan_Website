import re
from typing import List, Optional
from fastapi import HTTPException, Header, Query, status


def validate_luhn_checksum(imei: str) -> bool:
    """
    Validates a 15-digit IMEI number using the Luhn Algorithm.
    """
    if not re.fullmatch(r"^\d{15}$", imei):
        return False

    total = 0
    for idx, digit_char in enumerate(imei):
        digit = int(digit_char)
        # Double every second digit starting from index 1 (0-indexed)
        if idx % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit

    return total % 10 == 0


def sanitize_and_validate_imeis(imeis: str = Query(..., description="Comma-separated IMEI numbers")) -> List[str]:
    """
    Sanitizes and validates a comma-separated string of IMEIs.
    Protrack API allows a maximum of 100 IMEIs per single tracking request.
    """
    if not imeis or not imeis.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The 'imeis' parameter cannot be empty.",
        )

    # Split, strip whitespace, and deduplicate while preserving order
    raw_list = [imei.strip() for imei in imeis.split(",") if imei.strip()]
    cleaned_imeis = list(dict.fromkeys(raw_list))

    if len(cleaned_imeis) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid IMEI strings provided.",
        )

    if len(cleaned_imeis) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Protrack API limits requests to a maximum of 100 IMEIs per request.",
        )

    invalid_imeis = []
    for imei in cleaned_imeis:
        # Check digit length & optional Luhn validation
        if not re.fullmatch(r"^\d{14,16}$", imei) or not validate_luhn_checksum(imei):
            invalid_imeis.append(imei)

    if invalid_imeis:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "Invalid IMEI format detected",
                "invalid_imeis": invalid_imeis,
                "hint": "IMEI must be a valid 15-digit numeric string passing Luhn checksum.",
            },
        )

    return cleaned_imeis


def validate_playback_range(
    start_time: int = Query(..., description="Unix timestamp start (seconds)"),
    end_time: int = Query(..., description="Unix timestamp end (seconds)"),
) -> tuple[int, int]:
    """
    Validates start and end time parameters for route playback.
    """
    if start_time <= 0 or end_time <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Timestamps must be positive Unix epoch integers (in seconds).",
        )

    if start_time >= end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'start_time' must be strictly earlier than 'end_time'.",
        )

    max_days = 30
    max_seconds = max_days * 86400
    if (end_time - start_time) > max_seconds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Playback time range cannot exceed {max_days} days per query.",
        )

    return start_time, end_time


def validate_protrack_credentials(
    x_protrack_account: Optional[str] = Header(None, alias="X-Protrack-Account"),
    x_protrack_password: Optional[str] = Header(None, alias="X-Protrack-Password"),
) -> tuple[Optional[str], Optional[str]]:
    """
    Validates user-supplied Protrack account headers.
    """
    account = x_protrack_account.strip() if x_protrack_account is not None else None
    password = x_protrack_password.strip() if x_protrack_password is not None else None

    if account is not None:
        if not re.match(r"^[a-zA-Z0-9_\-\.@]{3,50}$", account):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid 'X-Protrack-Account' header format.",
            )

    if password is not None:
        if len(password) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="'X-Protrack-Password' header is too short.",
            )

    return account, password