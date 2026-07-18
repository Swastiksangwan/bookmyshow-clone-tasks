# BookMySeat

## Live Application

Live URL: https://bookmyshow-clone-tasks.onrender.com

This app is hosted on Render. The free Render service can take about 30-60 seconds to wake after inactivity.

## Evaluator Access

Use only this restricted evaluation account:

- Website login URL: https://bookmyshow-clone-tasks.onrender.com/login/
- Django admin URL: https://bookmyshow-clone-tasks.onrender.com/admin/
- Analytics dashboard URL: https://bookmyshow-clone-tasks.onrender.com/movies/admin-dashboard/
- Username: `evaluator_admin`
- Password: `BookMySeatEval@2026`

This is an evaluation-only restricted account. It is not a superuser. It has read-only administrative access to project records and access to the analytics dashboard. Production systems must never publish administrator credentials.

The existing demo superuser credentials are intentionally not published.

## Project Overview

BookMySeat is a Django cinema booking system. Users can register, browse movies, inspect movie details, choose a theater/showtime, reserve seats for a short time, complete a Razorpay Test Mode payment, and then view confirmed bookings in their profile.

The project also includes secure trailer embedding, optimized movie filtering, admin analytics, payment webhook handling, and a queued ticket email confirmation system.

## Implemented Tasks

1. Secure YouTube trailer embedding with strict URL validation, safe iframe construction, lazy loading, and fallback UI.
2. Concurrency-safe two-minute seat reservations using `SeatReservation`, transactions, row locking where supported, and expiry cleanup.
3. Razorpay payment integration with server-side signature verification, idempotent booking finalization, and secure webhooks.
4. Optimized admin analytics dashboard with database aggregation, indexes, cache, API protection, and demo data generation.
5. Scalable genre/language filtering with server-side multi-select filters, dynamic counts, sorting, pagination, and catalog demo data.
6. Queued ticket confirmation emails with Django templates, retry tracking, logging, and a background queue processor.

## Core Features

- User authentication and profile management
- Movie browsing and detail pages
- Safe YouTube trailer validation and embedding
- Theater/showtime selection
- Two-minute temporary seat reservation
- Razorpay Test Mode checkout
- Server-verified booking creation
- Idempotent webhook processing
- User booking history
- Admin analytics dashboard
- Server-side genre/language filtering
- Database-backed ticket email queue

## Architecture

Main request and processing flow:

```text
Browser
-> Django URLs
-> Views and helper services
-> PostgreSQL or local SQLite
-> Razorpay Checkout
-> Signed callback or signed webhook
-> Idempotent booking finalization
-> Email notification queue
-> Background queue processor
```

The backend is the source of truth for reservation availability, payment verification, booking creation, analytics, and email queue state.

## Technology Stack

- Python with Django 3.2.19
- PostgreSQL on Render, SQLite for local development
- Razorpay Python SDK 2.0.1
- WhiteNoise 6.11.0 for static files
- Gunicorn 23.0.0 on Render
- Pillow for uploaded images
- `dj-database-url` for deployment database configuration
- Bootstrap 4 compatible templates with a shared custom stylesheet

## Database Models

Important models:

- `Movie`: movie title, image, rating, cast, description, trailer URL, genres, and language.
- `Genre` and `Language`: normalized filtering metadata.
- `Theater`: showtime for a movie.
- `Seat`: physical seat for a theater; `is_booked=True` means permanently booked.
- `SeatReservation`: temporary two-minute seat hold grouped by `reservation_token`.
- `Booking`: final confirmed ticket record; `Booking.seat` is a `OneToOneField`.
- `PaymentTransaction`: Razorpay order/payment state, idempotency key, and payment status.
- `PaymentWebhookEvent`: signed Razorpay webhook event log with duplicate protection.
- `BookingEmailNotification`: queued ticket confirmation email with retry state.

## Security Controls

- Django password hashing for all user accounts.
- CSRF protection on browser forms.
- Server-side authentication for profile, reservations, payments, and admin analytics.
- Role/group checks through Django auth for analytics access.
- Restricted evaluator account with staff access, no superuser status, and view-only project permissions.
- Safe YouTube validation using parsed HTTPS URLs and allowed domains only.
- YouTube iframe `src` is built only from a validated video ID.
- Razorpay checkout signatures are verified server-side using HMAC.
- Razorpay webhooks verify the raw request body before JSON is trusted.
- Payment and webhook duplicate handling is idempotent.
- Database transactions protect booking finalization.
- Secrets are read from environment variables.
- Raw payment payloads, SMTP credentials, webhook secrets, and session data are not exposed in templates, email content, or README.

## Concurrency and Consistency

Seat reservation and booking writes use `transaction.atomic()`. The code also uses `select_for_update()` on reservation and seat rows where supported. PostgreSQL provides true row-level locking for production deployment. SQLite is acceptable for local development but does not provide the same row-level locking behavior.

Active reservations are treated as unavailable only when `status='RESERVED'` and `expires_at` is in the future. Expired reservations do not block seats, even before the cleanup command marks them as expired. Final bookings use `Booking.seat` as a database-level duplicate-booking guard.

## Analytics and Query Optimization

The analytics dashboard calculates revenue, popular movies, theater occupancy, peak booking hours, and cancellation rate with Django ORM database aggregation. It avoids loading full booking/payment datasets into Python memory.

The project includes indexes for booking timestamps, booking movie/theater lookups, payment status/time windows, reservation expiry, and movie filtering. Analytics results are cached through Django cache for 60 seconds. Local development uses `LocMemCache`; Redis is a good production upgrade for multi-process deployments.

## Email Queue

Ticket emails are not sent inside the payment request. After successful booking finalization, the system creates one `BookingEmailNotification` row for the reservation/payment. The background command processes queued emails:

```bash
python manage.py process_email_queue
python manage.py process_email_queue --loop --interval 30
```

Email templates include subject, plain text, and HTML versions. Failures are recorded with `attempt_count`, `last_error`, and `next_retry_at`, and are visible in Django admin.

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_evaluation_data
python manage.py create_evaluator_admin
python manage.py runserver
```

Open:

- Website: http://127.0.0.1:8000/
- Movies: http://127.0.0.1:8000/movies/
- Admin: http://127.0.0.1:8000/admin/
- Analytics: http://127.0.0.1:8000/movies/admin-dashboard/

For local email queue processing:

```bash
python manage.py process_email_queue --loop --interval 30
```

## Environment Variables

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Django signing secret. Required when `DEBUG=False`. |
| `DEBUG` | Enables local development behavior when true. |
| `ALLOWED_HOSTS` | Comma-separated allowed hostnames. |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated trusted origins for HTTPS deployment. |
| `DATABASE_URL` | PostgreSQL connection URL for deployment. |
| `RAZORPAY_KEY_ID` | Public Razorpay test key ID exposed to Checkout. |
| `RAZORPAY_KEY_SECRET` | Server-only Razorpay secret for checkout signature verification. |
| `RAZORPAY_WEBHOOK_SECRET` | Server-only webhook HMAC secret. |
| `TICKET_PRICE_PAISE` | Per-seat ticket price in paise. |
| `PAYMENT_CURRENCY` | Payment currency, default `INR`. |
| `EMAIL_BACKEND` | Django email backend. Console backend is used by default locally. |
| `EMAIL_HOST` | SMTP host for production email. |
| `EMAIL_PORT` | SMTP port. |
| `EMAIL_USE_TLS` | Enables SMTP TLS. |
| `EMAIL_USE_SSL` | Enables SMTP SSL. |
| `EMAIL_HOST_USER` | SMTP username. |
| `EMAIL_HOST_PASSWORD` | SMTP password. |
| `DEFAULT_FROM_EMAIL` | Sender address for ticket emails. |
| `EVALUATOR_ADMIN_USERNAME` | Restricted evaluator username. |
| `EVALUATOR_ADMIN_EMAIL` | Restricted evaluator email. |
| `EVALUATOR_ADMIN_PASSWORD` | Restricted evaluator password. |
| `EMAIL_QUEUE_INTERVAL` | Background email queue loop interval in seconds. |

Never commit real values for `SECRET_KEY`, Razorpay secrets, webhook secrets, SMTP passwords, or production database URLs.

## Deployment

Render deployment uses:

- PostgreSQL through `DATABASE_URL`
- `build.sh` to install dependencies, collect static files, run migrations, seed evaluation data, and create/update the restricted evaluator account
- `start.sh` to run the email queue processor in the background and start Gunicorn
- WhiteNoise for static files
- Razorpay Test Mode keys from environment variables

The seed command is idempotent and does not create fake completed bookings or payments.

## Test Suite

Verified in this branch:

```bash
python manage.py test
```

Result: 90 tests passed.

## Project Structure

```text
bookmyseat/                 Django project settings and root URLs
movies/                     Movie, booking, payment, analytics, email logic
movies/management/commands/ Background and seed commands
templates/                  User-facing and email templates
static/css/                 Shared project stylesheet
static/images/              Original evaluation poster placeholders
users/                      Authentication/profile app
docs/                       Task implementation documentation
```

## Task Documentation

- [Task 1: YouTube Trailer Embedding](docs/task-01-youtube-trailer-embedding-plan.md)
- [Task 2: Seat Reservation Timeout](docs/task-02-seat-reservation-timeout-plan.md)
- [Task 3: Payment Idempotency and Webhooks](docs/task-03-payment-idempotency-webhooks-plan.md)
- [Task 4: Admin Analytics Dashboard](docs/task-04-admin-analytics-dashboard-plan.md)
- [Task 5: Genre and Language Filtering](docs/task-05-scalable-genre-language-filtering-plan.md)
- [Task 6: Ticket Email Confirmation](docs/task-06-ticket-email-confirmation-plan.md)

## Known Evaluation Notes

- Render free instances may take 30-60 seconds to wake.
- Razorpay runs in Test Mode.
- Evaluation titles use original placeholder poster designs committed under `static/images/evaluation-posters/`.
- Fictional evaluation movies intentionally show trailer fallback text unless a legitimate related trailer is available.
- Email delivery depends on the configured Django email backend.
- Local SQLite differs from production PostgreSQL for row-level locking and large-dataset performance.
