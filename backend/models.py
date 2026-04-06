"""Pydantic models for API request/response and internal dataclasses."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# API request / response models
# ---------------------------------------------------------------------------

class SourceCreate(BaseModel):
    url: str = Field(..., description="YouTube channel or playlist URL")
    name: str = Field("", description="Custom label (auto-generated if blank)")
    max_backfill: int = Field(15, ge=1, le=500, description="Max past episodes on first sync")
    custom_storage_path: Optional[str] = Field(None, description="Override download folder (absolute path)")


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    max_backfill: Optional[int] = Field(None, ge=1, le=500)
    custom_storage_path: Optional[str] = None


class SourceResponse(BaseModel):
    id: int
    name: str
    source_type: str
    youtube_id: str
    url: str
    enabled: bool
    max_backfill: int
    last_polled_at: Optional[str]
    video_count: int = 0
    completed_count: int = 0
    created_at: str
    custom_storage_path: Optional[str] = None
    icon_url: Optional[str] = None


class VideoResponse(BaseModel):
    id: int
    video_id: str
    title: str
    description: str
    publish_date: Optional[str]
    duration_seconds: Optional[int]
    download_status: str
    file_size: Optional[int]
    error_message: Optional[str]
    created_at: str


class StatusResponse(BaseModel):
    server_running: bool = True
    next_poll: Optional[str] = None
    last_poll: Optional[str] = None
    download_queue_size: int = 0
    active_downloads: int = 0


class SettingsResponse(BaseModel):
    youtube_api_key_set: bool
    poll_interval_minutes: int
    storage_path: str
    server_port: int
    base_url: str


class SettingsUpdate(BaseModel):
    youtube_api_key: Optional[str] = None
    poll_interval_minutes: Optional[int] = Field(None, ge=1, le=1440)
