from datetime import timedelta
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from .models import Booking, Movie, Seat, SeatReservation, Theater
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

    def test_confirm_active_reservation_creates_booking(self):
        self.reserve_seat()
        reservation = SeatReservation.objects.get(seat=self.seat_a1)

        response = self.client.post(
            reverse('reservation_confirm', args=[reservation.reservation_token])
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Booking.objects.count(), 1)
        self.seat_a1.refresh_from_db()
        reservation.refresh_from_db()
        self.assertTrue(self.seat_a1.is_booked)
        self.assertEqual(reservation.status, SeatReservation.STATUS_CONFIRMED)
        self.assertIsNotNone(reservation.confirmed_at)

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
