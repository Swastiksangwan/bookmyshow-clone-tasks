# Task 2: Concurrency-Safe Seat Reservation with Auto Timeout

## 1. Original Task Requirement

Seat selection needed a temporary reservation step before final booking. Seats selected by a user should be locked for 2 minutes, should not be double-booked by simultaneous users, and should become available again if payment is not completed.

## 2. Implemented Solution

The app uses a `SeatReservation` model to represent temporary holds. Selecting seats creates one or more `SeatReservation` rows grouped by a shared `reservation_token`. A seat is unavailable when it is permanently booked or has an active, non-expired reservation.

Final `Booking` rows are created only after payment verification in Task 3. `Seat.is_booked=True` means permanent booking, not temporary reservation.

## 3. Architecture and Processing Flow

```text
Seat page
-> POST selected seat IDs to reserve_seats
-> transaction.atomic()
-> expire stale reservations
-> select_for_update() selected seats
-> validate availability
-> create 2-minute SeatReservation rows
-> reservation confirmation/payment page
-> payment verification finalizes Booking rows
```

Expired reservation cleanup can also run through:

```bash
python manage.py release_expired_reservations
python manage.py release_expired_reservations --loop --interval 30
```

## 4. Data Model or Schema Changes

`SeatReservation` includes:

- `user`
- `seat`
- `theater`
- `movie`
- `status`: `RESERVED`, `CONFIRMED`, `EXPIRED`, `CANCELLED`
- `created_at`
- `expires_at`
- `confirmed_at`
- `reservation_token`

Helper methods:

- `has_expired()`
- `is_active()`

Indexes:

- `status + expires_at` for expiry and active-reservation checks.

## 5. Security / Concurrency / Performance Decisions

- Reservation creation uses `transaction.atomic()`.
- Selected seats are queried with `select_for_update()`.
- Existing active reservations are checked inside the transaction.
- Expired `RESERVED` rows are marked `EXPIRED`.
- Any invalid or unavailable selected seat fails the whole reservation request.
- The implementation does not silently reserve only part of the selected seats.
- `Booking.seat` remains a final database-level `OneToOneField` duplicate-booking guard.
- PostgreSQL provides true row-level locking for `select_for_update()`.
- SQLite is acceptable for local development but does not fully model PostgreSQL row-level locking.

## 6. Important Files

| File | Purpose |
| --- | --- |
| `movies/models.py` | Defines `Seat`, `SeatReservation`, and `Booking`. |
| `movies/views.py` | Implements seat availability, reservation creation, expiry checks, and confirmation page behavior. |
| `movies/urls.py` | Routes seat selection, reservation, and confirmation URLs. |
| `templates/movies/seat_selection.html` | Displays available, reserved, sold, and selected seat states. |
| `templates/movies/reservation_confirm.html` | Shows reservation expiry and payment continuation page. |
| `movies/management/commands/release_expired_reservations.py` | Marks expired reservations as `EXPIRED`. |
| `movies/tests.py` | Tests reservation, expiry, duplicate prevention, and command behavior. |
| `movies/migrations/0003_seatreservation.py` | Adds the reservation table. |

## 7. Edge Cases Handled

- No selected seats: safe error message.
- Non-integer seat IDs: rejected.
- Seat IDs outside the theater: rejected.
- Duplicate submitted seat IDs: deduplicated.
- Already booked seats: rejected.
- Active reservations by another user: rejected.
- Expired reservations: ignored and marked expired.
- Confirmation after expiry: rejected.
- User closes the browser: reservation expires automatically.
- Network interruption: reservation expires automatically.

## 8. Automated Tests

Tests cover:

- `SeatReservation.is_active()` and `has_expired()`.
- Reserving an available seat.
- No booking created during temporary reservation.
- Active reservation blocking another user.
- Expired reservation no longer blocking the seat.
- Direct confirmation not creating booking without payment.
- Confirmation after expiry.
- Already booked seats.
- Invalid and duplicate seat IDs.
- Expiry cleanup command.

## 9. Manual Verification

1. Login as a normal user.
2. Open a movie detail page and select a theater.
3. Select available seats.
4. Confirm the reservation page shows a timer.
5. In a second browser/session, try selecting the same seat before expiry.
6. Confirm the second request fails safely.
7. Wait more than 2 minutes or run the cleanup command.
8. Confirm the seat becomes available again if no payment was completed.

## 10. Trade-offs and Production Notes

The local SQLite setup can demonstrate the application logic, but production consistency is strongest with PostgreSQL because row-level locking is needed under real concurrent traffic. The app also ignores expired reservations during availability checks, so cleanup delays do not keep seats blocked.

## 11. Completion Status

Task 2 is implemented and tested. The seat reservation flow remains active and feeds into the Razorpay-backed confirmation flow.
