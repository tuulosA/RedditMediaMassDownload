# redditcommand/utils/url_utils.py

from redditcommand.config import MediaValidationConfig

def is_valid_media_url(url: str) -> bool:
    url = url.lower()
    return (
        url.endswith(MediaValidationConfig.VALID_EXTENSIONS) or
        any(source in url for source in MediaValidationConfig.VALID_SOURCES)
    )

def matches_media_type(url: str, media_type: str) -> bool:
    url = url.lower()
    return (
        not media_type
        or (media_type == "image" and url.endswith(MediaValidationConfig.IMAGE_EXTENSIONS))
        or (media_type == "video" and url.endswith(MediaValidationConfig.VIDEO_EXTENSIONS))
        or any(source in url for source in MediaValidationConfig.SOURCE_HINTS.get(media_type, []))
    )