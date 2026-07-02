# Task 03: Payment Gateway Integration with Idempotency and Webhook Security

## 1. Task Overview

Task 3 adds real payment handling after Task 2's temporary seat reservation flow.

Task 2 already protects seats for a short time before final booking. That is the correct foundation for payment because a user may spend time completing checkout. Without a reservation window, two users could try to pay for the same seat at nearly the same time.

Payment integration is needed because the current confirmation button acts like a fake payment success. In the final design, the booking should be confirmed only after the backend verifies that payment succeeded.

Payment must be verified server-side because browser data can be changed, replayed, or faked. A frontend callback saying "payment successful" is useful for user experience, but it is not proof of payment. The backend must verify the Razorpay payment signature and match the payment to the stored reservation/order before creating bookings.

Idempotency means "processing the same thing more than once should have the same result as processing it once." In this project, if the browser submits the same verification request twice or Razorpay sends the same webhook twice, the system must not create duplicate bookings or duplicate payment records.

Webhook security means the app must verify that incoming webhook requests really came from Razorpay. Razorpay sends a signature header. The backend must validate that signature using the server-only webhook secret before trusting or processing the event.

## 2. Current Project Analysis

Files inspected:

- `movies/models.py`
- `movies/views.py`
- `movies/urls.py`
- `templates/movies/reservation_confirm.html`
- `templates/movies/seat_selection.html`
- `movies/management/commands/release_expired_reservations.py`
- `movies/admin.py`
- `movies/tests.py`
- `bookmyseat/settings.py`
- `docs/task-02-seat-reservation-timeout-plan.md`
- `requirements.txt`

### Current models in `movies/models.py`

`Movie` stores movie information:

- `name`
- `image`
- `rating`
- `cast`
- `description`
- `trailer_url`

`Theater` stores show information:

- `name`
- `movie`
- `time`

`Seat` stores a seat for one theater:

- `theater`
- `seat_number`
- `is_booked`

`SeatReservation` was added by Task 2 and stores temporary holds:

- `user`
- `seat`
- `theater`
- `movie`
- `status`
- `created_at`
- `expires_at`
- `confirmed_at`
- `reservation_token`

Current reservation statuses:

- `RESERVED`
- `CONFIRMED`
- `EXPIRED`
- `CANCELLED`

`Booking` stores final confirmed bookings:

- `user`
- `seat`
- `movie`
- `theater`
- `booked_at`

Important: `Booking.seat` is a `OneToOneField`. This protects final booking creation because one seat can only have one final booking row.

### Current views in `movies/views.py`

Important Task 2 helpers and views:

- `_expire_reservations(...)`
- `_get_active_reserved_seat_ids(...)`
- `_seat_selection_context(...)`
- `_parse_selected_seat_ids(...)`
- `_get_user_reservations_or_404(...)`
- `_reservation_context(...)`
- `book_seats(...)`
- `reserve_seats(...)`
- `confirm_reservation(...)`

`reserve_seats(...)` currently:

1. Reads selected seat IDs.
2. Creates a shared `reservation_token`.
3. Starts `transaction.atomic()`.
4. Expires stale reservations.
5. Locks selected `Seat` rows with `select_for_update()`.
6. Checks for already booked seats.
7. Checks for active reservations.
8. Creates `SeatReservation` rows for 2 minutes.
9. Redirects to `reservation_confirm`.

`confirm_reservation(...)` currently:

1. Loads reservations for the logged-in user and token.
2. On GET, shows the confirmation page if still active.
3. On POST, locks reservations and seats.
4. Rejects expired or inactive reservations.
5. Creates `Booking` rows.
6. Marks seats as booked.
7. Marks reservations as confirmed.
8. Redirects to profile.

### Current URLs in `movies/urls.py`

Current relevant routes:

- `theater/<int:theater_id>/seats/book/`
- `theater/<int:theater_id>/seats/reserve/`
- `reservations/<uuid:reservation_token>/confirm/`

There are no payment-specific URLs yet.

### Current `reservation_confirm.html`

The page currently shows:

- movie name
- theater and show time
- selected seats
- reservation expiry time
- error messages
- a `Confirm Booking` submit button
- a link back to seat selection

This page currently acts like a payment placeholder. Pressing `Confirm Booking` creates the booking directly.

### Current `seat_selection.html`

The seat selection page:

- shows available, reserved, selected, and sold seats
- submits selected seat IDs to `reserve_seats`
- blocks seats with `seat.is_booked=True`
- blocks seats in `active_reserved_seat_ids`

This is the correct entry point before payment.

### Current cleanup command

`movies/management/commands/release_expired_reservations.py` marks expired `SeatReservation` rows as `EXPIRED`.

It supports:

- one-time cleanup
- loop mode with `--loop`
- configurable interval with `--interval`

### Current Task 2 flow

1. User selects seats.
2. App reserves selected seats for 2 minutes.
3. User sees a confirmation page.
4. User manually confirms booking.
5. Booking is created.
6. Seat is marked booked.
7. Reservation is marked confirmed.

### Current payment weaknesses

- No actual payment gateway exists.
- The confirmation button acts like payment success.
- No `PaymentTransaction` record exists.
- No Razorpay order ID is stored.
- No Razorpay payment ID is stored.
- No payment status lifecycle exists.
- No server-side Razorpay checkout signature verification exists.
- No Razorpay webhook endpoint exists.
- No webhook signature verification exists.
- No payment idempotency key exists.
- Duplicate payment verification requests are not explicitly tracked.
- Duplicate webhook events cannot be detected.
- Partial failures such as "payment captured but booking creation failed" are not recorded.

## 3. Payment Gateway Choice

Use Razorpay for this project.

Razorpay is a good fit because this is an India-oriented movie ticket booking app. Razorpay supports Indian payment methods and is commonly used for Indian checkout flows.

The app should use Razorpay Orders API server-side. The backend should create a Razorpay order for the active reservation. The frontend should receive only safe public checkout values, such as:

- Razorpay `key_id`
- Razorpay `order_id`
- amount
- currency
- movie/show display text

Secrets must remain server-side only:

- `RAZORPAY_KEY_SECRET`
- `RAZORPAY_WEBHOOK_SECRET`

Planned environment variables:

```text
RAZORPAY_KEY_ID=...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
```

Use Razorpay test mode first. Switch to live mode only after local tests, webhook tests, and duplicate-processing tests are passing.

## 4. Proposed Payment Data Model

Task 3 should add payment-specific models. These models should be added later in `movies/models.py` with a migration.

### A. `PaymentTransaction`

Suggested fields:

- `user`
  - `ForeignKey(User, on_delete=models.CASCADE)`
- `reservation_token`
  - UUID value copied from the Task 2 reservation group
- `razorpay_order_id`
  - unique provider order ID returned by Razorpay Orders API
- `razorpay_payment_id`
  - nullable unique provider payment ID after payment attempt
- `amount`
  - amount in paise, or a decimal amount with a clear convention
- `currency`
  - probably `INR`
- `status`
  - `CREATED`
  - `AUTHORIZED`
  - `CAPTURED`
  - `FAILED`
  - `CANCELLED`
  - `EXPIRED`
  - optionally `BOOKING_PENDING` or `REQUIRES_REVIEW` for partial failures
- `idempotency_key`
  - unique key based on reservation token and Razorpay order
- `created_at`
- `updated_at`
- `verified_at`
- `raw_provider_payload`
  - `JSONField` for provider response/audit data where useful

Why this model is needed:

- stores the payment state independently from booking state
- connects Razorpay order/payment IDs to the reservation token
- prevents duplicate processing
- makes retries safe
- gives an audit trail
- helps recover partial failures
- supports manual review/refund simulation when payment succeeds after reservation expiry

### B. `PaymentWebhookEvent`

Suggested fields:

- `provider`
  - example: `razorpay`
- `event_id`
  - unique provider event ID or deterministic event key
- `event_type`
  - example: `payment.captured`, `payment.failed`
- `received_at`
- `processed_at`
- `processing_status`
  - `RECEIVED`
  - `PROCESSED`
  - `IGNORED_DUPLICATE`
  - `FAILED`
  - `INVALID_SIGNATURE`
- `raw_payload`
  - `JSONField`
- `signature_valid`
  - boolean

Why this model is needed:

- stores every webhook received
- blocks duplicate webhook processing
- records invalid signatures
- provides a debugging/audit trail
- supports retry/reconciliation when processing fails

## 5. Payment Lifecycle

Planned lifecycle:

### A. User reserves seats

The existing Task 2 flow reserves selected seats for 2 minutes using `SeatReservation`.

### B. Confirmation page creates or uses Razorpay order

For an active `reservation_token`, the backend creates a Razorpay order. It also creates or reuses a `PaymentTransaction`.

If the user refreshes the confirmation page, the app should reuse an existing active transaction/order for the same reservation instead of creating many orders unnecessarily.

### C. Razorpay Checkout opens on frontend

The frontend uses Razorpay Checkout JS with safe public values:

- key ID
- order ID
- amount
- currency
- user-facing movie/show information

The key secret is never sent to the browser.

### D. User completes payment, fails, cancels, or times out

The user may:

- successfully pay
- fail payment
- close/cancel checkout
- let the reservation timer expire

### E. Frontend sends payment result to backend verify endpoint

On successful Razorpay Checkout callback, the browser sends:

- `razorpay_order_id`
- `razorpay_payment_id`
- `razorpay_signature`

to the backend verify endpoint.

### F. Backend verifies Razorpay signature server-side

The backend uses `RAZORPAY_KEY_SECRET` to verify the checkout signature.

The backend must not trust frontend success alone.

### G. Backend checks reservation is still active

Before booking, the backend must confirm:

- reservation token exists
- reservation belongs to the logged-in user
- all reservations are still `RESERVED`
- none have expired
- selected seats are not already booked
- payment transaction matches the reservation token and Razorpay order ID

### H. Backend finalizes booking in a database transaction

Inside `transaction.atomic()`:

1. Lock reservation rows with `select_for_update()`.
2. Lock seat rows with `select_for_update()`.
3. Lock payment transaction row.
4. Re-check reservation expiry/status.
5. Re-check no booking exists.
6. Create `Booking` rows.
7. Mark seats `is_booked=True`.
8. Mark reservations `CONFIRMED`.
9. Mark payment transaction `CAPTURED` or success-equivalent.

### I. Webhook also confirms or updates payment status

Razorpay webhook events may arrive before or after the frontend verify request.

The webhook should update the payment transaction safely and idempotently. If the booking is already finalized, the webhook should not create it again.

### J. Duplicate callbacks/webhooks do not create duplicate bookings

Duplicate frontend verify requests and duplicate webhook events should return the existing final result or be ignored safely.

## 6. Secure Server-Side Verification Plan

Frontend success is not enough. The backend must verify payment data.

For Razorpay Checkout verification, the backend should verify:

- `razorpay_order_id`
- `razorpay_payment_id`
- `razorpay_signature`

The signature should be verified using the server-only `RAZORPAY_KEY_SECRET`.

The backend should also check:

- the `razorpay_order_id` exists in `PaymentTransaction`
- the transaction belongs to the same `reservation_token`
- the reservation belongs to the current user
- the amount and currency match the expected booking amount
- the payment has not already been processed

Only after all checks pass should booking finalization run.

## 7. Webhook Security Plan

Add a Razorpay webhook endpoint later, for example:

```text
POST /movies/payments/razorpay/webhook/
```

The webhook endpoint should:

1. Receive Razorpay events.
2. Read the raw request body.
3. Verify `X-Razorpay-Signature` using `RAZORPAY_WEBHOOK_SECRET`.
4. Reject invalid signatures.
5. Parse JSON only after signature validation.
6. Store the event in `PaymentWebhookEvent`.
7. Check whether the event was already processed.
8. Process only supported events.
9. Mark duplicate events as ignored.

Important security detail: Razorpay webhook signature verification must use the raw request body. Do not parse or modify the request body before signature verification.

The webhook view will need `@csrf_exempt` because Razorpay cannot send Django's CSRF token. This exemption should be used only for the webhook endpoint. The compensation is strict webhook signature verification.

Duplicate webhook protection:

- store provider event ID if available
- enforce uniqueness on `(provider, event_id)` where possible
- if event ID is missing, use a deterministic fallback key based on payment ID, event type, and provider timestamp if safe
- do not process the same event twice

## 8. Idempotency Plan

In this project, idempotency means duplicate payment requests must not create duplicate bookings or inconsistent payment state.

Duplicate situations to handle:

- same payment verification request submitted twice
- user refreshes checkout success page
- browser retry submits the same payload again
- Razorpay sends the same webhook more than once
- webhook arrives before frontend verification
- frontend verification arrives before webhook

Planned protections:

- `razorpay_order_id` should be unique.
- `razorpay_payment_id` should be unique when available.
- `idempotency_key` should be unique.
- `PaymentWebhookEvent(provider, event_id)` should be unique.
- Before creating bookings, check whether the payment already finalized booking.
- Before creating bookings, check whether any `Booking` already exists for the seats.
- Final booking creation must happen inside `transaction.atomic()`.
- Lock payment, reservation, and seat rows with `select_for_update()`.
- Keep the existing `Booking.seat` `OneToOneField`; it protects final duplicate seat booking.

Suggested idempotency key:

```text
reservation:{reservation_token}:razorpay_order:{razorpay_order_id}
```

If a duplicate verify request arrives after booking is already created, return a safe "already confirmed" response instead of failing unpredictably.

## 9. Success, Failure, Cancellation, Timeout

### Success

Expected handling:

1. Razorpay checkout returns payment details.
2. Backend verifies signature.
3. Payment transaction is marked captured/success.
4. Reservation is confirmed.
5. Booking rows are created.
6. Seats are marked booked.
7. User sees success/profile page.

### Failure

Expected handling:

1. Payment transaction is marked failed.
2. Reservation may remain active until expiry.
3. User may retry payment within the 2-minute window if the design allows.
4. If the reservation expires, user must select seats again.

### Cancellation

Expected handling:

1. User closes/cancels Razorpay Checkout.
2. Frontend may notify backend if practical.
3. Transaction can be marked cancelled if backend is notified.
4. Reservation expires normally unless explicitly cancelled.

### Timeout

Expected handling:

1. Reservation expires after 2 minutes.
2. `release_expired_reservations` marks it `EXPIRED`.
3. Payment verification after expiry must not create booking.
4. If payment succeeds after expiry, mark transaction as `REQUIRES_REVIEW` or equivalent.
5. In a real system, this would trigger refund/reconciliation. In this learning project, it can be documented/admin-reviewed.

### Partial failure

Possible case: Razorpay payment captured but booking creation fails.

Expected handling:

- Do not silently lose the paid transaction.
- Mark payment as paid but `BOOKING_PENDING` or `REQUIRES_REVIEW`.
- Store raw provider payload.
- Keep enough audit data for admin/debug reconciliation.
- Do not create duplicate bookings on retry.
- A later retry/reconciliation path should either safely create the booking or mark it for refund/manual review.

## 10. Fraud Prevention and Replay Attack Mitigation

Fraud and replay protections:

- `RAZORPAY_KEY_SECRET` is never exposed to the browser.
- `RAZORPAY_WEBHOOK_SECRET` is never exposed to the browser.
- Frontend checkout success is not trusted without backend signature verification.
- Razorpay checkout signature verification blocks fake frontend success payloads.
- Razorpay webhook signature verification blocks fake webhooks.
- Raw request body validation prevents signature mismatch and tampering.
- Webhook event IDs/payment IDs are stored to block duplicate replay.
- Unique constraints prevent duplicate payment rows.
- Idempotent database processing prevents duplicate booking.
- Reservation expiry prevents stale payment confirmation from booking old seats.
- `transaction.atomic()` keeps payment/booking state consistent.
- PostgreSQL row locking prevents simultaneous finalization race conditions.

Replay example:

If an attacker resends an old valid-looking webhook, the system should see that the event/payment was already processed and skip it.

## 11. Planned URL/View Design

Suggested future endpoints:

```text
POST /movies/reservations/<uuid:reservation_token>/payment/create/
POST /movies/reservations/<uuid:reservation_token>/payment/verify/
POST /movies/payments/razorpay/webhook/
GET  /movies/reservations/<uuid:reservation_token>/payment/status/
```

Suggested Django URL names:

- `payment_create`
- `payment_verify`
- `razorpay_webhook`
- `payment_status`

Planned view responsibilities:

### `create_payment_order`

- require login
- load active reservation
- calculate amount
- create or reuse `PaymentTransaction`
- call Razorpay Orders API server-side
- return checkout data

### `verify_payment`

- require login
- verify checkout signature
- match payment to transaction/reservation
- finalize booking idempotently
- return success/failure page or JSON response

### `razorpay_webhook`

- no login required
- CSRF exempt
- verify raw body signature
- store event
- process safely once

### `payment_status`

- optional
- show clear state to the user:
  - pending
  - success
  - failed
  - expired
  - requires review

## 12. Frontend/Template Plan

Planned changes for `templates/movies/reservation_confirm.html`:

- Replace `Confirm Booking` with `Pay Now`.
- Show reservation timer/expiry clearly.
- Include Razorpay Checkout JS.
- Use backend-created order ID.
- Pass only safe public values:
  - `RAZORPAY_KEY_ID`
  - Razorpay order ID
  - amount
  - currency
  - movie/show description
- On success, submit payment result to backend verify endpoint.
- On failure, show clear error.
- On cancellation/close, show clear message and allow retry if reservation is still active.

The frontend should never receive:

- `RAZORPAY_KEY_SECRET`
- `RAZORPAY_WEBHOOK_SECRET`

The frontend should not create bookings directly. It only starts checkout and sends the payment result to the backend.

## 13. Files Expected To Change Later

| File path | Planned change | Reason |
| --- | --- | --- |
| `movies/models.py` | Add `PaymentTransaction` and `PaymentWebhookEvent` models | Store payment lifecycle and webhook audit data |
| `movies/views.py` | Add create order, verify payment, webhook, and status views; change confirmation flow | Move booking finalization behind verified payment |
| `movies/urls.py` | Add payment and webhook routes | Expose backend endpoints |
| `movies/admin.py` | Register payment models | Inspect transactions and webhook events during development |
| `templates/movies/reservation_confirm.html` | Replace direct confirmation with Razorpay Checkout flow | User should pay before booking confirmation |
| `templates/movies/payment_status.html` | Possible new status/failure page | Show success, failure, expired, or review-needed states |
| `templates/movies/seat_selection.html` | Possibly update messaging around reserved seats/payment window | Clarify reservation/payment flow |
| `movies/tests.py` | Add payment lifecycle, idempotency, and webhook security tests | Verify safety behavior |
| `bookmyseat/settings.py` | Read Razorpay environment variables | Keep secrets server-side |
| `.env.example` | Document required local env vars if created | Help local setup without committing secrets |
| `requirements.txt` | Add Razorpay SDK if used | Call Razorpay Orders API/signature helpers |
| `movies/migrations/0004_*.py` | Add payment tables and constraints | Persist payment state |
| `docs/task-03-payment-idempotency-webhooks-plan.md` | Keep implementation plan updated | Track design decisions |

## 14. Testing Plan

### Manual tests

1. Create a reservation.
2. Create a Razorpay order for the reservation.
3. Complete successful test payment.
4. Verify payment server-side.
5. Confirm booking is created once.
6. Confirm seats are marked booked.
7. Simulate failed payment.
8. Simulate cancelled checkout.
9. Submit duplicate frontend verify request.
10. Send duplicate webhook event.
11. Send webhook with invalid signature.
12. Try payment verification after reservation expiry.
13. Try payment success when booking already exists.
14. Simulate payment captured but booking creation failure if practical.

### Automated tests

Recommended tests in `movies/tests.py`:

- `PaymentTransaction` creation for active reservation.
- Razorpay order creation is not allowed for expired reservation.
- Successful verified payment creates booking once.
- Duplicate verified payment does not duplicate booking.
- Invalid checkout signature is rejected.
- Expired reservation payment is rejected.
- Duplicate webhook event is ignored safely.
- Invalid webhook signature is rejected.
- Payment after reservation expiry does not create booking.
- Payment captured but booking creation failure is recorded as review/pending.
- `Booking.seat` uniqueness still protects duplicate final booking.

Mock Razorpay SDK/API calls in tests. Do not call real Razorpay during automated tests.

## 15. Local Development Notes

Use Razorpay test keys locally.

Required environment variables:

```text
RAZORPAY_KEY_ID=...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
```

Do not commit real keys.

Webhook testing requires Razorpay to reach the local development server. Local testing may need a public tunnel such as ngrok.

For unit tests:

- mock Razorpay API calls
- mock signature verification where appropriate
- use small deterministic payloads
- avoid real external payment calls

For deployment, use PostgreSQL.

Why PostgreSQL matters:

- Task 2 uses `select_for_update()` for seat locking.
- Task 3 should lock payment/reservation/seat rows during finalization.
- SQLite is fine for beginner local development but does not provide the same row-level locking behavior.
- PostgreSQL gives stronger consistency for simultaneous real users.

## 16. Acceptance Criteria

Task 3 implementation is complete when:

- Payment order can be created for an active reservation.
- Payment order cannot be created for an expired/inactive reservation.
- Payment verification is server-side.
- Razorpay checkout signature is verified.
- Razorpay webhook signature is verified.
- Duplicate payment verification does not duplicate bookings.
- Duplicate webhook does not duplicate processing.
- Success, failure, cancellation, and timeout are handled.
- Payment after reservation expiry does not create booking.
- Partial failures are recorded safely.
- Secrets are not exposed to browser or committed.
- Tests/checks pass.
- Complete payment lifecycle is documented.

## 17. Final Summary

Task 3 should turn the current fake confirmation step into a real payment-backed booking flow.

The planned design is:

1. Keep Task 2 `SeatReservation` as the temporary seat hold.
2. Create a Razorpay order for the active reservation.
3. Store payment state in `PaymentTransaction`.
4. Verify Razorpay checkout signatures server-side.
5. Finalize booking only inside a database transaction.
6. Verify Razorpay webhook signatures using the raw request body.
7. Store webhook events in `PaymentWebhookEvent`.
8. Use idempotency keys and uniqueness constraints to avoid duplicate processing.
9. Use PostgreSQL for production-grade consistency and row-level locking.

Implementation has not been done yet. This document is the plan only.

Next instruction needed:

```text
Please implement Task 3 using this plan.
```

## Production Timeout Note

The demo reservation window is 2 minutes because Task 2 required a short temporary seat lock. This is useful for testing timeout behavior.

In a production ticket booking system, the reservation/payment window should usually be increased to around 5–10 minutes so users have enough time to complete checkout. The safety rule should remain the same: if payment completes after the reservation expires, the backend must not create a booking automatically. Instead, the payment should be marked `REQUIRES_REVIEW` for refund/reconciliation handling.

This project already follows that safety rule: expired reservations do not create bookings, and late successful payments are recorded for review instead of risking double booking.
