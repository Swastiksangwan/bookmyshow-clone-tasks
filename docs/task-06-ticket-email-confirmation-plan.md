# Task 6: Automated Ticket Email Confirmation with Template Engine

## 1. Original Task Requirement

After a successful booking, the system needed to send a ticket confirmation email with booking details, show timing, seat numbers, payment ID, and theater information. Email delivery had to use templates, retries, logging, monitoring, secure SMTP configuration, and a background queue so booking/payment responses were not blocked.

## 2. Implemented Solution

The project uses a database-backed email queue through `BookingEmailNotification`. After `finalize_paid_reservation()` successfully creates bookings and captures a payment, it schedules an email notification row on transaction commit. It does not send SMTP inside the payment request.

The background command `process_email_queue` renders Django templates and sends pending notifications through the configured Django email backend.

## 3. Architecture and Processing Flow

```text
Payment verified
-> finalize_paid_reservation()
-> Booking rows created
-> PaymentTransaction.CAPTURED
-> transaction.on_commit()
-> enqueue_booking_confirmation_email()
-> BookingEmailNotification.PENDING
-> process_email_queue command
-> render subject/text/html templates
-> send through Django email backend
-> SENT or FAILED with retry metadata
```

## 4. Data Model or Schema Changes

`BookingEmailNotification` includes:

- `user`
- optional `booking`
- optional `payment_transaction`
- `reservation_token`
- `recipient_email`
- `subject`
- `status`: `PENDING`, `SENDING`, `SENT`, `FAILED`, `CANCELLED`
- `attempt_count`
- `max_attempts`
- `next_retry_at`
- `last_error`
- `provider_message_id`
- `created_at`
- `updated_at`
- `sent_at`
- `payload`

Indexes:

- `status + next_retry_at`
- `reservation_token`
- `created_at`
- `sent_at`

Constraint:

- one notification per non-null `payment_transaction`.

## 5. Security / Concurrency / Performance Decisions

- Email sending is not performed during the payment request-response cycle.
- Queue rows are created only for `PaymentTransaction.STATUS_CAPTURED`.
- Duplicate payment verification or duplicate webhook processing reuses the existing notification.
- SMTP credentials are read from environment variables.
- Local default email backend is Django console email backend.
- Templates do not include secrets, raw payment provider payloads, passwords, session data, or SMTP values.
- Subjects are normalized to remove newlines and reduce header injection risk.
- Email failures do not undo bookings or payments.
- Logging records success/failure without logging secrets.

## 6. Important Files

| File | Purpose |
| --- | --- |
| `movies/models.py` | Defines `BookingEmailNotification`. |
| `movies/email_notifications.py` | Builds payloads, enqueues notifications, renders templates, and sends email. |
| `movies/views.py` | Calls email enqueue logic after successful booking finalization. |
| `movies/management/commands/process_email_queue.py` | Background queue processor with loop and retry support. |
| `templates/emails/booking_confirmation_subject.txt` | Email subject template. |
| `templates/emails/booking_confirmation.txt` | Plain text ticket email. |
| `templates/emails/booking_confirmation.html` | HTML ticket email. |
| `movies/admin.py` | Admin monitoring for queued, sent, and failed notifications. |
| `bookmyseat/settings.py` | Email backend and SMTP env configuration. |
| `.env.example` | Placeholder email variables only. |
| `start.sh` | Starts the email queue loop alongside Gunicorn on Render. |
| `movies/tests.py` | Tests queue creation, rendering, retry behavior, and secret exclusion. |

## 7. Edge Cases Handled

- Payment not captured: no email queued.
- Missing final booking rows: no email queued.
- Duplicate payment verification: no duplicate email.
- Duplicate webhook finalization: no duplicate email.
- Missing user email: notification is marked `FAILED` with a clear error.
- Email backend exception: attempt count increments and retry time is set.
- Max attempts reached: notification stays failed and is not retried automatically.
- Payment succeeds but email fails: booking remains confirmed.

## 8. Automated Tests

Tests cover:

- Notification model creation.
- Successful payment finalization enqueuing one notification.
- Duplicate finalization not creating duplicates.
- Webhook path enqueuing once.
- Subject, text, and HTML template rendering.
- Locmem email backend sending.
- Successful send marking notification `SENT`.
- Failed send incrementing attempts and setting retry time.
- Max-attempt behavior.
- Missing user email handling.
- Secret and raw payload exclusion.
- Admin registration.

## 9. Manual Verification

1. Set local email backend:

   ```bash
   export EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
   export DEFAULT_FROM_EMAIL="BookMySeat <noreply@localhost>"
   ```

2. Complete a Razorpay Test Mode booking with a user that has an email address.
3. Confirm a `BookingEmailNotification` row appears in Django admin.
4. Run:

   ```bash
   python manage.py process_email_queue
   ```

5. Confirm the email prints to the console and the notification becomes `SENT`.
6. Simulate a bad SMTP setup and confirm `FAILED`, `attempt_count`, `next_retry_at`, and `last_error` update.

## 10. Trade-offs and Production Notes

The database-backed queue is simple and beginner-friendly. It satisfies background processing, retry tracking, and admin monitoring without requiring Redis/Celery. For higher production volume, Celery plus Redis or a managed task queue would be a good upgrade.

Production SMTP or transactional email credentials must remain in environment variables and must not be committed.

## 11. Completion Status

Task 6 is implemented and tested. Email notification processing is non-blocking and monitored through Django admin.
