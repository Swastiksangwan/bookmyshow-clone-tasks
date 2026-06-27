# Task 02: Concurrency-Safe Seat Reservation with Auto Timeout

## 1. Task Overview

Seat reservation means temporarily holding selected seats for a user before the final booking/payment is completed. In this project, the user currently selects seats and submits the form, then the seats are immediately marked as booked. Task 2 will add a middle step: seats are locked for 2 minutes first.

Seat states should be understood like this:

- Available seat: the seat is not booked and has no active reservation. A user can select it.
- Temporarily reserved seat: the seat is not permanently booked yet, but another user has locked it for a short time. Other users should not be able to reserve or book it.
- Permanently booked seat: the booking is complete. The seat should stay unavailable.

This is needed before payment because payment can take time. Without reservation, two users could select the same seat and try to pay at nearly the same moment. With reservation, the first successful reservation temporarily holds the seat while payment is completed.

The planned reservation timeout is 2 minutes. If payment/confirmation does not finish in time, the reservation expires and the seat becomes available again.

## 2. Current Project Analysis

Inspected files:

- `movies/models.py`
- `movies/views.py`
- `movies/urls.py`
- `templates/movies/seat_selection.html`
- `movies/admin.py`
- `movies/tests.py`
- `bookmyseat/settings.py`

Current model behavior in `movies/models.py`:

- `Movie` stores movie information.
- `Theater` belongs to a movie and has a show time.
- `Seat` belongs to a theater and has:
  - `seat_number`
  - `is_booked`
- `Booking` stores the final booking with:
  - `user`
  - `seat`
  - `movie`
  - `theater`
  - `booked_at`
- `Booking.seat` is a `OneToOneField`, so one seat can only have one booking record.

Current view behavior in `movies/views.py`:

- `movie_list` shows movies.
- `movie_detail` shows one movie and trailer information.
- `theater_list` shows theaters for a selected movie.
- `book_seats` handles both:
  - showing seat checkboxes for one theater
  - immediately creating bookings when the form is submitted

Current URL behavior in `movies/urls.py`:

- `/movies/` shows the movie list.
- `/movies/<movie_id>/` shows movie detail.
- `/movies/<movie_id>/theaters` shows theaters for a movie.
- `/movies/theater/<theater_id>/seats/book/` shows and submits seat booking.

Current template behavior in `templates/movies/seat_selection.html`:

- Seats are displayed as checkbox-style buttons.
- If `seat.is_booked` is true, the seat is shown as sold.
- If `seat.is_booked` is false, the seat can be selected.
- The form submits selected seat IDs as `seats`.

Current admin behavior in `movies/admin.py`:

- `Movie`, `Theater`, `Seat`, and `Booking` are registered.
- `SeatAdmin` shows `theater`, `seat_number`, and `is_booked`.
- There is currently no reservation admin model.

Current booking flow:

1. User opens a theater seat page.
2. Page loads all `Seat` rows for that theater.
3. User selects one or more seats.
4. User submits the form.
5. `book_seats` loops over selected seat IDs.
6. For each seat:
   - it checks `seat.is_booked`
   - creates a `Booking`
   - sets `seat.is_booked=True`
   - saves the seat
7. User is redirected to the profile page.

Current weaknesses:

- There is no temporary reservation step.
- Seats are not locked while the user is deciding or paying.
- Two users can submit almost simultaneously for the same seat.
- The current Python-level `if seat.is_booked` check is not enough to prevent all race conditions.
- There is no expiry time for selected seats.
- If a user closes the page, there is no reservation state to clean up.
- There is no scheduler or management command for cleanup.
- Seat availability only checks `Seat.is_booked`, not temporary holds.

Database note:

`bookmyseat/settings.py` uses SQLite locally by default. This is good for beginner local development, but SQLite has limited concurrency behavior compared with PostgreSQL.

## 3. Proposed Data Model

Recommended beginner-friendly design: add a separate model called `SeatReservation`.

Possible fields:

- `user`: foreign key to the user who reserved the seat.
- `seat`: foreign key to the selected seat.
- `theater`: foreign key to the theater.
- `movie`: foreign key to the movie.
- `status`: reservation status.
- `created_at`: when the reservation was created.
- `expires_at`: when the 2-minute hold ends.
- `confirmed_at`: when payment/confirmation completed.
- `reservation_token`: optional random token or session key for tracking a reservation group.

Suggested statuses:

- `RESERVED`: temporarily locked and not expired.
- `CONFIRMED`: payment/confirmation succeeded and a booking was created.
- `EXPIRED`: the 2-minute hold expired.
- `CANCELLED`: user or system cancelled the hold.

Why a separate `SeatReservation` model is better than only using `Seat.is_booked`:

- `Seat.is_booked` is a permanent state.
- A reservation is temporary and needs an expiry time.
- Reservation history is useful for debugging and testing.
- A separate model can represent abandoned, expired, cancelled, and confirmed attempts.
- It avoids changing `Seat.is_booked` to true before payment is complete.
- It keeps final bookings and temporary holds separate.

How existing `Seat.is_booked` should be treated:

- `Seat.is_booked=True` means permanently booked.
- An active `SeatReservation` means temporarily unavailable.
- An expired `SeatReservation` means the seat should be available again.
- The system should treat a reservation as active only when:
  - `status='RESERVED'`
  - `expires_at` is in the future

Important design rule:

Expired reservations should not block seat availability, even if the scheduler has not updated them to `EXPIRED` yet.

## 4. Reservation Flow

Expected reservation flow:

### A. User selects seats

The user opens the seat selection page and selects one or more available seats.

### B. System starts transaction

The reserve view starts a database transaction using `transaction.atomic()`.

### C. System locks selected Seat rows

Inside the transaction, the system fetches selected seats using `select_for_update()` where the database supports it.

Example planned idea:

```python
with transaction.atomic():
    seats = Seat.objects.select_for_update().filter(
        id__in=selected_seat_ids,
        theater=theater,
    )
```

### D. System checks seat state

Inside the same transaction, the system checks:

- the seat belongs to the selected theater
- the seat is not permanently booked
- the seat does not already have an active, non-expired reservation
- the same seat ID was not submitted twice

### E. System creates reservation for 2 minutes

If checks pass, create `SeatReservation` rows with:

- `status='RESERVED'`
- `created_at=timezone.now()`
- `expires_at=timezone.now() + timedelta(minutes=2)`

### F. Seat appears temporarily unavailable

Other users should see the seat as unavailable if it has an active reservation.

### G. User proceeds to payment placeholder/confirmation

For this beginner project, payment can be represented by a confirmation page/button first. A real payment gateway can be added later.

### H. Payment succeeds within 2 minutes

If the user confirms before `expires_at`:

- reservation becomes `CONFIRMED`
- `Seat.is_booked` becomes `True`
- a `Booking` record is created
- user is redirected to profile or booking success page

### I. Payment is not completed

If payment/confirmation does not happen:

- reservation expires after 2 minutes
- scheduler marks it `EXPIRED`
- seat becomes available again

## 5. Concurrency and Race Condition Prevention

A race condition happens when two requests read or change the same data at nearly the same time and the result depends on timing.

Simple example:

1. User A checks seat A1 and sees it is available.
2. User B checks seat A1 at nearly the same moment and also sees it is available.
3. Both try to book the same seat.
4. Without locking, both may pass the availability check before either save finishes.

Required behavior:

- Only one transaction should reserve the seat.
- The other request should fail safely and show a message such as `Some selected seats are no longer available.`
- No double booking should be created.

Recommended Django approach:

- Use `transaction.atomic()`.
- Use `select_for_update()` on selected `Seat` rows where supported.
- Check permanent booking and active reservations inside the transaction.
- Create reservation rows inside the same transaction.
- Confirm reservation and create `Booking` inside another transaction.
- Use database constraints where practical.

Possible constraints:

- Keep the existing `Booking.seat` `OneToOneField`, which protects final bookings.
- Consider a uniqueness rule for active reservations. This is easier in PostgreSQL with conditional unique constraints, for example one active `RESERVED` reservation per seat.
- In SQLite, conditional/partial constraints are more limited and should be tested carefully.

Important SQLite limitation:

- SQLite does not fully support row-level locking like PostgreSQL.
- `select_for_update()` does not behave the same way in SQLite.
- SQLite may lock more broadly, often at database/table write level.
- Local implementation can still demonstrate transaction logic.
- For production-grade row-level locking and stronger concurrency behavior, PostgreSQL is recommended.

Production recommendation:

Use PostgreSQL for deployment if this feature must reliably handle real simultaneous traffic. PostgreSQL supports row-level locking with `select_for_update()` and stronger concurrent transaction behavior.

## 6. Consistency Model

Planned consistency model:

- Strong consistency for reservation and booking writes.
- Read-after-write consistency for the user's own reservation.
- Eventual cleanup for expired reservations through the scheduler.
- Database transaction is the source of truth.

Strong consistency for writes:

When reserving or confirming seats, the project should make all related writes inside a transaction. Either the whole operation succeeds, or it rolls back.

Read-after-write consistency:

After a user reserves seats, the next page should read the newly created reservation from the database and show the correct state.

Eventual cleanup:

Expired reservations may stay in the database until the scheduler runs. That is acceptable only if availability checks always treat expired reservations as inactive.

Important rule:

The query for seat availability should check time. A reservation with `expires_at <= timezone.now()` should not block the seat, even if its status is still `RESERVED`.

## 7. Auto Timeout / Scheduler Plan

Reservations should expire after 2 minutes.

Recommended beginner-friendly implementation:

Create a Django management command:

```bash
python manage.py release_expired_reservations
```

What the command should do:

- Find `SeatReservation` rows where:
  - `status='RESERVED'`
  - `expires_at <= timezone.now()`
- Update them to:
  - `status='EXPIRED'`

Optional local development loop mode:

```bash
python manage.py release_expired_reservations --loop --interval 30
```

This would run cleanup every 30 seconds while developing locally.

Why this is useful:

- It acts like a simple background scheduler without adding Celery immediately.
- It is easy for beginners to run in a second terminal.
- It keeps expired reservations clean in the database.

Production alternatives:

- Celery beat
- cron job
- Django-Q
- APScheduler
- platform scheduled jobs, such as Render cron jobs or Heroku Scheduler

Important reliability rule:

The app should ignore expired reservations during availability checks even if the cleanup command has not run yet. The scheduler improves cleanup, but availability logic must not depend only on the scheduler.

## 8. Edge Case Handling

User closes app:

- Reservation remains temporarily.
- After 2 minutes, it expires.
- Scheduler marks it `EXPIRED`.
- Seat becomes available.

Network interruption:

- If reservation was created, it expires after 2 minutes.
- If reservation was not created, no seat is held.
- Confirmation after expiry should be rejected.

User opens multiple devices:

- Active reservations should be linked to the user.
- The system should check if the same user already has an active reservation for the same seat.
- Beginner-friendly choice: block duplicate reservation attempts and show a message.
- Optional improvement: reuse the existing active reservation and show the remaining time.

Same user selects same seat twice:

- Deduplicate submitted seat IDs before querying.
- If an active reservation already exists for that user and seat, either reuse it or block it.
- The simpler first version should block duplicate attempts with a clear message.

Two users select same seat within milliseconds:

- Both requests enter the reserve view.
- The first transaction locks/checks/creates the reservation.
- The second transaction should see the seat is now reserved or wait until the first finishes, depending on the database.
- Only one reservation succeeds.

Expired reservation still in database:

- It should be treated as inactive.
- The seat should be available if it is not permanently booked.

Payment/confirmation after expiry:

- The confirm view should check `expires_at`.
- If expired, do not create `Booking`.
- Mark reservation `EXPIRED` if needed.
- Show a message asking the user to select seats again.

Already booked seats:

- Cannot be reserved.
- Cannot be confirmed through a reservation.
- Should remain shown as sold.

Invalid seat IDs:

- Reject IDs that do not exist.
- Reject IDs that do not belong to the selected theater.
- Do not create partial reservations silently unless the UI clearly explains what happened.

## 9. Planned URL/View Design

Keep the design compatible with the current project.

Current page:

- `GET /movies/theater/<theater_id>/seats/book/`
  - show seats

Possible later views/URLs:

- `POST /movies/theater/<theater_id>/seats/reserve/`
  - reserve selected seats for 2 minutes
  - starts transaction
  - creates `SeatReservation` rows
  - redirects to confirmation/payment placeholder page

- `GET /movies/reservations/<reservation_token>/confirm/`
  - show selected seats and remaining time
  - show placeholder payment/confirm button

- `POST /movies/reservations/<reservation_token>/confirm/`
  - confirm reservation
  - create bookings
  - mark seats booked
  - mark reservation rows confirmed

- `POST /movies/reservations/<reservation_token>/cancel/`
  - optional cancellation endpoint
  - mark reservation rows cancelled

Simple compatibility plan:

- Keep the existing seat selection URL for displaying seats.
- Change its form action later to the new reserve endpoint.
- Add a new reservation confirmation template.
- Keep final redirect to `profile` after successful confirmation.

## 10. Files Expected To Change Later

| File path | Planned change | Reason |
|---|---|---|
| `movies/models.py` | Add `SeatReservation` model and status choices | Store temporary reservation state separately from final booking |
| `movies/views.py` | Add reserve, confirm, and optional cancel views; update seat availability logic | Implement reservation flow and confirmation logic |
| `movies/urls.py` | Add reservation/confirmation URL routes | Connect new views to browser actions |
| `movies/admin.py` | Register `SeatReservation` in admin | Inspect reservations during development/debugging |
| `templates/movies/seat_selection.html` | Show reserved seats as unavailable; post to reserve endpoint | Update UI for temporary holds |
| `templates/movies/reservation_confirm.html` | New confirmation/payment placeholder page | Let user confirm booking before timeout |
| `movies/migrations/0003_*.py` | Migration for `SeatReservation` model | Apply database schema changes |
| `movies/tests.py` | Add reservation, timeout, confirmation, and concurrency tests | Verify correctness |
| `movies/management/__init__.py` | New package file if missing | Allow management command discovery |
| `movies/management/commands/__init__.py` | New package file if missing | Allow management command discovery |
| `movies/management/commands/release_expired_reservations.py` | New cleanup command | Expire old reservations in background |

## 11. Testing Plan

Manual tests:

- Reserve an available seat.
- Confirm that a second user cannot reserve the same active reserved seat.
- Wait 2 minutes and confirm the reservation expires.
- Confirm an expired seat becomes available again.
- Confirm a reservation before expiry and verify it creates a `Booking`.
- Try to confirm after expiry and verify it fails safely.
- Close the browser after reservation and verify the seat is not permanently blocked.
- Submit invalid seat IDs and verify they are rejected.
- Try to reserve an already booked seat and verify it is blocked.
- Run the cleanup command and confirm expired reservations change to `EXPIRED`.

Automated tests:

- Reservation creation for available seats.
- Active reservation blocks another user.
- Expired reservation does not block availability.
- Expired reservation cleanup command marks rows as `EXPIRED`.
- Confirmed reservation marks `Seat.is_booked=True`.
- Confirmed reservation creates `Booking`.
- Confirmation after expiry fails.
- Already booked seats cannot be reserved.
- Invalid seat IDs are rejected.
- Same user duplicate reservation behavior is handled.
- Concurrency/race condition simulation where practical.

Concurrency test note:

True concurrent behavior is hard to prove fully with SQLite in a local unit test. Tests can still cover transaction code paths and business rules. For stronger concurrency tests, use PostgreSQL in a test environment and run simultaneous reservation attempts.

## 12. Acceptance Criteria

Task 2 is complete when:

- Seats can be reserved temporarily for 2 minutes.
- Active reserved seats are unavailable to other users.
- Expired reservations are released automatically.
- Confirmed reservations create bookings.
- Confirmed reservations mark seats as permanently booked.
- Double booking is prevented.
- Atomic transaction logic is used.
- Row-level locking is used where supported.
- SQLite limitations are understood and documented.
- PostgreSQL is recommended for production-grade locking.
- Edge cases are handled safely.
- Django checks and tests pass.

## 13. Final Summary

The planned design adds a `SeatReservation` model between seat selection and final booking. `Seat.is_booked` will continue to mean permanently booked, while active `SeatReservation` rows will mean temporarily unavailable. Reservations will last 2 minutes, then expire automatically through a cleanup management command.

Concurrency will be handled with `transaction.atomic()`, `select_for_update()` where supported, and checks for active reservations inside the same transaction. SQLite can demonstrate the flow locally, but PostgreSQL is recommended for production because it supports true row-level locking.

Implementation has not been done yet. This document is only the planning step.

Next instruction needed from the user:

`Please implement Task 2 using this plan.`
