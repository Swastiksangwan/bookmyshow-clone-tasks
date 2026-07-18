# Task 5: Scalable Genre and Language Filtering with Query Optimization

## 1. Original Task Requirement

The movie list needed server-side filtering by genre and language, multi-select filters, sorting, pagination, dynamic filter counts, indexes, and support for large catalogs of 5,000+ movies. Filtering could not be frontend-only.

## 2. Implemented Solution

The project added normalized `Genre` and `Language` models. `Movie` now supports multiple genres through a many-to-many relation and one primary language through a foreign key.

The `/movies/` page reads repeated query parameters with `request.GET.getlist()`, applies filters through Django ORM queries, sorts with a whitelist, calculates dynamic counts before pagination, and displays 12 movies per page.

## 3. Architecture and Processing Flow

```text
GET /movies/?genres=action&languages=hindi&sort=rating_desc&page=2
-> parse search/genres/languages/sort
-> apply search
-> apply genre OR filter
-> apply language OR filter
-> apply safe sorting
-> calculate dynamic genre/language counts before pagination
-> select_related/prefetch_related
-> Paginator page
-> templates/movies/movie_list.html
```

## 4. Data Model or Schema Changes

`Genre`:

- `name`
- `slug`
- ordered by name

`Language`:

- `name`
- `code`
- ordered by name

`Movie`:

- `genres = ManyToManyField(Genre, related_name="movies", blank=True)`
- `language = ForeignKey(Language, related_name="movies", null=True, blank=True, on_delete=SET_NULL)`

Indexes:

- `Movie.name`
- `Movie.rating`
- `Movie.language`

Unique `Genre.slug` and `Language.code` also create indexes. Django's many-to-many join table includes indexes for the relationship.

## 5. Security / Concurrency / Performance Decisions

- Filtering is performed server-side through Django ORM.
- Search uses `name__icontains`.
- Genre multi-select uses OR behavior with `genres__slug__in`.
- Language multi-select uses OR behavior with `language__code__in`.
- Combined filters use AND behavior between search, genres, and languages.
- Sorting uses a whitelist and never trusts arbitrary field names from query parameters.
- Popular sorting uses booking count aggregation.
- Pagination happens after filtering and sorting.
- Dynamic counts are calculated before pagination.
- `select_related("language")` and `prefetch_related("genres")` avoid N+1 display queries.
- `distinct()` is used after many-to-many genre filtering to avoid duplicate movies.

## 6. Important Files

| File | Purpose |
| --- | --- |
| `movies/models.py` | Defines `Genre`, `Language`, movie relations, and movie indexes. |
| `movies/views.py` | Implements search, filters, safe sorting, dynamic counts, and pagination. |
| `templates/movies/movie_list.html` | Filter UI, active chips, movie cards, and pagination. |
| `movies/admin.py` | Admin management for genres, languages, and movie metadata. |
| `movies/management/commands/generate_movie_catalog_demo_data.py` | Creates demo catalogs up to 5,000 movies. |
| `movies/tests.py` | Tests filter semantics, counts, sorting, pagination, and demo command. |
| `static/css/bookmyseat.css` | Polished responsive movie list and filter styling. |

## 7. Edge Cases Handled

- Invalid sort value: falls back to default ordering.
- No filters: shows paginated default results.
- No matching movies: empty state.
- Multiple selected genres: matches any selected genre.
- Multiple selected languages: matches any selected language.
- Search combined with filters: all conditions apply.
- Pagination links preserve active query parameters.
- Selected checkboxes remain checked.
- Counts are based on filtered catalog before pagination, not only current page.

## 8. Automated Tests

Tests cover:

- Genre and Language model creation.
- Movie genre/language assignment.
- Single and multi-genre filtering.
- Single and multi-language filtering.
- Combined genre/language filtering.
- Search plus filters.
- Title/rating sorting.
- Invalid sort fallback.
- Popular sorting.
- Pagination size and query parameter preservation.
- Dynamic faceted counts.
- Demo catalog command with a small test volume.
- Existing Task 1-4 and Task 6 compatibility through the full suite.

## 9. Manual Verification

1. Open `/movies/`.
2. Search by movie name.
3. Select one genre.
4. Select multiple genres.
5. Select one or more languages.
6. Combine search, genre, and language filters.
7. Try each sort option.
8. Move between pages and confirm filters remain active.
9. Run `python manage.py generate_movie_catalog_demo_data --movies 5000` only when large demo data is desired.
10. Confirm movie detail links still open.

## 10. Trade-offs and Production Notes

Many-to-many genres are flexible but add joins and sometimes require `distinct()`. A foreign-key language keeps primary-language filtering simpler and faster while still supporting multi-select language filters through `language__code__in`.

OR genre filtering is more common and scalable for browsing than AND filtering. Dynamic counts are useful but add aggregation queries; caching or denormalized counters could be added for much larger catalogs. PostgreSQL is recommended for production-scale filtering and indexed joins, while SQLite is fine for local development.

## 11. Completion Status

Task 5 is implemented and tested. The final UI polish keeps the same backend filtering semantics and optimized query flow.
