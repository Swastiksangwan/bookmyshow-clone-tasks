# Task 1: Secure YouTube Trailer Embedding

## 1. Original Task Requirement

Movie detail pages needed YouTube trailer embeds that were safe against script injection, validated before rendering, lazy loaded for performance, and graceful when a trailer URL is missing, invalid, or unavailable.

## 2. Implemented Solution

The `Movie` model stores an optional normal YouTube URL in `trailer_url`. The app never stores raw iframe HTML. The movie detail view extracts a safe YouTube video ID and builds the iframe source itself as `https://www.youtube.com/embed/<video_id>`.

If no safe video ID is available, the template shows fallback text instead of rendering an iframe. Evaluation-only fictional movies show the clearer message: `Trailer preview is not available for this evaluation title.`

## 3. Architecture and Processing Flow

```text
Django admin/user data -> Movie.trailer_url
-> movies.validators.extract_youtube_video_id()
-> movies.views.movie_detail()
-> templates/movies/movie_detail.html
-> safe iframe or fallback message
```

## 4. Data Model or Schema Changes

`movies/models.py` includes:

- `Movie.trailer_url`: optional `URLField(max_length=500, blank=True, null=True)`
- `validate_youtube_url`: model-level validator

Existing movies can keep a blank trailer URL.

## 5. Security / Concurrency / Performance Decisions

- Raw iframe HTML is not stored.
- `mark_safe` is not used.
- Trailer values are not rendered with `|safe`.
- User-provided URLs are not placed directly into iframe `src`.
- Only HTTPS URLs are accepted.
- Domains are validated with `urlparse().hostname`, not simple string matching.
- Allowed hosts are `youtube.com`, `www.youtube.com`, `m.youtube.com`, and `youtu.be`.
- Fake domains such as `youtube.com.evil.com` are rejected.
- Video IDs are validated with `^[A-Za-z0-9_-]+$`.
- Iframes include `loading="lazy"` to reduce initial page load cost.
- Iframes include `referrerpolicy="strict-origin-when-cross-origin"`, `allowfullscreen`, and a limited `allow` list.
- Django template auto-escaping remains enabled.

## 6. Important Files

| File | Purpose |
| --- | --- |
| `movies/models.py` | Adds `Movie.trailer_url` and validator hookup. |
| `movies/validators.py` | Extracts and validates safe YouTube video IDs. |
| `movies/views.py` | Builds safe embed URL in `movie_detail`. |
| `templates/movies/movie_detail.html` | Renders lazy iframe or fallback message. |
| `movies/tests.py` | Tests valid URLs, malicious URLs, and detail page rendering. |
| `movies/migrations/0002_movie_trailer_url.py` | Adds the trailer URL field. |

## 7. Edge Cases Handled

- Empty trailer URL: fallback message.
- Invalid domain: no iframe.
- Fake YouTube domain: no iframe.
- `javascript:` input: rejected.
- `<script>` input: rejected.
- Non-HTTPS YouTube URL: rejected.
- Removed/private YouTube video: page still loads; YouTube displays its own unavailable message inside the iframe if the ID is valid.

## 8. Automated Tests

Tests cover:

- Valid YouTube watch URLs.
- Valid short `youtu.be` URLs.
- Valid embed URLs.
- Mobile YouTube URLs.
- Invalid domains and fake domains.
- JavaScript and script tag injection attempts.
- Empty values.
- Detail page fallback behavior.
- Safe embed URL rendering and lazy loading.

## 9. Manual Verification

1. Add a valid trailer URL to a movie in Django admin.
2. Open `/movies/<movie_id>/`.
3. Confirm the iframe loads lazily and uses `/embed/<video_id>`.
4. Replace the trailer with an invalid URL.
5. Confirm no iframe renders and fallback text appears.

## 10. Trade-offs and Production Notes

This implementation validates URL structure and builds safe embed URLs without calling the YouTube API. It does not verify whether a video has been removed or made private before rendering. That keeps the app fast and avoids requiring API credentials.

## 11. Completion Status

Task 1 is implemented and covered by automated tests. The secure validation and iframe rendering behavior remains active in the final project.
