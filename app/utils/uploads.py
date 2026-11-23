"""Store bounded image uploads under server-generated names only."""
from pathlib import Path
from uuid import uuid4

import aiofiles
import magic
from fastapi import HTTPException, UploadFile

from app.core.config import UPLOAD_DIR

MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


async def save_profile_image(upload: UploadFile) -> str:
    data = await upload.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Profile image must be no larger than 5 MB")
    mime = magic.from_buffer(data, mime=True) if data else ""
    if mime not in IMAGE_EXTENSIONS:
        raise HTTPException(422, "Select a JPEG, PNG or WebP image")
    # Never use an untrusted filename, extension, or Content-Type as a path.
    destination = Path(UPLOAD_DIR) / (uuid4().hex + IMAGE_EXTENSIONS[mime])
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with aiofiles.open(destination, "xb") as target:
            await target.write(data)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination.as_posix()
