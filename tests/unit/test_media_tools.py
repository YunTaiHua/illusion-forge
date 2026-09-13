"""媒体工具路由测试"""
from illusion_forge.channels.tools.media import _route_media_type


def test_route_image_extensions():
    """图片扩展名路由到 image"""
    for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"]:
        assert _route_media_type(f"file{ext}") == "image"


def test_route_video_extensions():
    """视频扩展名路由到 video"""
    for ext in [".mp4", ".mov", ".avi", ".mkv", ".webm", ".3gp"]:
        assert _route_media_type(f"file{ext}") == "video"


def test_route_audio_extensions():
    """音频扩展名路由到 audio"""
    for ext in [".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus"]:
        assert _route_media_type(f"file{ext}") == "audio"


def test_route_document_extensions():
    """其他扩展名路由到 file"""
    for ext in [".pdf", ".docx", ".txt", ".zip", ".py", ""]:
        assert _route_media_type(f"file{ext}") == "file"


def test_route_case_insensitive():
    """扩展名大小写不敏感"""
    assert _route_media_type("PHOTO.JPG") == "image"
    assert _route_media_type("video.MP4") == "video"
