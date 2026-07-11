import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from .models import (
    Booking,
    BookingEmailNotification,
    PaymentTransaction,
    SeatReservation,
)


logger = logging.getLogger(__name__)


def _clean_subject(subject):
    return " ".join(subject.split()).strip()


def _amount_rupees(amount_paise):
    return amount_paise / 100


def build_booking_email_payload(payment_transaction):
    if payment_transaction.status != PaymentTransaction.STATUS_CAPTURED:
        raise ValueError("Ticket email can be built only for captured payments.")

    reservations = list(
        SeatReservation.objects.select_related("seat", "movie", "theater")
        .filter(
            reservation_token=payment_transaction.reservation_token,
            user=payment_transaction.user,
            status=SeatReservation.STATUS_CONFIRMED,
        )
        .order_by("seat__seat_number")
    )
    if not reservations:
        raise ValueError("Confirmed reservations were not found for this payment.")

    seat_ids = [reservation.seat_id for reservation in reservations]
    bookings = list(
        Booking.objects.select_related("seat", "movie", "theater")
        .filter(
            user=payment_transaction.user,
            seat_id__in=seat_ids,
            movie=reservations[0].movie,
            theater=reservations[0].theater,
        )
        .order_by("seat__seat_number")
    )
    if len(bookings) != len(seat_ids):
        raise ValueError("Final booking rows were not found for all reserved seats.")

    theater = reservations[0].theater
    movie = reservations[0].movie
    confirmed_at = payment_transaction.verified_at or timezone.now()

    return {
        "booking_ids": [booking.id for booking in bookings],
        "customer_username": payment_transaction.user.username,
        "movie_name": movie.name,
        "theater_name": theater.name,
        "show_time": theater.time.isoformat(),
        "show_time_display": timezone.localtime(theater.time).strftime("%B %d, %Y %I:%M %p"),
        "seat_numbers": [reservation.seat.seat_number for reservation in reservations],
        "razorpay_payment_id": payment_transaction.razorpay_payment_id or "",
        "razorpay_order_id": payment_transaction.razorpay_order_id,
        "amount": payment_transaction.amount,
        "amount_rupees": _amount_rupees(payment_transaction.amount),
        "currency": payment_transaction.currency,
        "confirmed_at": confirmed_at.isoformat(),
        "confirmed_at_display": timezone.localtime(confirmed_at).strftime("%B %d, %Y %I:%M %p"),
    }


def enqueue_booking_confirmation_email(payment_transaction):
    payment_transaction.refresh_from_db()
    if payment_transaction.status != PaymentTransaction.STATUS_CAPTURED:
        logger.info(
            "Skipping ticket email enqueue for payment %s with status %s.",
            payment_transaction.id,
            payment_transaction.status,
        )
        return None, False

    recipient_email = (payment_transaction.user.email or "").strip()
    try:
        payload = build_booking_email_payload(payment_transaction)
    except ValueError as exc:
        logger.warning(
            "Could not build ticket email payload for payment %s: %s",
            payment_transaction.id,
            exc,
        )
        return None, False

    subject = f"Your BookMySeat ticket for {payload['movie_name']}"
    defaults = {
        "user": payment_transaction.user,
        "booking": Booking.objects.filter(id__in=payload["booking_ids"]).order_by("id").first(),
        "reservation_token": payment_transaction.reservation_token,
        "recipient_email": recipient_email,
        "subject": subject,
        "status": BookingEmailNotification.STATUS_PENDING,
        "payload": payload,
    }

    notification, created = BookingEmailNotification.objects.get_or_create(
        payment_transaction=payment_transaction,
        defaults=defaults,
    )

    if not recipient_email:
        notification.user = payment_transaction.user
        notification.reservation_token = payment_transaction.reservation_token
        notification.recipient_email = recipient_email
        notification.subject = subject
        notification.payload = payload
        notification.status = BookingEmailNotification.STATUS_FAILED
        notification.last_error = "User email is missing."
        notification.next_retry_at = None
        notification.save(
            update_fields=[
                "user",
                "reservation_token",
                "recipient_email",
                "subject",
                "payload",
                "status",
                "last_error",
                "next_retry_at",
                "updated_at",
            ]
        )
        logger.warning(
            "Ticket email notification %s failed because user %s has no email.",
            notification.id,
            payment_transaction.user_id,
        )
        return notification, created

    if not created and notification.status != BookingEmailNotification.STATUS_SENT:
        notification.user = payment_transaction.user
        notification.booking = defaults["booking"]
        notification.reservation_token = payment_transaction.reservation_token
        notification.recipient_email = recipient_email
        notification.subject = subject
        notification.payload = payload
        notification.status = BookingEmailNotification.STATUS_PENDING
        notification.last_error = ""
        notification.next_retry_at = None
        notification.save(
            update_fields=[
                "user",
                "booking",
                "reservation_token",
                "recipient_email",
                "subject",
                "payload",
                "status",
                "last_error",
                "next_retry_at",
                "updated_at",
            ]
        )

    logger.info(
        "Ticket email notification %s %s for payment %s.",
        notification.id,
        "created" if created else "reused",
        payment_transaction.id,
    )
    return notification, created


def render_booking_confirmation_email(notification):
    context = dict(notification.payload)
    context["notification"] = notification

    subject = _clean_subject(
        render_to_string("emails/booking_confirmation_subject.txt", context)
    )
    text_body = render_to_string("emails/booking_confirmation.txt", context)
    html_body = render_to_string("emails/booking_confirmation.html", context)
    return subject, text_body, html_body


def send_booking_confirmation_email(notification):
    try:
        subject, text_body, html_body = render_booking_confirmation_email(notification)
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[notification.recipient_email],
        )
        email.attach_alternative(html_body, "text/html")
        sent_count = email.send(fail_silently=False)
        if sent_count:
            notification.mark_sent()
            logger.info("Sent ticket email notification %s.", notification.id)
            return True

        notification.mark_failed("Email backend did not send the message.")
        logger.warning("Ticket email notification %s was not sent.", notification.id)
        return False
    except Exception as exc:
        notification.mark_failed(exc)
        logger.warning(
            "Ticket email notification %s failed: %s",
            notification.id,
            exc,
        )
        return False
