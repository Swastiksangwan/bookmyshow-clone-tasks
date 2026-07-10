import random
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from movies.models import Genre, Language, Movie


DEMO_GENRES = [
    "Action",
    "Drama",
    "Comedy",
    "Thriller",
    "Romance",
    "Sci-Fi",
    "Horror",
    "Adventure",
    "Animation",
    "Documentary",
]

DEMO_LANGUAGES = [
    "Hindi",
    "English",
    "Tamil",
    "Telugu",
    "Malayalam",
    "Kannada",
    "Marathi",
    "Bengali",
]


class Command(BaseCommand):
    help = 'Create demo/test movie catalog data for genre and language filtering.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--movies',
            type=int,
            default=5000,
            help='Number of demo movies to create.',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Bulk operation batch size.',
        )

    def handle(self, *args, **options):
        movie_count = options['movies']
        batch_size = options['batch_size']
        if movie_count <= 0:
            raise CommandError('--movies must be greater than 0.')
        if batch_size <= 0:
            raise CommandError('--batch-size must be greater than 0.')

        self.stdout.write(
            self.style.WARNING(
                'Creating demo catalog data only. Do not run this against production data.'
            )
        )

        run_id = uuid.uuid4().hex[:8]
        run_prefix = f'Catalog Demo {run_id}'

        with transaction.atomic():
            genres = []
            for genre_name in DEMO_GENRES:
                genre, _ = Genre.objects.get_or_create(
                    slug=slugify(genre_name),
                    defaults={'name': genre_name},
                )
                genres.append(genre)

            languages = []
            for language_name in DEMO_LANGUAGES:
                language, _ = Language.objects.get_or_create(
                    code=slugify(language_name),
                    defaults={'name': language_name},
                )
                languages.append(language)

            movie_objects = []
            for index in range(movie_count):
                language = languages[index % len(languages)]
                rating = 5 + (index % 50) / 10
                movie_objects.append(
                    Movie(
                        name=f'{run_prefix} Movie {index + 1}',
                        image='movies/test.jpg',
                        rating=f'{rating:.1f}',
                        cast='Demo Actor One, Demo Actor Two',
                        description='Demo movie for genre and language filtering.',
                        language=language,
                    )
                )
            Movie.objects.bulk_create(movie_objects, batch_size=batch_size)

            created_movies = list(
                Movie.objects.filter(name__startswith=run_prefix).order_by('id')
            )
            through_model = Movie.genres.through
            through_objects = []
            for index, movie in enumerate(created_movies):
                genre_count = (index % 3) + 1
                start_index = index % len(genres)
                movie_genres = [
                    genres[(start_index + offset) % len(genres)]
                    for offset in range(genre_count)
                ]
                random.shuffle(movie_genres)
                for genre in movie_genres:
                    through_objects.append(
                        through_model(movie_id=movie.id, genre_id=genre.id)
                    )
            through_model.objects.bulk_create(through_objects, batch_size=batch_size)

        self.stdout.write(self.style.SUCCESS(f'Demo run: {run_prefix}'))
        self.stdout.write(self.style.SUCCESS(f'Genres available: {len(genres)}'))
        self.stdout.write(self.style.SUCCESS(f'Languages available: {len(languages)}'))
        self.stdout.write(self.style.SUCCESS(f'Movies created: {len(created_movies)}'))
        self.stdout.write(self.style.SUCCESS(f'Genre links created: {len(through_objects)}'))
