import os
import time
import hashlib
from typing import List, Optional
import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from backend.routes.validators import (
    sanitize_and_validate_imeis,
    validate_playback_range,
    validate_protrack_credentials,
)

load_dotenv()

PROTRACK_BASE_URL = os.getenv("PROTRACK_BASE_URL", "https://api.protrack365.com")
DEFAULT_ACCOUNT = os.getenv("PROTRACK_ACCOUNT", "")
DEFAULT_PASSWORD = os.getenv("PROTRACK_PASSWORD", "")
DIFAN_API_BASE_URL = os.getenv("DIFAN_API_BASE_URL", "http://localhost:5000").rstrip("/")

app = FastAPI(
    title="Protrack GPS Telematics Multi-Tenant Proxy",
    description="Backend API proxy for Protrack365 GPS integration with custom user API credential support.",
    version="1.2.0",
)

# Enable CORS for React Frontend Integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory Token Cache per account to prevent redundant authentication requests
# Cache structure: { "account_username": { "token": "...", "expires_at": 1234567890 } }
token_cache_store = {}


class GPSPosition(BaseModel):
    imei: str
    latitude: float
    longitude: float
    speed: float
    course: float
    gpstime: int
    online: bool


async def authorize_imei_access(imei: str, authorization: Optional[str]) -> None:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign-in is required for GPS tracking.")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{DIFAN_API_BASE_URL}/api/shipments/authorize-imei/{imei}",
                headers={"Authorization": authorization},
                timeout=5.0,
            )
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Unable to verify shipment access: {exc}",
            ) from exc

    if response.status_code != status.HTTP_200_OK:
        raise HTTPException(
            status_code=response.status_code,
            detail="GPS access is not authorized for this shipment.",
        )


async def get_protrack_token(
    user_account: Optional[str] = None,
    user_password: Optional[str] = None
) -> str:
    """
    Authenticates with Protrack API using user-provided credentials
    or falls back to default system environment variables.
    """
    account = user_account or DEFAULT_ACCOUNT
    password = user_password or DEFAULT_PASSWORD

    if not account or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Protrack API credentials missing. Provide X-Protrack-Account and X-Protrack-Password headers or configure system defaults.",
        )

    current_time = int(time.time())

    # Return cached token if valid (with 5 min safety buffer)
    cached = token_cache_store.get(account)
    if cached and cached["expires_at"] > current_time + 300:
        return cached["token"]

    # Protrack Signature Strategy: MD5(MD5(password) + time)
    md5_password = hashlib.md5(password.encode("utf-8")).hexdigest()
    signature_raw = f"{md5_password}{current_time}"
    signature = hashlib.md5(signature_raw.encode("utf-8")).hexdigest()

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{PROTRACK_BASE_URL}/api/authorization",
                params={
                    "account": account,
                    "time": current_time,
                    "signature": signature,
                },
                timeout=10.0,
            )
            data = response.json()

            if data.get("code") == 0 and "record" in data:
                access_token = data["record"]["access_token"]
                expires_in = data["record"].get("expires_in", 7200)

                # Store token in memory cache for this account
                token_cache_store[account] = {
                    "token": access_token,
                    "expires_at": current_time + expires_in,
                }
                return access_token
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Protrack Auth Failed for '{account}': {data.get('message', 'Invalid credentials')}",
                )
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to reach Protrack server: {str(exc)}",
            )


@app.get("/health")
def health_check():
    """Service health status endpoint"""
    return {
        "status": "ok",
        "service": "maps.py",
        "protrack_configured": bool(DEFAULT_ACCOUNT and DEFAULT_PASSWORD),
        "active_cached_accounts": len(token_cache_store)
    }


@app.get("/api/protrack/track", response_model=List[GPSPosition])
async def get_device_tracking(
    imeis: List[str] = Depends(sanitize_and_validate_imeis),
    credentials: tuple[Optional[str], Optional[str]] = Depends(validate_protrack_credentials),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    Fetch real-time location telemetry for GPS devices.
    Accepts custom Protrack credentials via HTTP Headers `X-Protrack-Account` and `X-Protrack-Password`.
    """
    for imei in imeis:
        await authorize_imei_access(imei, authorization)

    x_protrack_account, x_protrack_password = credentials
    token = await get_protrack_token(x_protrack_account, x_protrack_password)

    async with httpx.AsyncClient() as client:
        try:
            url = f"{PROTRACK_BASE_URL}/api/track"
            params = {"access_token": token, "imeis": ",".join(imeis)}
            response = await client.get(url, params=params, timeout=10.0)
            data = response.json()

            if data.get("code") != 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Protrack Error: {data.get('message')}",
                )

            records = data.get("record", [])
            positions = []
            for item in records:
                positions.append(
                    GPSPosition(
                        imei=str(item.get("imei")),
                        latitude=float(item.get("latitude", 0.0)),
                        longitude=float(item.get("longitude", 0.0)),
                        speed=float(item.get("speed", 0.0)),
                        course=float(item.get("course", 0.0)),
                        gpstime=int(item.get("gpstime", 0)),
                        online=bool(item.get("online", True)),
                    )
                )

            return positions

        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Error connecting to Protrack tracking endpoint: {str(exc)}",
            )


@app.get("/api/protrack/playback")
async def get_route_playback(
    imei: str,
    playback_range: tuple[int, int] = Depends(validate_playback_range),
    credentials: tuple[Optional[str], Optional[str]] = Depends(validate_protrack_credentials),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    Fetch historical GPS track points for map route playback.
    """
    start_time, end_time = playback_range
    await authorize_imei_access(imei, authorization)
    x_protrack_account, x_protrack_password = credentials
    token = await get_protrack_token(x_protrack_account, x_protrack_password)

    async with httpx.AsyncClient() as client:
        try:
            url = f"{PROTRACK_BASE_URL}/api/playback"
            params = {
                "access_token": token,
                "imei": imei,
                "begintime": start_time,
                "endtime": end_time,
            }
            response = await client.get(url, params=params, timeout=15.0)
            data = response.json()

            if data.get("code") != 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Protrack Playback Error: {data.get('message')}",
                )

            return {"imei": imei, "points": data.get("record", [])}

        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Error reaching Protrack playback endpoint: {str(exc)}",
            )


@app.post("/api/protrack/verify-credentials")
async def verify_credentials(
    credentials: tuple[Optional[str], Optional[str]] = Depends(validate_protrack_credentials),
):
    """
    Verifies user-supplied Protrack credentials and tests API connectivity.
    """
    x_protrack_account, x_protrack_password = credentials
    token = await get_protrack_token(x_protrack_account, x_protrack_password)
    return {
        "status": "success",
        "message": "Protrack API credentials verified successfully!",
        "account": x_protrack_account or DEFAULT_ACCOUNT,
        "token_preview": f"{token[:8]}...",
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run("backend.routes.maps:app", host="0.0.0.0", port=port, reload=True)