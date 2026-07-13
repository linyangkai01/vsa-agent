"""Video upload URL endpoint — returns a presigned URL for video upload.

Mirrors NVIDIA api/video_upload_url.py pattern.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["video"])


@router.post("/video/upload-url")
async def get_video_upload_url(filename: str):
    """Generate a presigned URL for video file upload.

    Simplified: returns mock URL. Production needs S3/MinIO integration.
    """
    return {"upload_url": f"https://storage.example.com/upload/{filename}", "filename": filename}
