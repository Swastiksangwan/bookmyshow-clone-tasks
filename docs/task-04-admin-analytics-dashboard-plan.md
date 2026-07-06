# Task 04: Advanced Admin Analytics Dashboard with Aggregation Optimization

## 1. Task Overview

Task 4 will add a secure analytics dashboard for administrators. The dashboard will show important business metrics for the movie booking project, including revenue, popular movies, theater occupancy, peak booking hours, and cancellation rate.

This dashboard must be restricted because it exposes business data. Normal users should not be able to see revenue totals, payment attempts, cancellation information, or booking trends. Access must be checked on the server for both the dashboard page and any analytics API endpoint.

The dashboard must use database aggregation because the project should handle at least 50,000 bookings. Loading all bookings into Python memory and looping over them would become slow, memory-heavy, and difficult to scale. The database is much better at grouped counts, sums, date filtering, and ordering.

Caching is needed because analytics queries can be expensive. If multiple admins refresh the dashboard repeatedly, the app should not rerun every aggregation query each time. A short cache time keeps the dashboard near real-time while protecting the database from repeated work.

Admin credentials must be stored as hashed passwords. Django already does this when users are created through `createsuperuser`, Django admin, or `User.objects.create_superuser()`. The project should never store plain-text production passwords in code, docs, environment files, fixtures, or Git.

If demo admin credentials are shared in a report later, they must be clearly marked as demo-only credentials. Real production admin passwords must never be committed or shared in project documentation.

This task builds on:

- Task 1: movie detail pages and safe trailer rendering.
- Task 2: reservation and final booking flow.
- Task 3: Razorpay-backed payment transactions and webhook-safe payment finalization.

For deployment, PostgreSQL is recommended. Task 2 needs stronger row-level locking behavior for real concurrency, Task 3 benefits from reliable transaction consistency, and Task 4 analytics will perform better with PostgreSQL indexes and query planning than with local SQLite.

## 2. Current Project Analysis

Files inspected before writing this plan:

- `movies/models.py`
- `movies/views.py`
- `movies/urls.py`
- `movies/admin.py`
- `movies/tests.py`
- `movies/management/commands/release_expired_reservations.py`
- `bookmyseat/settings.py`
- `templates/`
- `users/`
- `requirements.txt`
- `docs/task-01-youtube-trailer-embedding-plan.md`
- `docs/task-02-seat-reservation-timeout-plan.md`
- `docs/task-03-payment-idempotency-webhooks-plan.md`

Existing models in `movies/models.py`:

- `Movie`: stores movie name, poster image, rating, cast, description, and the Task 1 `trailer_url`.
- `Theater`: stores a theater/showtime for one movie.
- `Seat`: stores seats for a theater and a permanent `is_booked` flag.
- `SeatReservation`: added by Task 2. Temporarily reserves seats with statuses `RESERVED`, `CONFIRMED`, `EXPIRED`, and `CANCELLED`.
- `Booking`: stores final confirmed bookings. `Booking.seat` is a `OneToOneField`, so a seat can only have one final booking.
- `PaymentTransaction`: added by Task 3. Stores Razorpay order/payment IDs, payment amount in paise, currency, status, idempotency key, verification time, and raw provider payload.
- `PaymentWebhookEvent`: added by Task 3. Stores webhook event IDs, event type, processing status, raw payload, and signature validity.

Current user authentication:

- The project uses Django's built-in `auth.User`.
- Registration, login, logout, profile, and password reset views live in `users/views.py` and `users/urls.py`.
- Passwords are hashed by Django's auth system.
- The profile page shows the current user's final `Booking` rows.

Current admin availability:

- Django admin is available at `/admin/`.
- `Movie`, `Theater`, `Seat`, `Booking`, `SeatReservation`, `PaymentTransaction`, and `PaymentWebhookEvent` are registered in `movies/admin.py`.
- There is no custom analytics dashboard outside the default Django admin.

Current payment and revenue source from Task 3:

- Revenue should come from `PaymentTransaction`.
- A successful payment and finalized booking are represented by `PaymentTransaction.status == "CAPTURED"`.
- Payment amount is stored in paise in `PaymentTransaction.amount`.
- Payment verification/finalization time is stored in `PaymentTransaction.verified_at`.

Current booking source from Task 2 and Task 3:

- Final booking analytics should come from `Booking`.
- A `Booking` row is created only after a reservation is confirmed through verified payment.
- Each booked seat has one `Booking` row.
- Booking time is stored in `Booking.booked_at`.

Current limitations:

- There is no custom analytics dashboard.
- There is no analytics-specific API endpoint.
- There is no role-based analytics permission beyond normal login and Django admin flags.
- There is no analytics caching configuration.
- There is no performance test or seed command for 50,000 bookings.
- There are no analytics-focused indexes on payment status/date fields or booking time fields.
- The local database is SQLite, which is useful for development but not ideal for production analytics or high-concurrency booking behavior.

## 3. Analytics Definitions

### A. Total Revenue

Source: `PaymentTransaction`.

Rules:

- Include only rows where `status == "CAPTURED"`.
- Sum the `amount` field.
- `amount` is stored in paise.
- Display revenue in rupees by dividing paise by 100.
- Use `verified_at` as the capture/verification timestamp.
- Captured rows with missing `verified_at` should be treated carefully. The first implementation can exclude them, because Task 3 sets `verified_at` when finalizing payment.

Time windows:

- Daily revenue: captured payments verified from today's start to now, using Django timezone-aware datetimes.
- Weekly revenue: captured payments verified in the last 7 days. This is a rolling 7-day window, not calendar Monday-Sunday.
- Monthly revenue: captured payments verified during the current calendar month.

Example ORM direction:

```python
PaymentTransaction.objects.filter(
    status=PaymentTransaction.STATUS_CAPTURED,
    verified_at__gte=start_time,
).aggregate(total=Sum("amount"))
```

### B. Most Popular Movies

Source: `Booking`.

Rules:

- Group by `movie`.
- Count `Booking` rows.
- Since one `Booking` row represents one booked seat, the count also means seats booked.
- Sort by booking count descending.
- Limit the display to a small number, such as top 5 or top 10.

Example ORM direction:

```python
Booking.objects.values("movie_id", "movie__name").annotate(
    booking_count=Count("id")
).order_by("-booking_count")[:10]
```

### C. Busiest Theaters

Source: `Booking` and `Seat`.

Definition:

```text
occupancy_rate = booked seats for theater / total seats for theater * 100
```

Rules:

- `booked seats` should be counted from `Booking` rows grouped by theater.
- `total seats` should be counted from `Seat` rows grouped by theater.
- The calculation should happen with database aggregation, not Python loops over every seat or booking.
- Sort by occupancy rate descending.
- Limit to top 5 or top 10.

Implementation note:

Because `Theater` represents a movie/showtime in this project, occupancy rate is per theater/showtime record. A theater record with 30 seats and 24 bookings has an 80 percent occupancy rate.

### D. Peak Booking Hours

Source: `Booking.booked_at`.

Rules:

- Group bookings by hour of day.
- Use Django database functions such as `ExtractHour`.
- Count bookings per hour.
- Sort descending by booking count.
- Display hour labels clearly, for example `14:00 - 14:59`.

Example ORM direction:

```python
Booking.objects.annotate(hour=ExtractHour("booked_at")).values("hour").annotate(
    booking_count=Count("id")
).order_by("-booking_count")
```

### E. Cancellation Rate

Source: `PaymentTransaction`.

Formula:

```text
cancellation_rate = cancelled payment attempts / total payment attempts * 100
```

Rules:

- A cancelled attempt is `PaymentTransaction.status == "CANCELLED"`.
- Total payment attempts are all `PaymentTransaction` rows in the selected reporting window.
- The first implementation should use the current calendar month as the default reporting window for cancellation rate.
- Failed payments are not counted as cancellations in this first version. A separate failed-payment rate can be added later.
- If there are zero payment attempts, show `0%` instead of dividing by zero.

## 4. Security and Role-Based Authentication Plan

Use Django's built-in authentication and authorization. The dashboard should not introduce custom password handling.

Admin credentials:

- Django stores user passwords as hashes.
- Admin accounts should be created with `python manage.py createsuperuser`, Django admin, or `User.objects.create_superuser()`.
- Real production passwords must never be written to code, docs, Git commits, screenshots, or `.env.example`.
- Any shared password in a final report should be demo-only and clearly labeled.

Access control options:

- Allow `is_superuser=True`.
- Allow `is_staff=True` if the project owner wants all staff users to see analytics.
- Optionally allow members of a dedicated group named `analytics_admin`.

Recommended beginner-friendly helper:

```python
def can_view_analytics(user):
    return (
        user.is_authenticated
        and user.is_active
        and (
            user.is_staff
            or user.is_superuser
            or user.groups.filter(name="analytics_admin").exists()
        )
    )
```

Dashboard view rules:

- Protect the dashboard view server-side.
- Anonymous users should be redirected to login or receive 403 depending on the decorator used.
- Logged-in normal users should receive 403.
- Do not rely on hiding navbar links.
- Do not trust any role value submitted by a browser form.

Analytics API rules:

- The analytics JSON endpoint must use the same permission check as the HTML dashboard.
- Unauthorized API requests must return 403 or redirect to login.
- The API must not expose Razorpay secrets, webhook secrets, raw provider payloads, user passwords, session keys, or admin credentials.

Privilege escalation prevention:

- Never store a user's role manually in frontend JavaScript.
- Never trust role values stored in request data.
- Always check `request.user` permissions from the database.
- Keep CSRF protection enabled for logged-in admin actions.
- Use Django session authentication normally.
- If a user's permissions change, future requests should use the updated database-backed user permissions, not stale frontend state.

## 5. Dashboard Design Plan

Recommended URL:

```text
/movies/admin-dashboard/
```

This keeps the dashboard inside the existing `movies` app routes. A shorter `/admin-dashboard/` route could also work, but `/movies/admin-dashboard/` is simpler because the analytics are movie/payment related.

Dashboard sections:

- Revenue today card.
- Revenue last 7 days card.
- Revenue this month card.
- Most popular movies table.
- Busiest theaters table with occupancy rate.
- Peak booking hours table or simple chart-like table.
- Cancellation rate card.
- Cache timestamp or "Last refreshed" text.

UI approach:

- Use the existing Bootstrap style from `templates/users/basic.html`.
- Keep the page simple and readable.
- Avoid exposing raw payment payloads.
- Optionally add a staff-only navbar link later, but access must still be enforced server-side.

## 6. API Design Plan

Optional but recommended endpoint:

```text
GET /movies/admin-dashboard/api/analytics/
```

Purpose:

- Return the same cached analytics data as JSON.
- Make it easy to manually test unauthorized API access.
- Support future dashboard auto-refresh without reloading the whole page.

Security rules:

- Require the same admin/staff/group permission as the dashboard page.
- Return 403 for normal authenticated users.
- Redirect or return 403 for anonymous users, depending on the chosen decorator/helper.
- Do not expose sensitive payment secrets.
- Do not expose raw webhook payloads or full payment provider payloads.

Example JSON shape:

```json
{
  "revenue": {
    "today_paise": 20000,
    "last_7_days_paise": 140000,
    "current_month_paise": 600000,
    "today_rupees": 200.0,
    "last_7_days_rupees": 1400.0,
    "current_month_rupees": 6000.0
  },
  "popular_movies": [],
  "busiest_theaters": [],
  "peak_booking_hours": [],
  "cancellation_rate": 10.0,
  "generated_at": "2026-07-05T12:00:00Z"
}
```

## 7. Query Optimization Plan

Use Django ORM aggregation:

- `aggregate(Sum())` for revenue totals.
- `annotate(Count())` for popular movies and booking counts.
- `ExtractHour` for peak booking hours.
- `TruncDate` if later daily chart data is needed.
- `F` expressions or database calculations for occupancy rate where practical.
- `.values()` plus `.annotate()` plus `.order_by()` for grouped query results.

Avoid these patterns:

- Do not use `list(Booking.objects.all())` for analytics.
- Do not loop over all 50,000 bookings in Python to calculate totals.
- Do not load every `PaymentTransaction` into memory to sum revenue.
- Do not query each movie or theater one by one inside a loop.

Use `.select_related()` only when displaying a small final result set. For example, it is fine for a top 10 list after aggregation, but not for loading all bookings.

Suggested indexes:

| Model | Index | Reason |
|---|---|---|
| `Booking` | `booked_at` | Speeds date/hour based booking analytics |
| `Booking` | `movie` | Foreign keys usually create indexes, but movie grouping depends on this |
| `Booking` | `theater` | Foreign keys usually create indexes, but theater occupancy depends on this |
| `PaymentTransaction` | `status` | Speeds filtering captured/cancelled payments |
| `PaymentTransaction` | `verified_at` | Speeds revenue date windows |
| `PaymentTransaction` | `created_at` | Speeds payment attempt and cancellation windows |
| `PaymentTransaction` | `status`, `verified_at` | Speeds captured revenue by date |
| `PaymentTransaction` | `status`, `created_at` | Speeds cancellation rate by date |
| `Seat` | `theater` | Foreign key index supports total seats per theater |
| `SeatReservation` | `status`, `expires_at` | Supports existing timeout cleanup and availability checks |

Implementation note:

Django creates indexes for `ForeignKey` fields by default, but it is still useful to document the fields that analytics depends on. Later implementation should add explicit indexes only where they are missing or where a composite index helps the query.

## 8. Caching Plan

Use Django's cache framework.

Local development:

- Use `LocMemCache`.
- This avoids adding new dependencies for the beginner project.
- It works for local testing and small deployments.

Recommended cache key:

```text
admin_dashboard_analytics_v1
```

Recommended TTL:

```text
60 seconds
```

Why 60 seconds:

- It keeps the dashboard near real-time.
- It prevents repeated expensive aggregation queries on every refresh.
- It is easy for beginners to understand and test.

Redis-ready deployment note:

- For production, Redis is recommended if the app runs on multiple processes or servers.
- `LocMemCache` is per process, so each process has its own cache.
- A future deployment can switch to Redis through Django's `CACHES` setting, likely using `django-redis`.

Manual refresh strategy:

- First implementation can rely on TTL expiry.
- Optional later improvement: add a staff-only refresh button that deletes the cache key and reloads analytics.
- Any refresh action should be protected with CSRF.

Real-time meaning:

For this project, "real-time" should mean near-real-time with a short cache TTL. The dashboard may be up to about 60 seconds behind the database.

## 9. Large Dataset / 50,000 Booking Plan

Plan a demo-data management command:

```bash
python manage.py generate_analytics_demo_data --bookings 50000
```

Purpose:

- Create enough demo data to test analytics performance.
- Avoid doing this automatically in production.
- Make it easy to verify the dashboard with at least 50,000 bookings.

Recommended command behavior:

- Create demo movies if needed.
- Create demo theaters/showtimes if needed.
- Create enough seats for the requested number of bookings.
- Create demo users if needed.
- Create `Booking` rows efficiently with `bulk_create`.
- Create matching `PaymentTransaction` rows efficiently with `bulk_create`.
- Include a mix of `CAPTURED`, `CANCELLED`, and possibly `FAILED` transactions so revenue and cancellation metrics have realistic data.
- Use unique `razorpay_order_id`, `razorpay_payment_id`, and `idempotency_key` values.
- Use realistic `booked_at`, `created_at`, and `verified_at` time ranges where possible.
- Print a clear warning that generated data is demo/test data only.

Important data design note:

Because `Booking.seat` is a `OneToOneField`, the command must create or use enough distinct `Seat` rows. It cannot create 50,000 bookings for the same seat.

Suggested scale shape:

- 10 movies.
- Multiple theaters/showtimes per movie.
- Enough seats per theater to exceed the requested booking count.
- 50,000 final bookings spread across those seats.

Testing note:

Automated tests should use much smaller numbers, such as 25 or 100 bookings, so the test suite stays fast. The management command should support 50,000 for manual performance testing.

## 10. Planned Model/Migration Changes

No major new analytics model is required for the first implementation. Analytics can be calculated from existing `Booking`, `PaymentTransaction`, `Seat`, and `SeatReservation` rows.

Likely model changes:

- Add indexes to `Booking`.
- Add indexes to `PaymentTransaction`.
- Optionally add an index to `SeatReservation` for `status` and `expires_at`.

These should be added through `Meta.indexes` in `movies/models.py`, followed by a migration.

Possible future model:

- A precomputed analytics snapshot model could be useful later for very large production datasets.
- It is not needed for this beginner-friendly first version because database aggregation plus caching is enough for the 50,000-booking target.

## 11. Planned View/Service Structure

Keep analytics logic separate from the view so it is easier to test.

Recommended new file:

```text
movies/analytics.py
```

Recommended helper functions:

```python
def get_admin_analytics():
    ...

def get_cached_admin_analytics():
    ...

def can_view_analytics(user):
    ...
```

Responsibilities:

- `get_admin_analytics()` performs database aggregation and returns a dictionary.
- `get_cached_admin_analytics()` reads/writes Django cache with a 60-second TTL.
- `can_view_analytics(user)` centralizes role checks for dashboard and API views.

View structure:

- `admin_dashboard(request)` loads cached analytics and renders HTML.
- `admin_dashboard_api(request)` returns cached analytics as JSON.
- Both views use the same permission helper.

This keeps `movies/views.py` from becoming too crowded and makes analytics tests simpler.

## 12. Files Expected To Change Later

| File path | Planned change | Reason |
|---|---|---|
| `movies/models.py` | Add analytics-related indexes to `Booking`, `PaymentTransaction`, and possibly `SeatReservation` | Speed up aggregation queries and timeout cleanup |
| `movies/views.py` | Add staff-protected dashboard and API views, or import them if moved to another module | Provide secure HTML and JSON analytics access |
| `movies/urls.py` | Add `/admin-dashboard/` and `/admin-dashboard/api/analytics/` routes | Make dashboard and API reachable |
| `movies/admin.py` | Optionally improve admin list filters/search for analytics-related models | Help admins inspect source data |
| `movies/tests.py` | Add access-control, aggregation, cache, and demo command tests | Prove dashboard security and metric correctness |
| `movies/analytics.py` | New service module for aggregation, caching, and permission helpers | Keep analytics code reusable and testable |
| `templates/movies/admin_dashboard.html` | New dashboard template | Display metrics to authorized admins |
| `bookmyseat/settings.py` | Add Django cache configuration, likely `LocMemCache` for local development | Enable analytics caching |
| `movies/management/commands/generate_analytics_demo_data.py` | New demo data command supporting `--bookings 50000` | Test dashboard performance with large data |
| `movies/migrations/0005_*.py` | Migration for new indexes | Apply database performance changes |
| `templates/users/basic.html` | Optional staff-only dashboard link | Make dashboard discoverable without relying on this for security |
| `docs/task-04-admin-analytics-dashboard-plan.md` | This planning document | Document the implementation approach before coding |

## 13. Testing Plan

Manual tests:

- Admin/staff user can access `/movies/admin-dashboard/`.
- Normal logged-in user cannot access `/movies/admin-dashboard/`.
- Anonymous user cannot access `/movies/admin-dashboard/`.
- Unauthorized request to `/movies/admin-dashboard/api/analytics/` is blocked.
- Dashboard shows daily, last 7 days, and current month revenue.
- Dashboard shows most popular movies.
- Dashboard shows busiest theaters by occupancy rate.
- Dashboard shows peak booking hours.
- Dashboard shows cancellation rate.
- Cache works: repeated page refreshes within 60 seconds should use cached data.
- Metrics update after cache expiry or a future refresh action.
- Generate 50,000 demo bookings and confirm the dashboard still loads without crashing.

Automated tests:

- Dashboard access control for anonymous, normal user, staff user, superuser, and optional `analytics_admin` group user.
- API access control for the same user types.
- Revenue aggregation includes only `CAPTURED` payments.
- Revenue aggregation excludes `FAILED`, `CANCELLED`, `CREATED`, and `REQUIRES_REVIEW` payments.
- Popular movies aggregation returns the correct movie order and counts.
- Theater occupancy calculation returns correct percentages.
- Peak booking hours aggregation groups by `Booking.booked_at` hour.
- Cancellation rate uses `CANCELLED / total attempts * 100`.
- Cancellation rate returns 0 when there are no attempts.
- Cache helper returns cached data on repeated calls.
- Demo data command can create a small requested volume in tests.
- Existing Task 1 trailer tests still pass.
- Existing Task 2 reservation tests still pass.
- Existing Task 3 payment and webhook tests still pass.

Performance testing notes:

- Unit tests should not create 50,000 rows by default.
- Manual performance testing should run the demo data command with `--bookings 50000`.
- During implementation, Django debug toolbar is not required. Query counts can be checked manually or with Django's test tools if needed.

## 14. Acceptance Criteria

Task 4 will be complete when:

- A secure admin analytics dashboard exists.
- Only authorized staff/superuser/analytics users can access it.
- Unauthorized dashboard and API access is blocked server-side.
- Daily revenue appears.
- Last 7 days revenue appears.
- Current month revenue appears.
- Most popular movies appear.
- Busiest theaters by occupancy appear.
- Peak booking hours appear.
- Cancellation rate appears.
- Analytics queries use database aggregation.
- The implementation avoids loading all bookings/payments into Python memory.
- Useful indexes are added through migrations.
- Django caching is implemented with a short TTL.
- A 50,000-booking demo data command exists, or the performance strategy is documented and testable.
- Admin/demo credentials are stored as hashed Django passwords.
- Any shared admin password is demo-only and not a production secret.
- Existing Task 1, Task 2, and Task 3 flows continue to work.
- `python manage.py check` passes.
- `python manage.py test` passes.

## 15. Final Summary

The planned Task 4 implementation will add a staff-only analytics dashboard and optional protected JSON API. Metrics will come from existing `Booking`, `Seat`, `PaymentTransaction`, and `SeatReservation` data. Revenue will use captured Razorpay payment transactions from Task 3. Booking popularity, theater occupancy, and peak hours will use final bookings created after Task 2 reservations and Task 3 payment verification.

The dashboard should use database aggregation, indexes, and a short Django cache TTL so it can handle at least 50,000 bookings without loading entire tables into memory. Local development can use in-memory cache, while production should use PostgreSQL and preferably Redis-backed cache.

Implementation has not been done yet. This file is only the planning document.

Next instruction needed:

```text
Please implement Task 4 using this plan.
```
