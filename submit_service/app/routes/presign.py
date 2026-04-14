from __future__ import annotations

from typing import Literal
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..config import SubmitConfig
from .submissions import authenticate

logger = logging.getLogger(__name__)
router = APIRouter()
DEFAULT_PRESIGN_TTL = 21600


class PresignRequest(BaseModel):
    bucket: str = Field(min_length=1)
    key: str = Field(min_length=1)
    method: Literal["GET", "PUT"]
    expires: int | None = Field(default=None, ge=60, le=86400)


class PresignResponse(BaseModel):
    url: str


def get_config(request: Request) -> SubmitConfig:
    return request.app.state.cfg


def _s3_client():
    try:
        import boto3
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="boto3 is required for presign") from exc
    endpoint = os.environ.get("AWS_S3_ENDPOINT")
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    session = boto3.session.Session(region_name=region)
    return session.client("s3", endpoint_url=endpoint)


def _default_presign_ttl() -> int:
    raw = os.environ.get("FEDCTL_PRESIGN_TTL", "").strip()
    if not raw:
        return DEFAULT_PRESIGN_TTL
    return int(raw)


@router.post("/v1/presign", response_model=PresignResponse)
def presign(
    payload: PresignRequest,
    request: Request,
    cfg: SubmitConfig = Depends(get_config),
) -> PresignResponse:
    authenticate(request, cfg)
    client = _s3_client()
    op = "put_object" if payload.method == "PUT" else "get_object"
    try:
        url = client.generate_presigned_url(
            op,
            Params={"Bucket": payload.bucket, "Key": payload.key},
            ExpiresIn=payload.expires if payload.expires is not None else _default_presign_ttl(),
        )
    except Exception as exc:
        logger.warning("presign failed: %s", exc)
        raise HTTPException(status_code=500, detail="presign failed") from exc
    return PresignResponse(url=url)
