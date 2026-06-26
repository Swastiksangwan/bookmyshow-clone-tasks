from django.test import TestCase
from django.urls import reverse

from .models import Movie
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
