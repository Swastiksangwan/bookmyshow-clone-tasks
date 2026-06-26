# Task 01: Secure YouTube Trailer Embedding with Performance Controls

## 1. Task Overview

This feature will allow each movie to show a YouTube trailer on a movie detail page or movie-specific page. The trailer should appear only when the stored trailer URL is valid and safe.

Trailer embedding needs security controls because trailer URLs may eventually be entered through Django admin or another form. If the project stores or renders unsafe HTML, an attacker could try to inject JavaScript into the page. This is called XSS, or cross-site scripting.

Trailer embedding also needs performance controls because YouTube iframes load third-party scripts, network requests, images, and video player code. Loading several iframes immediately can slow the page, especially on mobile or slow internet. The plan is to validate trailer data first, then render the iframe lazily and safely.

## 2. Current Project Analysis

Relevant existing files:

- `movies/models.py`: contains the `Movie`, `Theater`, `Seat`, and `Booking` models.
- `movies/views.py`: contains `movie_list`, `theater_list`, and `book_seats`.
- `movies/urls.py`: maps movie URLs to the views.
- `movies/admin.py`: registers `Movie`, `Theater`, `Seat`, and `Booking` in Django admin.
- `templates/movies/movie_list.html`: shows the movie listing page.
- `templates/movies/theater_list.html`: shows theaters/showtimes for one selected movie.
- `templates/movies/seat_selection.html`: shows seats for one selected theater.
- `templates/home.html`: shows recommended movie cards on the homepage.
- `templates/users/basic.html`: base layout used by movie templates.
- `bookmyseat/urls.py`: includes `movies.urls` under `/movies/`.

Current movie display flow:

1. The homepage (`/`) shows recommended movies from `users.views.home`.
2. The movie list page (`/movies/`) shows all movies and supports search.
3. Clicking a movie currently opens the theater list URL: `/movies/<movie_id>/theaters`.
4. The theater list page shows the selected movie name and available theaters/showtimes.
5. Clicking "Book Now" opens the seat booking page.

Current URL routes in `movies/urls.py`:

- `/movies/` -> `movie_list`
- `/movies/<movie_id>/theaters` -> `theater_list`
- `/movies/theater/<theater_id>/seats/book/` -> `book_seats`

Movie detail page status:

There is no dedicated `movie_detail` view, URL, or `movie_detail.html` template right now. The closest existing movie-specific page is `templates/movies/theater_list.html`, because it receives one `movie` object and shows theaters for that movie.

For implementation later, there are two possible paths:

1. Add a true movie detail page, such as `/movies/<movie_id>/`, then place the trailer there.
2. Use the existing theater list page as the movie-specific page and add the trailer there.

The cleaner long-term design is to create a dedicated movie detail page, but the smaller change is to add the trailer section to the existing theater list page.

## 3. Proposed Data Design

The trailer URL should be stored on the `Movie` model.

Recommended model change later:

- Add a `trailer_url` field to `Movie`.
- Use a normal URL/text field for the YouTube URL.
- Keep it optional, because not every movie will have a trailer.

Recommended approach:

- Store only a normal YouTube URL.
- Do not store raw iframe HTML.
- Extract the YouTube video ID from the URL.
- Use only the extracted video ID to build the iframe embed URL.

Why raw iframe code is unsafe:

Raw iframe HTML is user/admin-provided HTML. If the project stores it and later renders it with `|safe`, malicious HTML or JavaScript could run in another user's browser. Even a trusted admin area can become risky if an account is compromised or if bad content is copied from an unknown source.

Valid YouTube URL formats to support:

- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://www.youtube.com/embed/VIDEO_ID`

Only the extracted YouTube video ID should be used for iframe rendering. For example, if the stored URL is:

`https://www.youtube.com/watch?v=dQw4w9WgXcQ`

The page should build this safe embed URL itself:

`https://www.youtube.com/embed/dQw4w9WgXcQ`

The template should not trust or directly inject the full stored URL into iframe HTML.

## 4. Security Plan

XSS risk in simple terms:

XSS happens when unsafe text is treated like HTML or JavaScript by the browser. For example, if a malicious value like `<script>alert(1)</script>` is saved as a trailer and later rendered as real HTML, the browser may run it.

What not to do:

- Do not store raw iframe HTML from users or admin.
- Do not render trailer URL with `|safe`.
- Do not directly inject a user-provided URL into iframe HTML.
- Do not allow any website URL to be embedded.
- Do not trust domains that only look like YouTube, such as `youtube.com.evil.com`.

What we will do:

- Validate the trailer URL before using it.
- Accept only known YouTube URL formats.
- Extract only the YouTube video ID.
- Build the safe embed URL ourselves:

  `https://www.youtube.com/embed/<video_id>`

- Reject unsupported domains.
- Keep Django's normal template auto-escaping enabled.
- Avoid `mark_safe` and avoid the `safe` template filter for trailer data.

Allowed domains:

- `youtube.com`
- `www.youtube.com`
- `m.youtube.com`
- `youtu.be`

Validation should block:

- `javascript:alert(1)`
- `<script>alert(1)</script>`
- non-YouTube links
- malformed URLs
- fake domains like `youtube.com.evil.com`

Recommended Django-specific validation approach:

- Create a helper function, for example `extract_youtube_video_id(url)`.
- Use Python URL parsing, such as `urllib.parse.urlparse` and `parse_qs`, instead of string slicing only.
- Check the parsed URL scheme is `https`.
- Check the parsed domain is exactly in the allowed domain list.
- Extract the video ID from either:
  - the `v` query parameter for watch URLs
  - the path for `youtu.be`
  - the `/embed/<video_id>` path for embed URLs
- Validate the extracted video ID with a strict pattern, such as letters, numbers, `_`, and `-`.
- Return `None` or raise a Django `ValidationError` when invalid.

## 5. Performance Plan

Why iframes can slow down pages:

A YouTube iframe loads content from YouTube, including player JavaScript, images, cookies/storage behavior, and network requests. This can increase page load time and affect mobile users.

Lazy loading plan:

- Add `loading="lazy"` to the iframe.
- Consider a lightweight placeholder or "Load trailer" button before creating the iframe if the page later shows many trailers.
- For this project, if only one trailer appears on one movie page, `loading="lazy"` may be enough for the first implementation.

Recommended iframe attributes:

- `loading="lazy"`
- `referrerpolicy="strict-origin-when-cross-origin"`
- `allowfullscreen`
- limited `allow` permissions, for example:

  `allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"`

Responsive layout plan:

- Wrap the iframe in a responsive container.
- Use CSS so the video keeps a 16:9 ratio on desktop and mobile.
- Avoid fixed iframe widths that break on small screens.

Fallback performance behavior:

- If the trailer URL is missing or invalid, do not render an iframe at all.
- Showing a small text fallback is faster and safer than trying to load a broken iframe.

## 6. Fallback Plan

If no trailer URL exists:

- Show `Trailer not available.`
- Do not render an iframe.

If the URL is invalid:

- Do not render an iframe.
- Show a safe fallback message, such as `Trailer not available.`
- Optionally show a more specific admin-only validation error when saving the movie.

If the YouTube video was removed, private, or unavailable:

- The browser/YouTube iframe may show YouTube's unavailable message.
- The Django page should still load normally.
- The rest of the movie page should not break.

Optional future improvement:

- Verify trailer availability using YouTube oEmbed or the YouTube Data API.
- This should not be required for this task, because it would add external API dependency, API keys, quota limits, and more setup.

## 7. Implementation Plan For Later

These are the planned steps for implementation later. Do not implement them until explicitly requested.

1. Update the `Movie` model with an optional `trailer_url` field.
2. Create and apply a migration for the new field.
3. Add a validation helper function to extract a safe YouTube video ID.
4. Decide where validation should run:
   - model-level validation via `Movie.clean()`
   - admin/form validation
   - view/template context validation before rendering
5. Update Django admin so the trailer URL can be added and reviewed.
6. Decide the display page:
   - preferred: create `movie_detail` view, URL, and template
   - smaller change: add trailer to `theater_list.html`
7. Update the movie detail/template page to render the iframe safely.
8. Add fallback UI for missing or invalid trailers.
9. Add responsive CSS for the trailer embed.
10. Add manual test cases.
11. Optionally add unit tests for URL validation.
12. Run Django verification commands:
    - `python manage.py check`
    - `python manage.py makemigrations --check --dry-run`
    - `python manage.py test`

## 8. Files Expected To Change Later

| File path | Planned change | Reason |
|---|---|---|
| `movies/models.py` | Add optional `trailer_url` field to `Movie`; possibly add model validation | Store trailer URL safely with movie data |
| `movies/admin.py` | Show/edit `trailer_url` in `MovieAdmin` | Allow trailer URLs to be added from Django admin |
| `movies/views.py` | Add safe embed context for movie pages; optionally add a `movie_detail` view | Pass only safe trailer data to templates |
| `movies/urls.py` | Add a movie detail route if a dedicated detail page is created | Give each movie a page where the trailer can appear |
| `templates/movies/movie_detail.html` | New template if a dedicated movie detail page is created | Render trailer, movie info, and fallback UI |
| `templates/movies/theater_list.html` | Alternative location for trailer if no detail page is added | Existing movie-specific page already receives one `movie` |
| `templates/movies/movie_list.html` | Update links if a dedicated detail page is added | Send users to movie detail before theater booking |
| `templates/home.html` | Update movie card links if a dedicated detail page is added | Keep homepage movie navigation consistent |
| `templates/users/basic.html` | Optional shared CSS or block support if needed | Support responsive trailer styling globally |
| `movies/utils.py` or `movies/validators.py` | Add YouTube URL parsing and validation helper | Keep validation logic reusable and testable |
| `movies/tests.py` | Add validation and view tests | Prove safe/unsafe trailer URLs behave correctly |
| `movies/migrations/0002_*.py` | New migration for `trailer_url` | Apply database schema change |

## 9. Testing Plan

Manual test cases:

| Test case | Example value | Expected result |
|---|---|---|
| Valid YouTube watch URL | `https://www.youtube.com/watch?v=dQw4w9WgXcQ` | Trailer iframe appears |
| Valid youtu.be URL | `https://youtu.be/dQw4w9WgXcQ` | Trailer iframe appears |
| Valid embed URL | `https://www.youtube.com/embed/dQw4w9WgXcQ` | Trailer iframe appears |
| Empty trailer URL | empty value | Fallback message appears; no iframe |
| Invalid domain | `https://example.com/video` | Fallback or validation error; no iframe |
| JavaScript injection attempt | `javascript:alert(1)` | Rejected; no script runs |
| Script tag injection attempt | `<script>alert(1)</script>` | Rejected or escaped; no script runs |
| Fake YouTube domain | `https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ` | Rejected; no iframe |
| Removed/private YouTube video | valid-looking URL for unavailable video | Page loads normally; iframe may show YouTube unavailable message |
| Slow network lazy loading | throttle browser network in DevTools | Page content loads first; iframe loads lazily |

Manual browser testing steps:

1. Start the local server with `python manage.py runserver`.
2. Log in to Django admin.
3. Add or edit a movie trailer URL.
4. Open the movie page where trailers are displayed.
5. Confirm valid trailers appear.
6. Confirm missing or invalid trailers show fallback text.
7. Try malicious values and confirm no alert/script runs.
8. Use browser DevTools Network tab to confirm iframe lazy loading behavior.
9. Test mobile size using responsive mode in DevTools.

Optional unit tests:

- Test the YouTube ID extraction helper with valid URL formats.
- Test blocked domains and malicious strings.
- Test view/template behavior for valid, empty, and invalid trailer URLs.

## 10. Acceptance Criteria

The feature will be considered complete when:

- Trailer appears on the movie detail page for valid YouTube URLs.
- Invalid or malicious URLs never render as HTML.
- Raw script injection does not execute.
- Trailer iframe uses lazy loading.
- Missing or invalid trailer shows a fallback message.
- Existing movie pages still work.
- Django checks and tests pass.

## 11. Final Summary

The safest plan is to store a normal YouTube URL on each movie, validate that it belongs to a real allowed YouTube domain, extract only the video ID, and build the iframe embed URL inside our own code. We should never store or render raw iframe HTML from admin or users.

For performance, the iframe should load lazily and be placed inside a responsive container. If there is no trailer, an invalid trailer, or a removed/private YouTube video, the movie page should still load normally and show a safe fallback.

Implementation has not been done yet. This document is only the planning step.

Next instruction needed from the user:

`Please implement Task 1 using this plan.`
