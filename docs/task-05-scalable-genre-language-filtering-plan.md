# Task 05: Scalable Genre and Language Filtering with Query Optimization

## 1. Task Overview

Task 5 will add scalable movie filtering so users can browse the movie catalog by genre and language. Users should be able to select multiple genres, select multiple languages, combine those filters with search, sort the results, and move through paginated pages without losing the current filters.

Filtering must happen server-side with Django ORM queries. Frontend-only filtering is not acceptable for a catalog of 5,000+ movies because the browser would need to download too many movie cards before filtering. That increases page load time, memory use, HTML size, and mobile data usage.

Pagination and sorting must work with filters because a large catalog cannot be shown on one page. The database should first apply filters, then sorting, then pagination. The app should return only the current page of movie results.

Dynamic filter counts are useful because they tell users how many movies are available under each option. For example, after choosing Hindi, the Action checkbox can show the number of Hindi action movies that are available.

Indexing and aggregation are needed because filtering and dynamic counts should be calculated by the database, not by loading every movie into Python and looping over it.

Task 5 should build on the existing movie list and movie detail flow:

- `/movies/` remains the main movie browsing page.
- Movie cards should still link to the Task 1 movie detail page.
- From movie detail, users can still continue to theaters, reservations, payments, and bookings from Tasks 2 and 3.
- Task 4 admin analytics should continue to work and should not depend on frontend-only movie filtering.

PostgreSQL is recommended for production-scale filtering and index behavior. SQLite is acceptable for local development and beginner testing.

## 2. Current Project Analysis

Files inspected before writing this plan:

- `movies/models.py`
- `movies/views.py`
- `movies/urls.py`
- `movies/tests.py`
- `templates/movies/movie_list.html`
- `templates/home.html`
- `bookmyseat/settings.py`
- `movies/management/commands/`
- `docs/task-01-youtube-trailer-embedding-plan.md`
- `docs/task-02-seat-reservation-timeout-plan.md`
- `docs/task-03-payment-idempotency-webhooks-plan.md`
- `docs/task-04-admin-analytics-dashboard-plan.md`

Current `Movie` model fields:

- `name`
- `image`
- `rating`
- `cast`
- `description`
- `trailer_url`

Current `movie_list` view behavior:

- Reads `search` from `request.GET`.
- If search exists, filters movies with `name__icontains=search_query`.
- Otherwise returns all movies with `Movie.objects.all()`.
- Sends the queryset to `templates/movies/movie_list.html`.
- No pagination, genre filtering, language filtering, dynamic counts, or sorting whitelist exists yet.

Current movie list template behavior:

- Shows a search box.
- Displays movie cards in a grid.
- Each movie links to `movie_detail`.
- Includes a small client-side JavaScript filter that hides/shows already-rendered cards based on the search field.
- That client-side filter is not enough for Task 5 and should not be treated as the real filtering system.

Current movie routes:

- `/movies/` -> movie list.
- `/movies/<movie_id>/` -> movie detail with secure Task 1 trailer handling.
- `/movies/<movie_id>/theaters` -> theater/showtime list.
- Seat reservation, payment, and admin analytics routes already exist and should remain unchanged.

Current limitations:

- No normalized `Genre` model.
- No `Language` model or language field.
- No multi-select genre filtering.
- No multi-select language filtering.
- No dynamic filter counts.
- No pagination for large catalogs.
- No filtering-specific indexes.
- Current `Movie.objects.all()` listing can become too large for 5,000+ movies.
- Current `name__icontains` search is simple but may not fully benefit from a normal B-tree index on all databases.

## 3. Data Model Design

Recommended model design:

### Genre

Add a `Genre` model:

```python
class Genre(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
```

### Language

Add a `Language` model:

```python
class Language(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.SlugField(max_length=20, unique=True)
```

The `code` can be values like `hindi`, `english`, `tamil`, or a short ISO-style code if the project prefers that later.

### Movie changes

Update `Movie`:

```python
genres = models.ManyToManyField(Genre, related_name="movies", blank=True)
language = models.ForeignKey(
    Language,
    related_name="movies",
    null=True,
    blank=True,
    on_delete=models.SET_NULL,
)
```

Recommendation:

- Use `ManyToManyField` for genres.
- Use a `ForeignKey` for one primary language.

Why this is the best first design:

- Movies commonly have multiple genres, so many-to-many is appropriate.
- Most movie listings have one primary language, so `ForeignKey` is simpler and faster.
- The task asks for multi-select language filters, and a `ForeignKey` still supports that with `language__code__in=[...]`.
- Many-to-many language would be more flexible for dubbed/multi-language movies, but it adds another join and makes dynamic counts more complex.

Future option:

If the project later needs movies to belong to multiple languages, change `language` to `languages = ManyToManyField(Language, related_name="movies")`. That would make filtering more flexible but would require more joins, more `distinct()`, and more careful count queries.

## 4. Filter Semantics

### Genre multi-select

Recommended behavior: OR logic.

If a user selects Action and Drama, return movies that have Action OR Drama.

Why OR:

- It is beginner-friendly.
- It matches common catalog browsing behavior.
- It is easier to express efficiently with `genres__slug__in=selected_genres`.

Optional advanced behavior: AND logic.

AND logic would return only movies that contain every selected genre. This is more expensive because it usually requires grouping by movie and checking that the count of matched genres equals the number selected.

### Language multi-select

Use OR logic.

If a user selects Hindi and English, return movies where:

```python
language__code__in=["hindi", "english"]
```

### Combined filters

Genre and language filters combine with AND.

Example:

```text
genres = Action OR Drama
languages = Hindi OR English
final condition = (Action OR Drama) AND (Hindi OR English)
```

### Search

The existing search should combine with filters.

Example:

```text
movie name contains "avengers"
AND selected genres match
AND selected languages match
```

Implementation should keep search server-side. The current client-side search snippet in `movie_list.html` should be removed or treated only as a visual enhancement, not as the source of truth.

## 5. Sorting Plan

Supported sort options should use a safe whitelist.

Recommended options:

- `default`: newest by `id` descending, because `Movie` does not currently have `created_at`.
- `title_asc`: movie name A-Z.
- `title_desc`: movie name Z-A.
- `rating_desc`: rating high to low.
- `rating_asc`: rating low to high.
- `popular`: most booked, using `Booking` aggregation if practical.

Sorting must happen after filters and before pagination.

Do not trust arbitrary user input as a database field. For example, do not do:

```python
movies.order_by(request.GET["sort"])
```

Instead:

```python
SORT_OPTIONS = {
    "default": "-id",
    "title_asc": "name",
    "title_desc": "-name",
    "rating_desc": "-rating",
    "rating_asc": "rating",
}
```

For `popular`, use:

```python
Movie.objects.annotate(booking_count=Count("booking")).order_by("-booking_count")
```

The exact reverse query name should be verified during implementation. Since `Booking.movie` has no `related_name`, the query path is likely `booking`.

## 6. Pagination Plan

Use Django `Paginator`.

Recommended page size:

- 12 movies per page for a card grid.
- 20 movies is also acceptable, but 12 fits the existing three-column layout.

Rules:

- Apply search and filters first.
- Apply sorting second.
- Apply pagination last.
- Preserve filters in pagination links.
- Handle invalid page values safely.
- Do not load all movies into memory.

Implementation idea:

```python
paginator = Paginator(movie_queryset, 12)
page_obj = paginator.get_page(request.GET.get("page"))
```

For pagination links, keep the current query string except `page`, then append the new page number.

## 7. Dynamic Filter Counts Plan

Dynamic counts are faceted counts. They show how many results would be available for each filter option.

### Genre counts

Recommended behavior:

- Apply search filters.
- Apply language filters.
- Do not apply the currently selected genre filter when calculating genre counts.

This lets users see alternative genre options that are still available under the active search/language filters.

Example:

```python
base_for_genre_counts = Movie.objects.all()
base_for_genre_counts = apply_search(base_for_genre_counts)
base_for_genre_counts = apply_language_filter(base_for_genre_counts)

Genre.objects.filter(
    movies__in=base_for_genre_counts
).annotate(
    movie_count=Count("movies", distinct=True)
)
```

### Language counts

Recommended behavior:

- Apply search filters.
- Apply genre filters.
- Do not apply the currently selected language filter when calculating language counts.

Example:

```python
base_for_language_counts = Movie.objects.all()
base_for_language_counts = apply_search(base_for_language_counts)
base_for_language_counts = apply_genre_filter(base_for_language_counts)

Language.objects.filter(
    movies__in=base_for_language_counts
).annotate(
    movie_count=Count("movies", distinct=True)
)
```

Important:

- Do not loop through every movie in Python.
- Use database aggregation with `Count`.
- Use `distinct=True` when many-to-many joins could duplicate movie rows.
- Counts should be calculated before pagination, because counts describe the filtered catalog, not only the current page.

## 8. Query Optimization Plan

Use server-side Django ORM queries:

- `.filter()` for search and filter conditions.
- `.values()` and `.annotate()` for counts.
- `.order_by()` for sorting.
- `Paginator` for page limits.

Avoid:

- `list(Movie.objects.all())`
- Python loops over every movie for filtering.
- Python loops over every movie for counts.
- N+1 queries when displaying genres/language.

Recommended queryset display optimization:

```python
movies = movies.select_related("language").prefetch_related("genres")
```

Use `distinct()` carefully:

- Filtering through `genres` can duplicate movie rows because of the many-to-many join.
- Use `.distinct()` after `genres__slug__in=selected_genres`.
- Avoid unnecessary `distinct()` when only filtering by `language`.

Suggested indexes:

| Field/index | Reason |
|---|---|
| `Movie.name` | Helps name sorting and exact/prefix lookup; note that `icontains` may need PostgreSQL trigram for large search |
| `Movie.rating` | Helps rating sorting |
| `Movie.language` | Foreign keys are indexed by default, helps language filtering |
| `Genre.slug` unique | Fast genre lookup from query params |
| `Language.code` unique | Fast language lookup from query params |
| Many-to-many join table indexes | Django creates indexes for join tables, supporting genre filtering |
| Optional PostgreSQL trigram index on `Movie.name` | Better scalable substring search if `icontains` becomes slow |

Full-table scan prevention:

- Filter lookup fields should be indexed.
- Pagination limits returned rows.
- Dynamic counts are database aggregations.
- Many-to-many join tables have indexes.
- PostgreSQL query planning handles indexed joins better than SQLite.

Search caveat:

A normal B-tree index on `Movie.name` may not speed up `name__icontains` on every database. For production search at larger scale, consider PostgreSQL trigram indexes or full-text search. For a 5,000-movie beginner catalog, indexed filters plus pagination are the most important first step.

## 9. Large Catalog / 5,000 Movie Dataset Plan

Plan a management command:

```bash
python manage.py generate_movie_catalog_demo_data --movies 5000
```

Command behavior:

- Create demo/test data only.
- Do not run automatically in production.
- Create demo genres.
- Create demo languages.
- Create 5,000 movies by default when requested.
- Assign each movie 1-3 genres.
- Assign each movie one primary language.
- Use `bulk_create` for movies where possible.
- Use many-to-many bulk insert through the `Movie.genres.through` table where practical.
- Use unique names and slugs/codes.
- Reuse existing demo genres/languages if already present.
- Print a clear summary.

Tests should use a smaller number, such as:

```bash
python manage.py generate_movie_catalog_demo_data --movies 50
```

Do not generate 5,000 movies during normal automated tests.

## 10. URL and Query Parameter Design

Existing movie list URL:

```text
/movies/
```

Recommended query parameter style:

```text
/movies/?genres=action&genres=drama&languages=hindi&languages=english&search=avengers&sort=rating_desc&page=2
```

Use repeated parameters because Django supports:

```python
request.GET.getlist("genres")
request.GET.getlist("languages")
```

Avoid comma-separated values for the first implementation because repeated parameters are easier to parse and preserve in Django forms.

Supported params:

- `genres`: repeated genre slugs.
- `languages`: repeated language codes.
- `search`: movie name search.
- `sort`: whitelisted sorting option.
- `page`: pagination page number.

Pagination links must preserve all current params except the old `page`.

## 11. Template/UI Plan

Update `templates/movies/movie_list.html`.

The page should show:

- Search box.
- Genre filter checkboxes with counts.
- Language filter checkboxes with counts.
- Sorting dropdown.
- Movie result grid.
- Pagination controls.
- Active filter summary.
- Clear filters link.

UX rules:

- Selected genre checkboxes stay checked after request.
- Selected language checkboxes stay checked after request.
- Selected sort option stays selected.
- Search text stays in the search box.
- Pagination links preserve current filters.
- Clear filters returns to `/movies/`.

The existing client-side filtering script should be removed or made harmless because backend filtering is the source of truth.

## 12. Files Expected To Change Later

| File path | Planned change | Reason |
|---|---|---|
| `movies/models.py` | Add `Genre`, `Language`, `Movie.genres`, `Movie.language`, and indexes | Store normalized filter data and improve query performance |
| `movies/views.py` | Update `movie_list` to apply search, filters, sorting, pagination, and dynamic counts | Main server-side filtering implementation |
| `movies/urls.py` | Likely no route change, unless a helper endpoint is added later | Existing `/movies/` route can support query params |
| `movies/admin.py` | Register `Genre` and `Language`; expose movie genre/language fields | Make catalog data manageable from Django admin |
| `movies/tests.py` | Add model, filtering, sorting, pagination, counts, and demo command tests | Prove Task 5 works and Tasks 1-4 still pass |
| `templates/movies/movie_list.html` | Add filter UI, sorting dropdown, counts, pagination, active filters | User-facing catalog filtering |
| `templates/home.html` | Optional update if homepage should show genre/language info or link to filtered lists | Keep homepage consistent with movie browsing |
| `movies/management/commands/generate_movie_catalog_demo_data.py` | New command for 5,000-movie demo catalog | Manual performance/data testing |
| `movies/migrations/0006_*.py` | Migration for new models and fields | Apply schema changes |
| `docs/task-05-scalable-genre-language-filtering-plan.md` | This planning document | Document approach before implementation |

## 13. Testing Plan

Manual tests:

- Filter by one genre.
- Filter by multiple genres.
- Filter by one language.
- Filter by multiple languages.
- Combine genre and language filters.
- Combine search, genre, and language filters.
- Sort with filters.
- Paginate with filters.
- Verify selected checkboxes persist.
- Verify dynamic genre counts update.
- Verify dynamic language counts update.
- Generate 5,000 movies and confirm the page still loads.
- Confirm Task 1 movie detail/trailer still works.
- Confirm Task 2 reservation flow still works.
- Confirm Task 3 payment flow still works.
- Confirm Task 4 admin dashboard still works.

Automated tests:

- `Genre` model creation.
- `Language` model creation.
- Movie genre/language assignment.
- Single genre filter.
- Multi-genre OR filter.
- Single language filter.
- Multi-language filter.
- Combined genre and language filters.
- Search plus filters.
- Sorting whitelist.
- Invalid sort falls back safely.
- Pagination returns expected page size.
- Pagination preserves filters if practical.
- Dynamic genre counts are correct.
- Dynamic language counts are correct.
- Demo catalog command creates requested small count.
- Existing Task 1-4 tests still pass.

Testing performance note:

Unit tests should not create 5,000 movies by default. Use a small command count in tests and reserve the 5,000-movie command for manual performance testing.

## 14. Performance Justification

Filtering happens in the database, not the browser and not Python loops.

Genre filtering uses a many-to-many join. That is flexible and correct for movies with multiple genres, but it may require `distinct()` to avoid duplicate movie rows.

Language uses a `ForeignKey`, which is faster and simpler for one primary movie language. Multi-select language filtering still works with `language__code__in`.

Indexes improve lookup and sorting on common fields:

- genre slug
- language code
- movie language foreign key
- movie rating
- movie name where appropriate

Pagination limits the number of movie rows rendered in each response.

Dynamic counts use database aggregation with `Count`, not Python loops.

PostgreSQL is recommended for production because it has better indexing options, stronger query planning, and optional trigram/full-text search. SQLite is acceptable for local development and beginner testing.

## 15. Trade-Offs Between Flexibility and Scalability

Multi-select filters improve user experience, but they require joins and aggregation.

OR genre filtering is user-friendly and scalable. It asks, "show movies that match any selected genre."

AND genre filtering is more precise but more expensive. It requires grouping by movie and checking that each movie matched every selected genre.

Dynamic counts are useful but add extra aggregation queries. For 5,000 movies, database aggregation should be fine. If the catalog becomes much larger, counts could be cached.

Denormalized counters could be added later for extreme scale, but they add write complexity and are not needed for the first implementation.

The recommended design balances flexibility and scalability:

- Many-to-many genres for real catalog behavior.
- Foreign-key primary language for faster language filtering.
- Server-side filters and pagination.
- Database aggregation for counts.
- PostgreSQL recommendation for production.

## 16. Acceptance Criteria

Task 5 will be complete when:

- Users can filter movies by genre.
- Users can filter movies by multiple genres.
- Users can filter movies by language.
- Users can filter movies by multiple languages.
- Filters are server-side.
- Pagination works with filters.
- Sorting works with filters.
- Dynamic genre counts are accurate.
- Dynamic language counts are accurate.
- Queries use database filtering and aggregation.
- Indexes are added.
- A 5,000-movie demo data command exists.
- Implementation avoids loading the entire catalog into memory.
- Query performance decisions are documented.
- Flexibility/scalability trade-offs are documented.
- Existing Tasks 1-4 still pass.
- `python manage.py check` passes.
- `python manage.py test` passes.

## 17. Final Summary

The planned implementation will normalize movie genre and language data, update `/movies/` to use server-side multi-select filtering, add sorting and pagination, and calculate dynamic filter counts with database aggregation.

The recommended model design is many-to-many genres plus one primary language foreign key. This supports multi-select filters while keeping language filtering simple and efficient.

Implementation has not been done yet. This file is only the planning document.

Next instruction needed:

```text
Please implement Task 5 using this plan.
```
