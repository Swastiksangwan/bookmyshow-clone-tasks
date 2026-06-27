import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from movies.models import SeatReservation


class Command(BaseCommand):
    help = 'Mark expired seat reservations as expired.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--loop',
            action='store_true',
            help='Keep running cleanup until stopped with Ctrl+C.',
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=30,
            help='Seconds to wait between cleanup runs in loop mode.',
        )

    def handle(self, *args, **options):
        if options['loop']:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Running reservation cleanup every {options['interval']} seconds. Press Ctrl+C to stop."
                )
            )
            try:
                while True:
                    self.release_expired()
                    time.sleep(options['interval'])
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING('Stopped reservation cleanup loop.'))
            return

        self.release_expired()

    def release_expired(self):
        now = timezone.now()
        released_count = SeatReservation.objects.filter(
            status=SeatReservation.STATUS_RESERVED,
            expires_at__lte=now,
        ).update(status=SeatReservation.STATUS_EXPIRED)

        self.stdout.write(
            self.style.SUCCESS(f'Released {released_count} expired reservation(s).')
        )
