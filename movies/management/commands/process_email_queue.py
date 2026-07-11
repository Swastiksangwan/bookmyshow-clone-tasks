import time

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from movies.email_notifications import send_booking_confirmation_email
from movies.models import BookingEmailNotification


class Command(BaseCommand):
    help = "Process queued booking confirmation emails."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Maximum number of queued emails to process per run.",
        )
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Keep processing the queue until stopped with Ctrl+C.",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=30,
            help="Seconds to wait between queue runs in loop mode.",
        )

    def handle(self, *args, **options):
        if options["loop"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Running email queue processor every {options['interval']} seconds. Press Ctrl+C to stop."
                )
            )
            try:
                while True:
                    self.process_queue(options["limit"])
                    time.sleep(options["interval"])
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING("Stopped email queue processor."))
            return

        self.process_queue(options["limit"])

    def process_queue(self, limit):
        now = timezone.now()
        queued_ids = list(
            BookingEmailNotification.objects.filter(
                Q(status=BookingEmailNotification.STATUS_PENDING)
                | Q(status=BookingEmailNotification.STATUS_FAILED),
                attempt_count__lt=F("max_attempts"),
            )
            .filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now))
            .order_by("created_at")
            .values_list("id", flat=True)[:limit]
        )

        processed_count = 0
        sent_count = 0
        failed_count = 0
        skipped_count = 0

        for notification_id in queued_ids:
            with transaction.atomic():
                notification = (
                    BookingEmailNotification.objects.select_for_update()
                    .get(id=notification_id)
                )
                if not notification.can_retry():
                    skipped_count += 1
                    continue
                notification.status = BookingEmailNotification.STATUS_SENDING
                notification.save(update_fields=["status", "updated_at"])

            processed_count += 1
            was_sent = send_booking_confirmation_email(notification)
            notification.refresh_from_db()
            if was_sent and notification.status == BookingEmailNotification.STATUS_SENT:
                sent_count += 1
            else:
                failed_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Processed {processed} email notification(s): {sent} sent, {failed} failed, {skipped} skipped.".format(
                    processed=processed_count,
                    sent=sent_count,
                    failed=failed_count,
                    skipped=skipped_count,
                )
            )
        )
