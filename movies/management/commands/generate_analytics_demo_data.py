import math
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from movies.models import Booking, Movie, PaymentTransaction, Seat, Theater


def chunks(values, size):
    for index in range(0, len(values), size):
        yield values[index:index + size]


class Command(BaseCommand):
    help = 'Create demo/test analytics data for the admin dashboard.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--bookings',
            type=int,
            default=50000,
            help='Number of demo booking rows to create.',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Bulk operation batch size.',
        )

    def handle(self, *args, **options):
        booking_count = options['bookings']
        batch_size = options['batch_size']
        if booking_count <= 0:
            raise CommandError('--bookings must be greater than 0.')
        if batch_size <= 0:
            raise CommandError('--batch-size must be greater than 0.')

        self.stdout.write(
            self.style.WARNING(
                'Creating demo analytics data only. Do not run this against production data.'
            )
        )

        run_id = uuid.uuid4().hex[:8]
        run_name = f'Analytics Demo {run_id}'
        now = timezone.now()
        User = get_user_model()

        with transaction.atomic():
            user, user_created = User.objects.get_or_create(
                username='analytics_demo_user',
                defaults={'email': 'analytics-demo@example.com'},
            )
            if user_created:
                user.set_unusable_password()
                user.save(update_fields=['password'])

            movies = []
            for index in range(10):
                movie, _ = Movie.objects.get_or_create(
                    name=f'Analytics Demo Movie {index + 1}',
                    defaults={
                        'image': 'movies/test.jpg',
                        'rating': '8.0',
                        'cast': 'Demo Cast',
                        'description': 'Demo movie for analytics testing.',
                    },
                )
                movies.append(movie)

            theater_count = min(max(10, math.ceil(booking_count / 500)), 200)
            theater_objects = [
                Theater(
                    name=f'{run_name} Screen {index + 1}',
                    movie=movies[index % len(movies)],
                    time=now + timedelta(hours=index),
                )
                for index in range(theater_count)
            ]
            Theater.objects.bulk_create(theater_objects, batch_size=batch_size)
            theaters = list(
                Theater.objects.filter(name__startswith=run_name)
                .select_related('movie')
                .order_by('id')
            )

            seat_count = max(booking_count, math.ceil(booking_count * 1.2))
            seat_objects = [
                Seat(
                    theater=theaters[index % len(theaters)],
                    seat_number=f'D{(index % 9999) + 1}',
                )
                for index in range(seat_count)
            ]
            Seat.objects.bulk_create(seat_objects, batch_size=batch_size)
            seats = list(
                Seat.objects.filter(theater__in=theaters)
                .select_related('theater', 'theater__movie')
                .order_by('id')[:booking_count]
            )

            booking_objects = []
            captured_payment_objects = []
            for index, seat in enumerate(seats):
                booked_at = now - timedelta(hours=index % 168)
                booking_objects.append(
                    Booking(
                        user=user,
                        seat=seat,
                        movie=seat.theater.movie,
                        theater=seat.theater,
                        booked_at=booked_at,
                    )
                )
                captured_payment_objects.append(
                    PaymentTransaction(
                        user=user,
                        reservation_token=uuid.uuid4(),
                        razorpay_order_id=f'order_demo_{run_id}_{index}',
                        razorpay_payment_id=f'pay_demo_{run_id}_{index}',
                        amount=20000,
                        currency='INR',
                        status=PaymentTransaction.STATUS_CAPTURED,
                        idempotency_key=f'demo:{run_id}:captured:{index}',
                        created_at=booked_at,
                        updated_at=booked_at,
                        verified_at=booked_at,
                    )
                )

            Booking.objects.bulk_create(booking_objects, batch_size=batch_size)
            PaymentTransaction.objects.bulk_create(
                captured_payment_objects,
                batch_size=batch_size,
            )

            seat_ids = [seat.id for seat in seats]
            for seat_id_chunk in chunks(seat_ids, batch_size):
                Seat.objects.filter(id__in=seat_id_chunk).update(is_booked=True)

            extra_attempt_count = max(1, booking_count // 10)
            extra_payment_objects = []
            for index in range(extra_attempt_count):
                status = (
                    PaymentTransaction.STATUS_CANCELLED
                    if index % 2 == 0
                    else PaymentTransaction.STATUS_FAILED
                )
                extra_payment_objects.append(
                    PaymentTransaction(
                        user=user,
                        reservation_token=uuid.uuid4(),
                        razorpay_order_id=f'order_demo_{run_id}_attempt_{index}',
                        amount=20000,
                        currency='INR',
                        status=status,
                        idempotency_key=f'demo:{run_id}:attempt:{index}',
                        created_at=now - timedelta(hours=index % 72),
                        updated_at=now - timedelta(hours=index % 72),
                    )
                )
            PaymentTransaction.objects.bulk_create(
                extra_payment_objects,
                batch_size=batch_size,
            )

        self.stdout.write(self.style.SUCCESS(f'Demo run: {run_name}'))
        self.stdout.write(self.style.SUCCESS(f'Movies created/reused: {len(movies)}'))
        self.stdout.write(self.style.SUCCESS(f'Theaters created: {len(theaters)}'))
        self.stdout.write(self.style.SUCCESS(f'Seats created: {seat_count}'))
        self.stdout.write(self.style.SUCCESS(f'Bookings created: {len(booking_objects)}'))
        self.stdout.write(
            self.style.SUCCESS(
                f'Payment transactions created: {len(captured_payment_objects) + len(extra_payment_objects)}'
            )
        )
