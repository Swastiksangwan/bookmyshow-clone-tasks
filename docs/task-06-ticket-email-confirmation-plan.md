# Task 06: Automated Ticket Email Confirmation with Template Engine

## 1. Task Overview

Automated ticket email confirmation means the app sends a booking confirmation email to the user after a booking is successfully completed. The email should include the ticket details a user expects after payment, such as movie name, theater name, show timing, seat numbers, payment ID, and booking references.

The email must be sent only after a successful booking. In this project, that means after Task 3 has verified the Razorpay payment server-side and `finalize_paid_reservation()` has created the final `Booking` rows, marked the selected seats as booked, marked the `SeatReservation` rows as confirmed, and marked the `PaymentTransaction` as `CAPTURED`.

Email sending must not block the booking/payment response. SMTP servers and transactional email providers can be slow, temporarily unavailable, or rate limited. If the booking view waits for SMTP, the user may see a slow or failed response even though payment and booking succeeded. The booking response should finish quickly, and email delivery should happen in the background.

A template engine is needed because ticket emails have structured content. Django templates let the project maintain plain text and HTML email versions without hardcoding long email strings in Python.

Retry logic is needed because email delivery can fail for temporary reasons, such as SMTP timeout, provider outage, network issues, or rate limiting. A failed email should not undo the booking. Instead, the system should store the failure, retry later, and make the failure visible to admins.

SMTP credentials must be secure. Email host, username, password, TLS/SSL settings, and default sender should come from environment variables. Real SMTP credentials must never be committed to Git.

Logging and monitoring failed emails matters because a user may pay and book successfully but never receive the confirmation email. Admins need a way to see pending, failed, and sent notifications and understand why a delivery failed.

Local development can use Django's console email backend, which prints emails to the terminal. Production should use secure SMTP or a transactional email provider. PostgreSQL is recommended for production consistency and operational reliability, while local SQLite is acceptable for development.

## 2. Current Project Analysis

Files inspected before writing this plan:

- `movies/models.py`
- `movies/views.py`
- `movies/urls.py`
- `movies/admin.py`
- `movies/tests.py`
- `movies/management/commands/`
- `templates/`
- `templates/movies/reservation_confirm.html`
- `templates/users/profile.html`
- `users/models.py`
- `users/views.py`
- `bookmyseat/settings.py`
- `.env.example`
- `.gitignore`
- `requirements.txt`
- `docs/task-01-youtube-trailer-embedding-plan.md`
- `docs/task-02-seat-reservation-timeout-plan.md`
- `docs/task-03-payment-idempotency-webhooks-plan.md`
- `docs/task-04-admin-analytics-dashboard-plan.md`
- `docs/task-05-scalable-genre-language-filtering-plan.md`

Current booking-related models in `movies/models.py`:

- `Booking`
  - Stores final confirmed bookings.
  - Fields: `user`, `seat`, `movie`, `theater`, `booked_at`.
  - `seat` is a `OneToOneField`, so one seat can only have one final booking.
  - Task 4 added indexes on `booked_at`, `movie/booked_at`, and `theater/booked_at`.

- `SeatReservation`
  - Added by Task 2.
  - Stores temporary seat holds before payment.
  - Statuses: `RESERVED`, `CONFIRMED`, `EXPIRED`, `CANCELLED`.
  - Uses `reservation_token` to group seats selected in one reservation attempt.
  - Has helper methods `has_expired()` and `is_active()`.

- `PaymentTransaction`
  - Added by Task 3.
  - Stores Razorpay order/payment details and payment status.
  - Important fields for email: `user`, `reservation_token`, `razorpay_order_id`, `razorpay_payment_id`, `amount`, `currency`, `status`, `verified_at`.
  - `raw_provider_payload` exists but should not be included in emails.
  - A successful finalized payment uses `status == PaymentTransaction.STATUS_CAPTURED`.

- `PaymentWebhookEvent`
  - Added by Task 3.
  - Stores Razorpay webhook events and processing status.
  - Useful for payment audit, but not directly needed inside ticket emails.

Current successful payment finalization flow in `movies/views.py`:

- `reserve_seats()` creates 2-minute `SeatReservation` rows.
- `confirm_reservation()` creates or reuses a Razorpay order and renders the payment page.
- `verify_payment()` verifies the Razorpay checkout signature server-side and calls `finalize_paid_reservation()`.
- `razorpay_webhook()` validates Razorpay webhook signatures and may also call `finalize_paid_reservation()`.
- `finalize_paid_reservation()` is the central idempotent booking finalization helper.

Current `finalize_paid_reservation()` behavior:

1. Starts `transaction.atomic()`.
2. Locks the `PaymentTransaction` row with `select_for_update()`.
3. Locks matching `SeatReservation` rows.
4. Rejects missing, expired, inactive, or unsafe reservations.
5. Locks selected `Seat` rows.
6. Creates `Booking` rows.
7. Marks seats as permanently booked with `Seat.is_booked=True`.
8. Marks reservations as `CONFIRMED`.
9. Sets `PaymentTransaction.status` to `CAPTURED`.
10. Sets `PaymentTransaction.verified_at`.

This is the correct place to connect Task 6 because it is used by both frontend payment verification and Razorpay webhooks.

Current user email source:

- The project uses Django's built-in `auth.User`.
- `users.models.py` does not define a custom profile model.
- User email should come from `request.user.email` or `payment_transaction.user.email`.
- The profile form in `users/views.py` updates the Django user object, so the email field can be maintained there.

Current settings structure:

- `bookmyseat/settings.py` already reads important values from environment variables, including `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `DATABASE_URL`, Razorpay settings, ticket price, and payment currency.
- `EMAIL_BACKEND` is currently hardcoded to Django's console backend:
  `django.core.mail.backends.console.EmailBackend`.
- `.env.example` currently includes Razorpay and payment placeholders, but no email placeholders.
- `.gitignore` ignores `.env`, so local secrets should not be committed.

Current management command pattern:

- `release_expired_reservations` already supports one-time and loop mode processing.
- Task 4 added demo-data/admin commands.
- Task 6 can follow this same beginner-friendly command style for queue processing.

Current limitations:

- No email confirmation system.
- No email queue model.
- No email retry tracking.
- No email templates under `templates/emails/`.
- No admin monitoring for email delivery failures.
- No email-specific helper module.
- No background email processor command.
- No SMTP environment variable configuration beyond the current console backend.

## 3. Proposed Architecture

Use a simple database-backed email queue for this Django project.

Planned flow:

1. User selects seats.
2. Task 2 creates temporary `SeatReservation` rows.
3. Task 3 creates/reuses a Razorpay order.
4. Razorpay checkout or webhook confirms payment.
5. Backend verifies the payment signature or webhook signature.
6. `finalize_paid_reservation()` finalizes booking idempotently.
7. After final booking succeeds, create one `BookingEmailNotification` queue row.
8. Return the user response immediately.
9. A background command processes pending email queue rows.
10. The command renders subject/text/HTML templates.
11. The command sends email through Django's configured email backend.
12. The queue row is marked `SENT` or `FAILED`.
13. Failed rows are retried based on retry rules.

Why database-backed queue:

- It satisfies the background queue requirement without adding Celery, Redis, RabbitMQ, or another service.
- It is beginner-friendly and easy to inspect through Django admin.
- Queue creation is fast and happens in the database.
- Actual SMTP sending happens outside the booking/payment request.
- If the background worker is not running, emails stay `PENDING` and can be sent later.
- It can run locally with:

```bash
python manage.py process_email_queue
```

- It can run in loop mode with:

```bash
python manage.py process_email_queue --loop --interval 30
```

Production can later replace or extend this command with Celery + Redis, cron, Supervisor, systemd, platform scheduled jobs, or a hosted task runner.

Important architecture rule:

The queue row should be created only after booking finalization succeeds. The app must not queue a ticket email for a payment that failed, expired, requires review, or did not create final `Booking` rows.

## 4. Data Model Design

Add a model named `BookingEmailNotification`.

Suggested fields:

- `user`: `ForeignKey` to Django `User`, `on_delete=models.CASCADE`
- `booking`: `ForeignKey` to `Booking`, `null=True`, `blank=True`, `on_delete=models.SET_NULL`
- `payment_transaction`: `ForeignKey` to `PaymentTransaction`, `null=True`, `blank=True`, `on_delete=models.SET_NULL`
- `reservation_token`: `UUIDField`, `db_index=True`
- `recipient_email`: `EmailField`
- `subject`: `CharField(max_length=255)`
- `status`: `CharField` with choices:
  - `PENDING`
  - `SENDING`
  - `SENT`
  - `FAILED`
  - `CANCELLED`
- `attempt_count`: `PositiveIntegerField(default=0)`
- `max_attempts`: `PositiveIntegerField(default=3)`
- `next_retry_at`: `DateTimeField(null=True, blank=True)`
- `last_error`: `TextField(blank=True)`
- `provider_message_id`: `CharField(max_length=255, null=True, blank=True)`
- `created_at`: `DateTimeField(auto_now_add=True)`
- `updated_at`: `DateTimeField(auto_now=True)`
- `sent_at`: `DateTimeField(null=True, blank=True)`
- `payload`: `JSONField(default=dict, blank=True)`

Suggested class constants:

```python
STATUS_PENDING = "PENDING"
STATUS_SENDING = "SENDING"
STATUS_SENT = "SENT"
STATUS_FAILED = "FAILED"
STATUS_CANCELLED = "CANCELLED"
```

Important design decision:

One reservation can include multiple seats, and the current finalization code creates one `Booking` row per seat. The email should be one notification per reservation/payment, not one email per seat, because users expect one ticket confirmation email listing all seats.

Recommended approach:

- Use one `BookingEmailNotification` row per successful `PaymentTransaction`.
- Keep `booking` nullable because one email can represent several `Booking` rows.
- Store grouped ticket details in `payload`, such as booking IDs and seat numbers.
- Use `reservation_token` and `payment_transaction` for grouping.
- Add an idempotency rule to avoid duplicate email notifications.

Recommended idempotency protection:

- Add a unique constraint on `payment_transaction` when it is not null, or use `get_or_create(payment_transaction=payment_transaction)` in the enqueue helper.
- If conditional constraints are used, keep SQLite compatibility in mind.
- At minimum, the enqueue helper must check for an existing non-cancelled notification for the same `payment_transaction` or `reservation_token`.

Suggested payload structure:

```json
{
  "booking_ids": [1, 2, 3],
  "movie_name": "Example Movie",
  "theater_name": "Main Theater",
  "show_time": "2026-07-11T18:30:00+00:00",
  "seat_numbers": ["A1", "A2", "A3"],
  "payment_id": "pay_test_123",
  "razorpay_order_id": "order_test_123",
  "amount": 60000,
  "currency": "INR",
  "confirmed_at": "2026-07-11T10:15:00+00:00"
}
```

Sensitive values must not be stored in this payload. Do not store Razorpay key secret, webhook secret, SMTP password, user password, session data, or full raw provider payload.

## 5. Email Template Design

Use Django's template engine.

Create these templates later:

- `templates/emails/booking_confirmation_subject.txt`
- `templates/emails/booking_confirmation.txt`
- `templates/emails/booking_confirmation.html`

The subject template should be plain text and short, for example:

```text
Your BookMySeat ticket for {{ movie_name }}
```

The text template should be readable in plain email clients.

The HTML template should include the same information with simple structure. It should not depend on external CSS or JavaScript. Inline, minimal styling is acceptable for email compatibility.

Email should include:

- Customer name or username.
- Recipient email.
- Movie name.
- Theater name.
- Show timing.
- Seat numbers.
- Booking IDs or ticket references.
- Razorpay payment ID.
- Razorpay order ID if useful.
- Total amount and currency.
- Confirmation timestamp.
- A short support/contact note if useful.

Email must not include:

- `RAZORPAY_KEY_SECRET`
- `RAZORPAY_WEBHOOK_SECRET`
- SMTP username/password
- raw payment provider payload
- webhook raw payload
- Django session key
- user password or password hash
- internal debug tracebacks
- secret environment values

Template context should be built from the safe notification payload and safe model fields only.

## 6. SMTP / Email Configuration Plan

Update `bookmyseat/settings.py` later to read email settings from environment variables.

Suggested variables:

```text
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
EMAIL_HOST_USER=your_smtp_username
EMAIL_HOST_PASSWORD=your_smtp_password
DEFAULT_FROM_EMAIL=BookMySeat <noreply@example.com>
```

Local default:

- If SMTP is not configured, use:

```python
django.core.mail.backends.console.EmailBackend
```

- This prints emails in the terminal and is safe for beginner local development.

Production:

- Use Django SMTP backend or a transactional provider's SMTP settings.
- Use TLS or SSL.
- Store credentials in environment variables or deployment secret settings.
- Never commit real credentials.
- Update `.env.example` with placeholders only.
- Keep `.env` ignored by Git.

Example settings direction:

```python
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True").lower() in ("true", "1", "yes")
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "False").lower() in ("true", "1", "yes")
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "BookMySeat <noreply@localhost>")
```

## 7. Queue Creation Plan

Add a helper module later:

`movies/email_notifications.py`

Recommended functions:

- `build_booking_email_payload(payment_transaction)`
- `enqueue_booking_confirmation_email(payment_transaction)`
- `render_booking_confirmation_email(notification)`
- `send_booking_confirmation_email(notification)`

### `build_booking_email_payload(payment_transaction)`

Responsibilities:

- Load confirmed `SeatReservation` rows for the transaction's `reservation_token`.
- Load final `Booking` rows for the same user/seats.
- Build a safe payload with movie, theater, show time, seat numbers, booking IDs, payment ID, order ID, amount, currency, and confirmation time.
- Avoid raw provider payload.
- Avoid secrets.

### `enqueue_booking_confirmation_email(payment_transaction)`

Responsibilities:

- Run only when `payment_transaction.status == CAPTURED`.
- Check that final `Booking` rows exist.
- Check that the user has an email address.
- Create or reuse one notification for the payment transaction.
- Store safe subject and payload.
- Keep the function idempotent so duplicate payment verification or duplicate webhooks do not create duplicate emails.

Recommended behavior for missing user email:

- Do not crash payment finalization.
- Either do not enqueue and log a warning, or create a `FAILED` notification with `last_error="User email is missing."`
- The implementation should choose the option that gives the best admin visibility. For this project, creating a `FAILED` notification is useful because admins can see the reason.

### Where to call enqueueing

Best location:

- After `finalize_paid_reservation()` successfully commits booking changes.

Important transaction note:

- If the queue row is created inside the same transaction as booking finalization, it will roll back if booking finalization rolls back. That is good.
- However, actual SMTP sending must not happen inside that transaction.
- The later implementation can enqueue inside `finalize_paid_reservation()` right after `PaymentTransaction` becomes `CAPTURED`, or immediately after the helper returns success in `verify_payment()` and webhook handling.

Recommended for idempotency:

- Centralize enqueueing close to `finalize_paid_reservation()` so both frontend verification and webhook paths behave the same.
- Use `get_or_create` around `payment_transaction` to prevent duplicates.

## 8. Background Worker / Queue Processor Plan

Add a management command later:

`movies/management/commands/process_email_queue.py`

Command usage:

```bash
python manage.py process_email_queue
```

Options:

```bash
python manage.py process_email_queue --limit 50
python manage.py process_email_queue --loop --interval 30
```

Behavior:

1. Find notifications where:
   - `status` is `PENDING` or `FAILED`
   - `attempt_count < max_attempts`
   - `next_retry_at` is null or `next_retry_at <= timezone.now()`
2. Limit the batch size with `--limit`.
3. For each notification, mark it `SENDING`.
4. Render subject, text, and HTML templates.
5. Send email with Django `EmailMultiAlternatives`.
6. On success:
   - status = `SENT`
   - `sent_at = timezone.now()`
   - clear `last_error`
   - optionally store `provider_message_id` if available
7. On failure:
   - status = `FAILED`
   - increment `attempt_count`
   - store safe `last_error`
   - set `next_retry_at` using retry backoff
8. If max attempts are reached:
   - keep status `FAILED`
   - do not retry automatically until an admin manually resets it.

Loop mode:

- If `--loop` is provided, run the processor repeatedly every `--interval` seconds.
- Stop cleanly with `Ctrl+C`.
- This mirrors the existing `release_expired_reservations --loop --interval 30` pattern.

Production options:

- Run the command with Supervisor, systemd, Docker, cron, or platform scheduled jobs.
- Later replace the command with Celery + Redis if the app grows.
- Celery can reuse the same helper functions and model.

## 9. Retry Logic Plan

Email failure should not undo payment or booking. A confirmed booking remains confirmed even if email delivery fails.

Retry only email delivery, not booking/payment finalization.

Store:

- `attempt_count`
- `max_attempts`
- `last_error`
- `next_retry_at`
- `status`

Suggested retry backoff:

- First failure: retry after 1 minute.
- Second failure: retry after 5 minutes.
- Third failure: retry after 15 minutes.

After `max_attempts`:

- Keep status as `FAILED`.
- Do not retry forever.
- Admin can inspect the row in Django admin.
- A later improvement can add an admin action like "requeue selected notifications."

Important safety rule:

The retry command must send only the email. It must never recreate payment, seats, reservations, or bookings.

## 10. Logging and Monitoring Plan

Use Python logging in `movies/email_notifications.py` and the management command.

Logging plan:

- Log successful sends at `info` level.
- Log skipped notifications at `warning` level when user email is missing or notification data is invalid.
- Log send failures at `warning` or `error` level.
- Do not log SMTP password.
- Do not log Razorpay secrets.
- Do not log raw payment provider payload.
- Keep log messages useful but not sensitive.

Admin monitoring:

Register `BookingEmailNotification` in `movies/admin.py`.

Suggested admin display:

- `user`
- `recipient_email`
- `reservation_token`
- `payment_transaction`
- `status`
- `attempt_count`
- `max_attempts`
- `next_retry_at`
- `sent_at`
- `created_at`
- `updated_at`

Suggested filters:

- `status`
- `created_at`
- `sent_at`

Suggested search fields:

- `recipient_email`
- `reservation_token`
- `payment_transaction__razorpay_payment_id`
- `payment_transaction__razorpay_order_id`
- `user__username`

Suggested read-only fields:

- `created_at`
- `updated_at`
- `sent_at`
- `last_error`
- `payload`

This gives admins a simple monitoring screen for failed or delayed email deliveries.

## 11. Security Plan

SMTP credentials:

- Read credentials from environment variables.
- Keep `.env` ignored by Git.
- Use `.env.example` placeholders only.
- Never commit real provider credentials.

Email contents:

- Include only user-safe booking details.
- Do not include raw payment provider payload.
- Do not include webhook payload.
- Do not include internal exception tracebacks.
- Do not include secrets, password hashes, session IDs, or environment values.

Recipient safety:

- Use the authenticated user's stored `User.email` from the database.
- If the email is missing, do not crash booking finalization.
- Store a clear failure state for admin review.

Header injection prevention:

- Use Django email utilities such as `EmailMultiAlternatives`.
- Render subject from a plain text template.
- Strip newlines from the subject before sending.
- Do not concatenate untrusted raw input into email headers.

Template safety:

- Use Django template auto-escaping for HTML templates.
- Avoid `mark_safe`.
- Avoid `|safe` for user-controlled values.

Logging safety:

- Log notification IDs and safe identifiers.
- Do not log SMTP passwords, Razorpay secrets, raw payloads, or personal data beyond what is necessary.

Queue security:

- Queue processor should be a server-side management command, not a public URL.
- Admin monitoring should require Django admin/staff access.
- Email retry should not allow users to trigger arbitrary email sends.

## 12. Files Expected To Change Later

| File path | Planned change | Reason |
|---|---|---|
| `movies/models.py` | Add `BookingEmailNotification` model with queue status, retry fields, payload, and idempotency protection. | Store email work outside the request and track delivery status. |
| `movies/admin.py` | Register `BookingEmailNotification` with filters/search/read-only monitoring fields. | Let admins monitor pending, sent, and failed emails. |
| `movies/views.py` | Call enqueue helper only after successful booking finalization. | Queue email after payment and booking are complete without sending SMTP in the request. |
| `movies/email_notifications.py` | New helper module for payload building, enqueueing, rendering, and sending. | Keep email logic separate from payment views. |
| `movies/management/commands/process_email_queue.py` | New background queue processor with one-time and loop modes. | Send queued emails and retry failures outside the booking response. |
| `templates/emails/booking_confirmation_subject.txt` | New subject template. | Keep subject rendering in Django templates. |
| `templates/emails/booking_confirmation.txt` | New plain text email template. | Support plain email clients. |
| `templates/emails/booking_confirmation.html` | New HTML email template. | Send clean formatted ticket confirmation email. |
| `bookmyseat/settings.py` | Read email backend, SMTP host, port, TLS/SSL, username, password, and sender from environment variables. | Avoid hardcoded SMTP secrets and support local/production email backends. |
| `.env.example` | Add email placeholders only. | Show developers what env vars to configure without exposing secrets. |
| `movies/tests.py` | Add notification, enqueue, render, queue processing, retry, and security tests. | Verify email behavior and keep Tasks 1-5 passing. |
| `movies/migrations/0007_*.py` | Migration for `BookingEmailNotification`. | Apply the new queue table. |
| `docs/task-06-ticket-email-confirmation-plan.md` | This planning document. | Document Task 6 before implementation. |

## 13. Testing Plan

Automated tests:

- `BookingEmailNotification` model creation.
- Queue row is created after successful payment finalization.
- Duplicate frontend payment verification does not create duplicate email notifications.
- Duplicate webhook processing does not create duplicate email notifications.
- Subject template renders correctly.
- Plain text template renders correctly.
- HTML template renders correctly.
- Queue processor sends email using Django locmem or console/test email backend.
- Successful send marks notification `SENT`.
- Failed send increments `attempt_count`.
- Failed send sets `next_retry_at`.
- Max attempts stops automatic retry.
- Missing user email is handled safely and does not crash booking finalization.
- Email content does not include:
  - Razorpay key secret
  - Razorpay webhook secret
  - SMTP password
  - raw provider payload
- Admin registration does not break.
- Existing Task 1 trailer tests still pass.
- Existing Task 2 reservation tests still pass.
- Existing Task 3 payment/webhook tests still pass.
- Existing Task 4 analytics tests still pass.
- Existing Task 5 filtering tests still pass.

Suggested test tools:

- Use `override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")`.
- Use `django.core import mail` to inspect sent test emails.
- Patch email sending to simulate SMTP failures.
- Use existing payment finalization tests as the entry point for enqueue checks.
- Do not call real SMTP or external email services in automated tests.
- Do not call real Razorpay APIs in email tests.

Manual tests:

1. Configure console email backend locally.
2. Complete a booking through the existing reservation and Razorpay test flow.
3. Confirm a `BookingEmailNotification` row is created.
4. Run:

```bash
python manage.py process_email_queue
```

5. Confirm the email content appears in the terminal.
6. Confirm notification status becomes `SENT`.
7. Simulate a bad SMTP configuration.
8. Run the queue processor again.
9. Confirm status becomes `FAILED`.
10. Confirm `attempt_count`, `next_retry_at`, and `last_error` are set.
11. Check Django admin for pending/failed/sent notification visibility.

## 14. Acceptance Criteria

Task 6 is complete when:

- Successful booking creates an email notification queue row.
- Email queue row is created only after verified payment and successful booking finalization.
- Email contains booking details, show timing, seat numbers, payment ID, and theater information.
- Email uses Django templates.
- Booking/payment response is not blocked by SMTP delivery.
- Background command processes the email queue.
- Background command supports one-time and loop modes.
- Retry logic exists and does not retry forever.
- Failed email deliveries are logged.
- Failed/pending/sent email notifications are visible in Django admin.
- SMTP/email settings come from environment variables.
- Local development works with console email backend.
- Sensitive secrets are not exposed in emails or logs.
- Duplicate payment verification does not duplicate emails.
- Duplicate webhook processing does not duplicate emails.
- Existing Tasks 1-5 still work.
- `python manage.py check` passes.
- `python manage.py test` passes.

## 15. Final Summary

The planned implementation will add a database-backed email queue for ticket confirmations. After Razorpay payment is verified and `finalize_paid_reservation()` successfully creates the final `Booking` rows, the app will create one queue row for the whole reservation/payment. A separate management command will render Django email templates and send the email in the background. Failed sends will be retried with limited backoff and monitored through Django admin.

This plan intentionally does not implement code yet. No models, views, settings, templates, or tests have been changed by this planning step.

Next instruction needed from the user:

```text
Please implement Task 6 using this plan.
```
