import hashlib
import hmac
import json
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, Group, User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from .analytics import (
    can_view_analytics,
    clear_admin_analytics_cache,
    get_admin_analytics,
    get_cached_admin_analytics,
)
from .models import (
    Booking,
    Movie,
    PaymentTransaction,
    PaymentWebhookEvent,
    Seat,
    SeatReservation,
    Theater,
)
from .views import (
    get_or_create_payment_transaction,
    verify_razorpay_checkout_signature,
    verify_razorpay_webhook_signature,
)
from .validators import extract_youtube_video_id


class YouTubeTrailerValidationTests(TestCase):
    def test_valid_watch_url(self):
        video_id = extract_youtube_video_id(
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        )
        self.assertEqual(video_id, 'dQw4w9WgXcQ')

    def test_valid_watch_url_without_www(self):
        video_id = extract_youtube_video_id(
            'https://youtube.com/watch?v=dQw4w9WgXcQ'
        )
        self.assertEqual(video_id, 'dQw4w9WgXcQ')

    def test_valid_short_url(self):
        video_id = extract_youtube_video_id('https://youtu.be/dQw4w9WgXcQ')
        self.assertEqual(video_id, 'dQw4w9WgXcQ')

    def test_valid_embed_url(self):
        video_id = extract_youtube_video_id(
            'https://www.youtube.com/embed/dQw4w9WgXcQ'
        )
        self.assertEqual(video_id, 'dQw4w9WgXcQ')

    def test_valid_mobile_watch_url(self):
        video_id = extract_youtube_video_id(
            'https://m.youtube.com/watch?v=dQw4w9WgXcQ'
        )
        self.assertEqual(video_id, 'dQw4w9WgXcQ')

    def test_invalid_domain_is_rejected(self):
        self.assertIsNone(extract_youtube_video_id('https://example.com/video'))

    def test_fake_youtube_domain_is_rejected(self):
        self.assertIsNone(
            extract_youtube_video_id(
                'https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ'
            )
        )

    def test_non_https_url_is_rejected(self):
        self.assertIsNone(
            extract_youtube_video_id(
                'http://www.youtube.com/watch?v=dQw4w9WgXcQ'
            )
        )

    def test_javascript_url_is_rejected(self):
        self.assertIsNone(extract_youtube_video_id('javascript:alert(1)'))

    def test_script_tag_is_rejected(self):
        self.assertIsNone(extract_youtube_video_id('<script>alert(1)</script>'))

    def test_empty_value_is_rejected(self):
        self.assertIsNone(extract_youtube_video_id(''))


class MovieDetailTrailerTests(TestCase):
    def create_movie(self, trailer_url=''):
        return Movie.objects.create(
            name='Test Movie',
            image='movies/test.jpg',
            rating='8.5',
            cast='Actor One, Actor Two',
            description='A test movie description.',
            trailer_url=trailer_url,
        )

    def test_movie_detail_page_loads(self):
        movie = self.create_movie()

        response = self.client.get(reverse('movie_detail', args=[movie.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Movie')
        self.assertContains(response, 'Trailer not available.')

    def test_valid_trailer_uses_safe_embed_url(self):
        movie = self.create_movie(
            trailer_url='https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        )

        response = self.client.get(reverse('movie_detail', args=[movie.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'src="https://www.youtube.com/embed/dQw4w9WgXcQ"',
        )
        self.assertContains(response, 'loading="lazy"')
        self.assertNotContains(response, movie.trailer_url)

    def test_invalid_trailer_does_not_render_iframe(self):
        movie = self.create_movie(trailer_url='<script>alert(1)</script>')

        response = self.client.get(reverse('movie_detail', args=[movie.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Trailer not available.')
        self.assertNotContains(response, '<iframe')
        self.assertNotContains(response, '<script>alert(1)</script>')


class SeatReservationFlowTests(TestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(
            username='user_a',
            password='password123',
        )
        self.user_b = User.objects.create_user(
            username='user_b',
            password='password123',
        )
        self.movie = Movie.objects.create(
            name='Reservation Movie',
            image='movies/test.jpg',
            rating='9.0',
            cast='Actor One',
            description='Reservation test movie.',
        )
        self.theater = Theater.objects.create(
            name='Main Theater',
            movie=self.movie,
            time=timezone.now() + timedelta(days=1),
        )
        self.other_theater = Theater.objects.create(
            name='Other Theater',
            movie=self.movie,
            time=timezone.now() + timedelta(days=2),
        )
        self.seat_a1 = Seat.objects.create(
            theater=self.theater,
            seat_number='A1',
        )
        self.seat_a2 = Seat.objects.create(
            theater=self.theater,
            seat_number='A2',
        )
        self.other_seat = Seat.objects.create(
            theater=self.other_theater,
            seat_number='B1',
        )

    def login_as_user_a(self):
        self.client.login(username='user_a', password='password123')

    def reserve_seat(self, seat=None, user=None):
        seat = seat or self.seat_a1
        if user == self.user_b:
            client = Client()
            client.login(username='user_b', password='password123')
        else:
            client = self.client
            self.login_as_user_a()

        response = client.post(
            reverse('reserve_seats', args=[self.theater.id]),
            {'seats': [str(seat.id)]},
        )
        return response

    def create_reservation(self, user=None, seat=None, expires_at=None):
        user = user or self.user_a
        seat = seat or self.seat_a1
        return SeatReservation.objects.create(
            user=user,
            seat=seat,
            theater=seat.theater,
            movie=seat.theater.movie,
            status=SeatReservation.STATUS_RESERVED,
            expires_at=expires_at or timezone.now() + timedelta(minutes=2),
        )

    def test_reservation_helper_methods(self):
        active = self.create_reservation()
        expired = self.create_reservation(
            seat=self.seat_a2,
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        self.assertTrue(active.is_active())
        self.assertFalse(active.has_expired())
        self.assertTrue(expired.has_expired())
        self.assertFalse(expired.is_active())

    def test_logged_in_user_can_reserve_available_seat(self):
        self.login_as_user_a()

        response = self.client.post(
            reverse('reserve_seats', args=[self.theater.id]),
            {'seats': [str(self.seat_a1.id)]},
        )

        self.assertEqual(response.status_code, 302)
        reservation = SeatReservation.objects.get(seat=self.seat_a1)
        self.assertEqual(reservation.status, SeatReservation.STATUS_RESERVED)
        self.assertEqual(reservation.user, self.user_a)
        self.assertGreater(
            reservation.expires_at,
            timezone.now() + timedelta(seconds=100),
        )
        self.assertEqual(Booking.objects.count(), 0)
        self.seat_a1.refresh_from_db()
        self.assertFalse(self.seat_a1.is_booked)

    def test_active_reservation_blocks_other_user(self):
        self.reserve_seat()

        response = self.reserve_seat(user=self.user_b)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'Some selected seats are no longer available. Please choose again.',
        )
        active_count = SeatReservation.objects.filter(
            seat=self.seat_a1,
            status=SeatReservation.STATUS_RESERVED,
            expires_at__gt=timezone.now(),
        ).count()
        self.assertEqual(active_count, 1)

    def test_expired_reservation_does_not_block_new_reservation(self):
        old_reservation = self.create_reservation(
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        response = self.reserve_seat(user=self.user_b)

        self.assertEqual(response.status_code, 302)
        old_reservation.refresh_from_db()
        self.assertEqual(old_reservation.status, SeatReservation.STATUS_EXPIRED)
        active_count = SeatReservation.objects.filter(
            seat=self.seat_a1,
            status=SeatReservation.STATUS_RESERVED,
            expires_at__gt=timezone.now(),
        ).count()
        self.assertEqual(active_count, 1)

    def test_direct_confirm_no_longer_creates_booking_without_payment(self):
        self.reserve_seat()
        reservation = SeatReservation.objects.get(seat=self.seat_a1)

        response = self.client.post(
            reverse('reservation_confirm', args=[reservation.reservation_token])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payment verification is required before booking confirmation.')
        self.assertEqual(Booking.objects.count(), 0)
        self.seat_a1.refresh_from_db()
        reservation.refresh_from_db()
        self.assertFalse(self.seat_a1.is_booked)
        self.assertEqual(reservation.status, SeatReservation.STATUS_RESERVED)
        self.assertIsNone(reservation.confirmed_at)

    def test_confirm_after_expiry_fails_safely(self):
        reservation = self.create_reservation(
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.login_as_user_a()

        response = self.client.post(
            reverse('reservation_confirm', args=[reservation.reservation_token])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This reservation has expired. Please select seats again.')
        self.assertEqual(Booking.objects.count(), 0)
        self.seat_a1.refresh_from_db()
        reservation.refresh_from_db()
        self.assertFalse(self.seat_a1.is_booked)
        self.assertEqual(reservation.status, SeatReservation.STATUS_EXPIRED)

    def test_already_booked_seat_cannot_be_reserved(self):
        self.seat_a1.is_booked = True
        self.seat_a1.save()
        self.login_as_user_a()

        response = self.client.post(
            reverse('reserve_seats', args=[self.theater.id]),
            {'seats': [str(self.seat_a1.id)]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'Some selected seats are no longer available. Please choose again.',
        )
        self.assertEqual(SeatReservation.objects.count(), 0)

    def test_invalid_seat_ids_are_rejected(self):
        self.login_as_user_a()

        response = self.client.post(
            reverse('reserve_seats', args=[self.theater.id]),
            {'seats': [str(self.other_seat.id), '999999']},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'Some selected seats are no longer available. Please choose again.',
        )
        self.assertEqual(SeatReservation.objects.count(), 0)

    def test_non_integer_seat_id_is_rejected(self):
        self.login_as_user_a()

        response = self.client.post(
            reverse('reserve_seats', args=[self.theater.id]),
            {'seats': ['not-a-seat']},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid seat selection. Please choose again.')
        self.assertEqual(SeatReservation.objects.count(), 0)

    def test_duplicate_seat_ids_create_one_reservation(self):
        self.login_as_user_a()

        response = self.client.post(
            reverse('reserve_seats', args=[self.theater.id]),
            {'seats': [str(self.seat_a1.id), str(self.seat_a1.id)]},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(SeatReservation.objects.count(), 1)

    def test_release_expired_reservations_command(self):
        expired = self.create_reservation(
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        active = self.create_reservation(
            seat=self.seat_a2,
            expires_at=timezone.now() + timedelta(minutes=2),
        )
        output = StringIO()

        call_command('release_expired_reservations', stdout=output)

        expired.refresh_from_db()
        active.refresh_from_db()
        self.assertEqual(expired.status, SeatReservation.STATUS_EXPIRED)
        self.assertEqual(active.status, SeatReservation.STATUS_RESERVED)
        self.assertIn('Released 1 expired reservation(s).', output.getvalue())


@override_settings(
    RAZORPAY_KEY_ID='rzp_test_key',
    RAZORPAY_KEY_SECRET='test_secret',
    RAZORPAY_WEBHOOK_SECRET='webhook_secret',
    TICKET_PRICE_PAISE=20000,
    PAYMENT_CURRENCY='INR',
)
class PaymentFlowTests(SeatReservationFlowTests):
    def checkout_signature(self, order_id='order_test', payment_id='pay_test'):
        return hmac.new(
            b'test_secret',
            f'{order_id}|{payment_id}'.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()

    def webhook_signature(self, raw_body):
        return hmac.new(
            b'webhook_secret',
            raw_body,
            hashlib.sha256,
        ).hexdigest()

    def create_payment_transaction(self, reservation, order_id='order_test'):
        return PaymentTransaction.objects.create(
            user=reservation.user,
            reservation_token=reservation.reservation_token,
            razorpay_order_id=order_id,
            amount=20000,
            currency='INR',
            status=PaymentTransaction.STATUS_CREATED,
            idempotency_key=f'reservation:{reservation.reservation_token}:razorpay_order:{order_id}',
        )

    def test_payment_transaction_model_creation(self):
        reservation = self.create_reservation()
        transaction_obj = self.create_payment_transaction(reservation)

        self.assertEqual(transaction_obj.status, PaymentTransaction.STATUS_CREATED)
        self.assertFalse(transaction_obj.is_successful())
        self.assertFalse(transaction_obj.is_finalized())

    def test_payment_webhook_event_model_creation(self):
        event = PaymentWebhookEvent.objects.create(
            event_id='evt_test',
            event_type='payment.captured',
            raw_payload={'event': 'payment.captured'},
            signature_valid=True,
        )

        self.assertEqual(event.provider, 'razorpay')
        self.assertEqual(event.processing_status, PaymentWebhookEvent.STATUS_RECEIVED)

    @patch('movies.views.create_razorpay_order')
    def test_razorpay_order_created_and_reused_for_active_reservation(self, mock_create_order):
        reservation = self.create_reservation()
        mock_create_order.return_value = {'id': 'order_test'}

        transaction_one, reservations, error, expired = get_or_create_payment_transaction(
            reservation.reservation_token,
            self.user_a,
        )
        transaction_two, reservations, error, expired = get_or_create_payment_transaction(
            reservation.reservation_token,
            self.user_a,
        )

        self.assertIsNone(error)
        self.assertFalse(expired)
        self.assertEqual(transaction_one.id, transaction_two.id)
        self.assertEqual(mock_create_order.call_count, 1)

    @patch('movies.views.create_razorpay_order')
    def test_razorpay_order_not_created_for_expired_reservation(self, mock_create_order):
        reservation = self.create_reservation(
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        transaction_obj, reservations, error, expired = get_or_create_payment_transaction(
            reservation.reservation_token,
            self.user_a,
        )

        self.assertIsNone(transaction_obj)
        self.assertTrue(expired)
        self.assertIn('expired', error)
        mock_create_order.assert_not_called()

    @override_settings(RAZORPAY_KEY_ID='', RAZORPAY_KEY_SECRET='')
    def test_missing_razorpay_configuration_shows_safe_error(self):
        self.reserve_seat()
        reservation = SeatReservation.objects.get(seat=self.seat_a1)

        response = self.client.get(
            reverse('reservation_confirm', args=[reservation.reservation_token])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payment gateway is not configured')
        self.assertEqual(PaymentTransaction.objects.count(), 0)

    def test_signature_helpers(self):
        signature = self.checkout_signature()
        self.assertTrue(
            verify_razorpay_checkout_signature('order_test', 'pay_test', signature)
        )
        self.assertFalse(
            verify_razorpay_checkout_signature('order_test', 'pay_test', 'bad')
        )

        raw_body = b'{"event":"payment.captured"}'
        webhook_signature = self.webhook_signature(raw_body)
        self.assertTrue(verify_razorpay_webhook_signature(raw_body, webhook_signature))
        self.assertFalse(verify_razorpay_webhook_signature(raw_body, 'bad'))

    def test_successful_verified_payment_creates_booking_once(self):
        self.reserve_seat()
        reservation = SeatReservation.objects.get(seat=self.seat_a1)
        transaction_obj = self.create_payment_transaction(reservation)
        signature = self.checkout_signature()

        response = self.client.post(
            reverse('payment_verify', args=[reservation.reservation_token]),
            {
                'razorpay_order_id': transaction_obj.razorpay_order_id,
                'razorpay_payment_id': 'pay_test',
                'razorpay_signature': signature,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Booking.objects.count(), 1)
        transaction_obj.refresh_from_db()
        reservation.refresh_from_db()
        self.seat_a1.refresh_from_db()
        self.assertEqual(transaction_obj.status, PaymentTransaction.STATUS_CAPTURED)
        self.assertEqual(reservation.status, SeatReservation.STATUS_CONFIRMED)
        self.assertTrue(self.seat_a1.is_booked)

        response = self.client.post(
            reverse('payment_verify', args=[reservation.reservation_token]),
            {
                'razorpay_order_id': transaction_obj.razorpay_order_id,
                'razorpay_payment_id': 'pay_test',
                'razorpay_signature': signature,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Booking.objects.count(), 1)

    def test_invalid_checkout_signature_marks_payment_failed(self):
        self.reserve_seat()
        reservation = SeatReservation.objects.get(seat=self.seat_a1)
        transaction_obj = self.create_payment_transaction(reservation)

        response = self.client.post(
            reverse('payment_verify', args=[reservation.reservation_token]),
            {
                'razorpay_order_id': transaction_obj.razorpay_order_id,
                'razorpay_payment_id': 'pay_bad',
                'razorpay_signature': 'bad-signature',
            },
        )

        self.assertEqual(response.status_code, 302)
        transaction_obj.refresh_from_db()
        self.assertEqual(transaction_obj.status, PaymentTransaction.STATUS_FAILED)
        self.assertEqual(Booking.objects.count(), 0)

    def test_payment_verification_after_expiry_does_not_create_booking(self):
        reservation = self.create_reservation(
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        transaction_obj = self.create_payment_transaction(reservation)
        self.login_as_user_a()

        response = self.client.post(
            reverse('payment_verify', args=[reservation.reservation_token]),
            {
                'razorpay_order_id': transaction_obj.razorpay_order_id,
                'razorpay_payment_id': 'pay_test',
                'razorpay_signature': self.checkout_signature(),
            },
        )

        self.assertEqual(response.status_code, 302)
        transaction_obj.refresh_from_db()
        reservation.refresh_from_db()
        self.assertEqual(Booking.objects.count(), 0)
        self.assertEqual(transaction_obj.status, PaymentTransaction.STATUS_REQUIRES_REVIEW)
        self.assertEqual(reservation.status, SeatReservation.STATUS_EXPIRED)

    def test_webhook_with_invalid_signature_returns_400(self):
        response = self.client.post(
            reverse('razorpay_webhook'),
            data=b'{"event":"payment.captured"}',
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE='bad',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(PaymentWebhookEvent.objects.count(), 0)

    def test_valid_webhook_event_is_stored_and_duplicate_is_ignored(self):
        raw_body = json.dumps(
            {
                'id': 'evt_test',
                'event': 'payment.failed',
                'payload': {'payment': {'entity': {'id': 'pay_missing'}}},
            },
            separators=(',', ':'),
        ).encode('utf-8')
        signature = self.webhook_signature(raw_body)

        response = self.client.post(
            reverse('razorpay_webhook'),
            data=raw_body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=signature,
        )
        duplicate_response = self.client.post(
            reverse('razorpay_webhook'),
            data=raw_body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertEqual(PaymentWebhookEvent.objects.count(), 1)
        event = PaymentWebhookEvent.objects.get()
        self.assertTrue(event.signature_valid)

    def test_captured_webhook_finalizes_booking_idempotently(self):
        reservation = self.create_reservation()
        transaction_obj = self.create_payment_transaction(reservation)
        raw_body = json.dumps(
            {
                'id': 'evt_capture_1',
                'event': 'payment.captured',
                'payload': {
                    'payment': {
                        'entity': {
                            'id': 'pay_test',
                            'order_id': transaction_obj.razorpay_order_id,
                        }
                    }
                },
            },
            separators=(',', ':'),
        ).encode('utf-8')
        signature = self.webhook_signature(raw_body)

        response = self.client.post(
            reverse('razorpay_webhook'),
            data=raw_body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=signature,
        )
        duplicate_response = self.client.post(
            reverse('razorpay_webhook'),
            data=raw_body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertEqual(Booking.objects.count(), 1)
        transaction_obj.refresh_from_db()
        reservation.refresh_from_db()
        self.seat_a1.refresh_from_db()
        self.assertEqual(transaction_obj.status, PaymentTransaction.STATUS_CAPTURED)
        self.assertEqual(reservation.status, SeatReservation.STATUS_CONFIRMED)
        self.assertTrue(self.seat_a1.is_booked)


class AdminAnalyticsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username='analytics_user',
            password='password123',
        )
        self.staff_user = User.objects.create_user(
            username='analytics_staff',
            password='password123',
            is_staff=True,
        )
        self.superuser = User.objects.create_superuser(
            username='analytics_superuser',
            email='super@example.com',
            password='password123',
        )
        self.analytics_group = Group.objects.create(name='analytics_admin')
        self.group_user = User.objects.create_user(
            username='analytics_group_user',
            password='password123',
        )
        self.group_user.groups.add(self.analytics_group)

    def tearDown(self):
        cache.clear()

    def create_movie(self, name):
        return Movie.objects.create(
            name=name,
            image='movies/test.jpg',
            rating='8.5',
            cast='Demo Cast',
            description='Demo movie.',
        )

    def create_theater_with_seats(self, movie_name, theater_name, seat_count):
        movie = self.create_movie(movie_name)
        theater = Theater.objects.create(
            name=theater_name,
            movie=movie,
            time=timezone.now() + timedelta(days=1),
        )
        seats = [
            Seat.objects.create(theater=theater, seat_number=f'A{index + 1}')
            for index in range(seat_count)
        ]
        return movie, theater, seats

    def create_booking(self, seat, user=None, booked_at=None):
        booking = Booking.objects.create(
            user=user or self.user,
            seat=seat,
            movie=seat.theater.movie,
            theater=seat.theater,
        )
        if booked_at is not None:
            Booking.objects.filter(pk=booking.pk).update(booked_at=booked_at)
            booking.refresh_from_db()
        return booking

    def create_payment(
        self,
        status,
        amount=20000,
        verified_at=None,
        created_at=None,
        suffix='1',
    ):
        transaction_obj = PaymentTransaction.objects.create(
            user=self.user,
            reservation_token='00000000-0000-0000-0000-000000000001',
            razorpay_order_id=f'order_analytics_{suffix}',
            razorpay_payment_id=(
                f'pay_analytics_{suffix}'
                if status == PaymentTransaction.STATUS_CAPTURED
                else None
            ),
            amount=amount,
            currency='INR',
            status=status,
            idempotency_key=f'analytics:{suffix}',
            verified_at=verified_at,
        )
        updates = {}
        if created_at is not None:
            updates['created_at'] = created_at
        if verified_at is not None:
            updates['verified_at'] = verified_at
        if updates:
            PaymentTransaction.objects.filter(pk=transaction_obj.pk).update(**updates)
            transaction_obj.refresh_from_db()
        return transaction_obj

    def test_permission_helper(self):
        self.assertFalse(can_view_analytics(AnonymousUser()))
        self.assertFalse(can_view_analytics(self.user))
        self.assertTrue(can_view_analytics(self.staff_user))
        self.assertTrue(can_view_analytics(self.superuser))
        self.assertTrue(can_view_analytics(self.group_user))

    def test_dashboard_access_control(self):
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

        self.client.login(username='analytics_user', password='password123')
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 403)
        self.client.logout()

        self.client.login(username='analytics_staff', password='password123')
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Admin Analytics Dashboard')
        self.client.logout()

        self.client.login(username='analytics_superuser', password='password123')
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)

    @override_settings(
        RAZORPAY_KEY_SECRET='server-secret',
        RAZORPAY_WEBHOOK_SECRET='webhook-secret',
    )
    def test_api_access_control_and_secret_safety(self):
        self.client.login(username='analytics_user', password='password123')
        response = self.client.get(reverse('admin_dashboard_api'))
        self.assertEqual(response.status_code, 403)
        self.client.logout()

        self.client.login(username='analytics_staff', password='password123')
        response = self.client.get(reverse('admin_dashboard_api'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('revenue', data)
        content = response.content.decode('utf-8')
        self.assertNotIn('server-secret', content)
        self.assertNotIn('webhook-secret', content)
        self.assertNotIn('raw_provider_payload', content)

    def test_revenue_aggregation_uses_captured_payments_only(self):
        now = timezone.now()
        self.create_payment(
            PaymentTransaction.STATUS_CAPTURED,
            amount=10000,
            verified_at=now - timedelta(minutes=5),
            suffix='today',
        )
        self.create_payment(
            PaymentTransaction.STATUS_CAPTURED,
            amount=30000,
            verified_at=now - timedelta(days=2),
            suffix='week',
        )
        self.create_payment(
            PaymentTransaction.STATUS_CAPTURED,
            amount=50000,
            verified_at=now - timedelta(days=40),
            suffix='old',
        )
        self.create_payment(
            PaymentTransaction.STATUS_FAILED,
            amount=90000,
            verified_at=now,
            suffix='failed',
        )

        analytics = get_admin_analytics()

        self.assertEqual(analytics['revenue']['today_paise'], 10000)
        self.assertEqual(analytics['revenue']['last_7_days_paise'], 40000)
        self.assertEqual(analytics['revenue']['today_rupees'], 100.0)

    def test_popular_movies_and_busiest_theaters(self):
        movie_a, theater_a, seats_a = self.create_theater_with_seats(
            'Popular A',
            'Theater A',
            4,
        )
        movie_b, theater_b, seats_b = self.create_theater_with_seats(
            'Popular B',
            'Theater B',
            2,
        )
        self.create_booking(seats_a[0])
        self.create_booking(seats_b[0])
        self.create_booking(seats_b[1])

        analytics = get_admin_analytics()

        self.assertEqual(analytics['popular_movies'][0]['movie_name'], movie_b.name)
        self.assertEqual(analytics['popular_movies'][0]['booking_count'], 2)
        self.assertEqual(analytics['popular_movies'][1]['movie_name'], movie_a.name)
        self.assertEqual(analytics['popular_movies'][1]['booking_count'], 1)

        self.assertEqual(
            analytics['busiest_theaters'][0]['theater_name'],
            theater_b.name,
        )
        self.assertEqual(analytics['busiest_theaters'][0]['booked_seats'], 2)
        self.assertEqual(analytics['busiest_theaters'][0]['total_seats'], 2)
        self.assertEqual(analytics['busiest_theaters'][0]['occupancy_rate'], 100.0)
        self.assertEqual(
            analytics['busiest_theaters'][1]['theater_name'],
            theater_a.name,
        )
        self.assertEqual(analytics['busiest_theaters'][1]['occupancy_rate'], 25.0)

    def test_peak_booking_hours(self):
        movie, theater, seats = self.create_theater_with_seats(
            'Peak Movie',
            'Peak Theater',
            3,
        )
        base = timezone.now().replace(minute=0, second=0, microsecond=0)
        hour_14 = base.replace(hour=14)
        hour_9 = base.replace(hour=9)
        self.create_booking(seats[0], booked_at=hour_14)
        self.create_booking(seats[1], booked_at=hour_14)
        self.create_booking(seats[2], booked_at=hour_9)

        analytics = get_admin_analytics()

        self.assertEqual(analytics['peak_booking_hours'][0]['hour'], 14)
        self.assertEqual(analytics['peak_booking_hours'][0]['booking_count'], 2)
        self.assertEqual(analytics['peak_booking_hours'][0]['label'], '14:00 - 14:59')

    def test_cancellation_rate(self):
        self.create_payment(PaymentTransaction.STATUS_CANCELLED, suffix='cancelled1')
        self.create_payment(PaymentTransaction.STATUS_CANCELLED, suffix='cancelled2')
        self.create_payment(PaymentTransaction.STATUS_FAILED, suffix='failed1')
        self.create_payment(
            PaymentTransaction.STATUS_CAPTURED,
            verified_at=timezone.now(),
            suffix='captured1',
        )

        analytics = get_admin_analytics()

        self.assertEqual(analytics['cancellation_rate']['total_attempts'], 4)
        self.assertEqual(analytics['cancellation_rate']['cancelled_attempts'], 2)
        self.assertEqual(analytics['cancellation_rate']['cancellation_rate'], 50.0)

    def test_cancellation_rate_without_attempts_is_zero(self):
        analytics = get_admin_analytics()

        self.assertEqual(analytics['cancellation_rate']['total_attempts'], 0)
        self.assertEqual(analytics['cancellation_rate']['cancelled_attempts'], 0)
        self.assertEqual(analytics['cancellation_rate']['cancellation_rate'], 0)

    def test_cached_analytics_reuses_cached_result_until_cleared(self):
        first = get_cached_admin_analytics()
        self.create_payment(
            PaymentTransaction.STATUS_CAPTURED,
            amount=20000,
            verified_at=timezone.now(),
            suffix='cached',
        )
        second = get_cached_admin_analytics()
        self.assertEqual(first, second)

        clear_admin_analytics_cache()
        third = get_cached_admin_analytics()
        self.assertEqual(third['revenue']['today_paise'], 20000)

    def test_generate_analytics_demo_data_command(self):
        output = StringIO()

        call_command('generate_analytics_demo_data', bookings=25, stdout=output)

        self.assertGreaterEqual(Booking.objects.count(), 25)
        self.assertGreaterEqual(PaymentTransaction.objects.count(), 25)
        self.assertIn('Demo run:', output.getvalue())

    def test_create_demo_admin_command_hashes_password(self):
        output = StringIO()

        call_command(
            'create_demo_admin',
            username='demo_admin_test',
            email='demo@example.com',
            password='DemoAdmin@12345',
            stdout=output,
        )

        user = User.objects.get(username='demo_admin_test')
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password('DemoAdmin@12345'))
        self.assertNotEqual(user.password, 'DemoAdmin@12345')
        self.assertIn('Demo-only credentials', output.getvalue())
