# Task 4: Advanced Admin Analytics Dashboard with Aggregation Optimization

## 1. Original Task Requirement

Admins needed a secure analytics dashboard showing revenue, popular movies, theater occupancy, peak booking hours, and cancellation rate. The implementation had to restrict access, avoid loading large datasets into memory, support 50,000+ booking demo data, add indexes, and use caching.

## 2. Implemented Solution

The project includes a custom dashboard at `/movies/admin-dashboard/` and a protected JSON API at `/movies/admin-dashboard/api/analytics/`. Both use the same server-side permission helper, `can_view_analytics()`.

Analytics are calculated in `movies/analytics.py` with Django ORM aggregation and cached for 60 seconds through Django's cache framework. Local development uses `LocMemCache`.

## 3. Architecture and Processing Flow

```text
Authenticated request
-> can_view_analytics(request.user)
-> get_cached_admin_analytics()
-> cache hit returns data
-> cache miss runs database aggregations
-> dashboard template or JSON API response
```

## 4. Data Model or Schema Changes

Task 4 added analytics-focused indexes:

- `Booking.booked_at`
- `Booking.movie + booked_at`
- `Booking.theater + booked_at`
- `PaymentTransaction.status + verified_at`
- `PaymentTransaction.status + created_at`
- `SeatReservation.status + expires_at`

No separate analytics table is used.

## 5. Security / Concurrency / Performance Decisions

- Dashboard and API require login.
- Normal authenticated users receive 403.
- Staff, superusers, or members of `analytics_admin` can view analytics.
- The permission check uses Django auth/database state, not frontend role values.
- API output does not include payment secrets, webhook secrets, raw provider payloads, passwords, or session data.
- Queries use `.aggregate()`, `.annotate()`, `.values()`, `Count`, `Sum`, `ExtractHour`, `Case`, and expressions.
- The implementation avoids `list(Booking.objects.all())` and full-dataset Python loops.
- Results are cached under `admin_dashboard_analytics_v1` for 60 seconds.
- "Real-time" means near-real-time with a short cache TTL.

## 6. Important Files

| File | Purpose |
| --- | --- |
| `movies/analytics.py` | Aggregation, cache, permission helper, and currency formatting. |
| `movies/views.py` | Dashboard and API views. |
| `movies/urls.py` | Dashboard/API routes. |
| `templates/movies/admin_dashboard.html` | Admin analytics UI. |
| `movies/models.py` | Analytics indexes on booking/payment/reservation models. |
| `bookmyseat/settings.py` | LocMemCache configuration. |
| `movies/management/commands/generate_analytics_demo_data.py` | Creates demo analytics data efficiently. |
| `movies/management/commands/create_demo_admin.py` | Creates demo-only superuser when explicitly run. |
| `movies/tests.py` | Tests permissions, metrics, caching, and demo commands. |

## 7. Edge Cases Handled

- Anonymous user: redirected to login.
- Normal user: 403.
- Staff/superuser/group user: dashboard/API access.
- No payment attempts: cancellation rate is 0.
- No booking data: dashboard tables show empty states.
- Captured payments without `verified_at`: excluded from revenue.
- Cache hit: expensive aggregation is not repeated until TTL expires or cache is cleared.

## 8. Automated Tests

Tests cover:

- Permission helper behavior.
- Dashboard access control.
- API access control and secret safety.
- Captured-only revenue aggregation.
- Popular movie counts.
- Theater occupancy percentage.
- Peak booking hour grouping.
- Cancellation rate calculation.
- Cache reuse.
- Demo analytics data command with a small test volume.
- Demo admin command password hashing.

## 9. Manual Verification

1. Login with an authorized staff/evaluator account.
2. Open `/movies/admin-dashboard/`.
3. Confirm revenue cards, cancellation rate, popular movies, peak hours, and theater occupancy render.
4. Open `/movies/admin-dashboard/api/analytics/`.
5. Logout or login as a normal user and confirm access is blocked.
6. Run `python manage.py generate_analytics_demo_data --bookings 50000` only when demo data is desired.
7. Reload the dashboard and confirm it still loads without crashing.

## 10. Trade-offs and Production Notes

LocMemCache is simple and works locally. Redis is better for multi-process production deployments because each process otherwise has its own memory cache. PostgreSQL is recommended for production analytics because indexed joins and aggregations are stronger than SQLite for larger datasets.

The 50,000-booking command creates demo data only and is not run automatically in tests.

## 11. Completion Status

Task 4 is implemented and tested. The dashboard and API remain protected and use database aggregation with caching.
