# Task 3: Payment Gateway Integration with Idempotency and Webhook Security

## 1. Original Task Requirement

The fake direct booking confirmation needed to be replaced with a Razorpay Test Mode payment flow. The backend had to verify checkout signatures server-side, verify webhook signatures with the raw request body, and finalize bookings idempotently so duplicate callbacks or webhooks could not create duplicate bookings.

## 2. Implemented Solution

The reservation confirmation page creates or reuses a Razorpay order through `PaymentTransaction`. Browser checkout success posts Razorpay IDs/signature to the backend. The backend verifies the HMAC signature before finalizing bookings.

Webhooks are accepted only after validating `X-Razorpay-Signature` against the raw request body. Valid webhook events are stored in `PaymentWebhookEvent` and duplicate events are ignored safely.

Booking creation is centralized in `finalize_paid_reservation()`.

## 3. Architecture and Processing Flow

```text
Active SeatReservation
-> reservation_confirm GET
-> create/reuse Razorpay order and PaymentTransaction
-> Razorpay Checkout in browser
-> payment_verify POST
-> server-side checkout HMAC verification
-> finalize_paid_reservation()
-> Booking rows + Seat.is_booked + SeatReservation.CONFIRMED
```

Webhook flow:

```text
Razorpay webhook
-> raw request body
-> HMAC signature verification
-> PaymentWebhookEvent get_or_create()
-> transaction lookup by order/payment ID
-> idempotent finalization or safe status update
```

## 4. Data Model or Schema Changes

`PaymentTransaction` includes:

- `user`
- `reservation_token`
- `razorpay_order_id` unique
- `razorpay_payment_id` unique when present
- `amount` in paise
- `currency`
- `status`
- `idempotency_key` unique
- `verified_at`
- `raw_provider_payload`

Statuses include `CREATED`, `AUTHORIZED`, `CAPTURED`, `FAILED`, `CANCELLED`, `EXPIRED`, `BOOKING_PENDING`, and `REQUIRES_REVIEW`.

`PaymentWebhookEvent` includes:

- `provider`
- `event_id`
- `event_type`
- `raw_payload`
- `signature_valid`
- `processing_status`
- `received_at`
- `processed_at`

It has a unique constraint on `provider + event_id`.

## 5. Security / Concurrency / Performance Decisions

- Frontend payment success is never trusted by itself.
- Checkout signatures use HMAC-SHA256 over `razorpay_order_id|razorpay_payment_id`.
- Webhook signatures use HMAC-SHA256 over `request.body`.
- Webhook JSON is parsed only after signature verification.
- Razorpay secret and webhook secret remain server-side environment variables.
- `verify_payment` only accepts POST.
- The webhook endpoint is the only CSRF-exempt payment endpoint because Razorpay cannot send CSRF tokens.
- Booking finalization uses `transaction.atomic()`.
- `PaymentTransaction`, `SeatReservation`, and `Seat` rows are locked with `select_for_update()` where supported.
- `Booking.seat` remains a final duplicate-booking protection.
- Duplicate frontend verification redirects safely when booking already exists.
- Duplicate webhooks are ignored by `PaymentWebhookEvent(provider, event_id)`.
- Captured payments after reservation expiry become `REQUIRES_REVIEW`; no booking is created.

## 6. Important Files

| File | Purpose |
| --- | --- |
| `movies/models.py` | Defines payment and webhook models. |
| `movies/views.py` | Creates/reuses orders, verifies signatures, processes webhooks, and finalizes bookings. |
| `movies/urls.py` | Adds payment verification, cancel, status, and webhook routes. |
| `templates/movies/reservation_confirm.html` | Razorpay Checkout UI and payment result form. |
| `templates/movies/payment_status.html` | Displays safe payment state messages. |
| `movies/admin.py` | Shows payment and webhook records in admin. |
| `movies/tests.py` | Tests signature verification, payment idempotency, and webhooks. |
| `bookmyseat/settings.py` | Reads Razorpay env vars and ticket price. |
| `.env.example` | Contains placeholder Razorpay variables only. |

## 7. Edge Cases Handled

- Missing Razorpay keys: payment page shows a configuration error.
- Invalid checkout signature: transaction marked `FAILED`.
- Duplicate frontend verify: booking is not duplicated.
- Duplicate webhook: event is ignored safely.
- Payment failed webhook: transaction marked `FAILED` if not finalized.
- Captured webhook for an already finalized booking: no duplicate booking.
- Reservation expired before payment verification: payment moves to review state.
- Existing booking rows or booked seats: finalization returns safely or marks review.
- Integrity errors during booking finalization: transaction moves to review state.

## 8. Automated Tests

Tests cover:

- Payment model creation.
- Webhook event model creation.
- Razorpay order creation and reuse.
- No order creation for expired reservation.
- Missing configuration error.
- Checkout HMAC verification.
- Webhook HMAC verification.
- Successful payment creating one booking.
- Duplicate verification not duplicating booking.
- Invalid signature failure.
- Payment after expiry.
- Invalid webhook signature.
- Valid webhook storage.
- Duplicate webhook idempotency.
- Captured webhook finalization.

Automated tests do not call real Razorpay APIs.

## 9. Manual Verification

1. Configure Razorpay test environment variables.
2. Reserve a seat.
3. Open the confirmation page.
4. Click Pay Now and complete Razorpay Test Mode checkout.
5. Confirm the profile shows one booking.
6. Re-submit the same verification payload only in a controlled test and confirm no duplicate booking is created.
7. Configure a local webhook tunnel and verify valid webhooks are stored while duplicates are ignored.

## 10. Trade-offs and Production Notes

The project stores raw provider payloads only in the server-side database for audit/debugging and never exposes them to templates or emails. PostgreSQL is recommended in production for transaction locking and stronger consistency under concurrent payments.

## 11. Completion Status

Task 3 is implemented and tested. Razorpay Test Mode is active when the required environment variables are configured.
