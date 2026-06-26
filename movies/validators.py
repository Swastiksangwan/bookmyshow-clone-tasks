import re
from urllib.parse import parse_qs, urlparse

from django.core.exceptions import ValidationError


ALLOWED_YOUTUBE_HOSTS = {
    'youtube.com',
    'www.youtube.com',
    'm.youtube.com',
    'youtu.be',
}

YOUTUBE_VIDEO_ID_RE = re.compile(r'^[A-Za-z0-9_-]+$')


def extract_youtube_video_id(url):
    """Return a safe YouTube video ID, or None when the URL is not allowed."""
    if not url:
        return None

    parsed = urlparse(str(url).strip())
    hostname = parsed.hostname.lower() if parsed.hostname else ''

    if parsed.scheme != 'https' or hostname not in ALLOWED_YOUTUBE_HOSTS:
        return None

    video_id = None
    path_parts = [part for part in parsed.path.split('/') if part]

    if hostname == 'youtu.be':
        if len(path_parts) == 1:
            video_id = path_parts[0]
    elif path_parts == ['watch']:
        video_values = parse_qs(parsed.query).get('v')
        if video_values:
            video_id = video_values[0]
    elif len(path_parts) == 2 and path_parts[0] == 'embed':
        video_id = path_parts[1]

    if video_id and YOUTUBE_VIDEO_ID_RE.fullmatch(video_id):
        return video_id

    return None


def validate_youtube_url(value):
    if value and not extract_youtube_video_id(value):
        raise ValidationError('Enter a valid HTTPS YouTube trailer URL.')
