import mimetypes


def normalize_file_type(file_url: str, current_type: str | None = None) -> str | None:
    """
    Ensures valid MIME type like image/jpeg or video/mp4
    """
    if current_type and "/" in current_type:
        return current_type.lower()

    guess, _ = mimetypes.guess_type(file_url)
    if guess:
        return guess.lower()

    ext = file_url.split(".")[-1].lower()
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "mp4": "video/mp4",
        "mov": "video/mp4",
    }.get(ext)
