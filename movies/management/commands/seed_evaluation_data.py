from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from movies.models import Genre, Language, Movie, Seat, Theater


SEED_GENRES = [
    "Action",
    "Adventure",
    "Comedy",
    "Drama",
    "Romance",
    "Sci-Fi",
    "Thriller",
]

SEED_LANGUAGES = [
    ("English", "english"),
    ("Hindi", "hindi"),
    ("Tamil", "tamil"),
    ("Telugu", "telugu"),
]

SEED_MOVIES = [
    {
        "name": "Evaluation: Interstellar Dreams",
        "language": "english",
        "genres": ["Sci-Fi", "Drama", "Adventure"],
        "rating": "8.8",
        "cast": "Aarav Mehta, Nisha Rao, Daniel Cooper",
        "description": (
            "A hopeful space adventure about a young engineer racing to save a "
            "colony ship before its final launch window closes."
        ),
        "trailer_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "theater_name": "Evaluation Screen 1",
    },
    {
        "name": "Evaluation: Mumbai Nights",
        "language": "hindi",
        "genres": ["Drama", "Thriller"],
        "rating": "8.1",
        "cast": "Kabir Sethi, Meera Kapoor, Rohan Malhotra",
        "description": (
            "A city thriller following an honest journalist uncovering a ticketing "
            "scam during the busiest festival weekend."
        ),
        "trailer_url": "",
        "theater_name": "Evaluation Screen 2",
    },
    {
        "name": "Evaluation: Comedy Junction",
        "language": "hindi",
        "genres": ["Comedy", "Romance"],
        "rating": "7.6",
        "cast": "Priya Sharma, Dev Anand, Sana Mir",
        "description": (
            "A warm comedy about two rival theater managers forced to organize one "
            "perfect opening night together."
        ),
        "trailer_url": "",
        "theater_name": "Evaluation Screen 3",
    },
    {
        "name": "Evaluation: Southern Quest",
        "language": "tamil",
        "genres": ["Action", "Adventure", "Thriller"],
        "rating": "8.4",
        "cast": "Arjun Varma, Kavya Iyer, Vivek Raman",
        "description": (
            "An action adventure where a rescue pilot and her crew cross dangerous "
            "terrain to bring a stranded village home."
        ),
        "trailer_url": "",
        "theater_name": "Evaluation Screen 4",
    },
]


class Command(BaseCommand):
    help = "Seed minimum usable evaluation data without duplicating existing rows."

    def handle(self, *args, **options):
        summary = {
            "genres_created": 0,
            "genres_reused": 0,
            "languages_created": 0,
            "languages_reused": 0,
            "movies_created": 0,
            "movies_reused": 0,
            "theaters_created": 0,
            "theaters_reused": 0,
            "seats_created": 0,
            "seats_reused": 0,
        }

        with transaction.atomic():
            genres_by_name = {}
            for genre_name in SEED_GENRES:
                genre, created = Genre.objects.get_or_create(
                    slug=slugify(genre_name),
                    defaults={"name": genre_name},
                )
                if not created and genre.name != genre_name:
                    genre.name = genre_name
                    genre.save(update_fields=["name"])
                summary["genres_created" if created else "genres_reused"] += 1
                genres_by_name[genre_name] = genre

            languages_by_code = {}
            for language_name, language_code in SEED_LANGUAGES:
                language, created = Language.objects.update_or_create(
                    code=language_code,
                    defaults={"name": language_name},
                )
                summary["languages_created" if created else "languages_reused"] += 1
                languages_by_code[language_code] = language

            base_show_time = timezone.now() + timedelta(days=3)
            for index, movie_data in enumerate(SEED_MOVIES):
                movie, created = Movie.objects.update_or_create(
                    name=movie_data["name"],
                    defaults={
                        "image": "movies/test.jpg",
                        "rating": movie_data["rating"],
                        "cast": movie_data["cast"],
                        "description": movie_data["description"],
                        "trailer_url": movie_data["trailer_url"],
                        "language": languages_by_code[movie_data["language"]],
                    },
                )
                movie.genres.set(
                    genres_by_name[genre_name]
                    for genre_name in movie_data["genres"]
                )
                summary["movies_created" if created else "movies_reused"] += 1

                theater, theater_created = Theater.objects.update_or_create(
                    movie=movie,
                    name=movie_data["theater_name"],
                    defaults={"time": base_show_time + timedelta(days=index)},
                )
                summary["theaters_created" if theater_created else "theaters_reused"] += 1

                for seat_number in self._seat_numbers():
                    seat, seat_created = Seat.objects.get_or_create(
                        theater=theater,
                        seat_number=seat_number,
                        defaults={"is_booked": False},
                    )
                    summary["seats_created" if seat_created else "seats_reused"] += 1

        self.stdout.write(self.style.SUCCESS("Evaluation data seed complete."))
        self.stdout.write(
            f"Genres: {summary['genres_created']} created, {summary['genres_reused']} reused."
        )
        self.stdout.write(
            f"Languages: {summary['languages_created']} created, {summary['languages_reused']} reused."
        )
        self.stdout.write(
            f"Movies: {summary['movies_created']} created, {summary['movies_reused']} reused."
        )
        self.stdout.write(
            f"Theaters: {summary['theaters_created']} created, {summary['theaters_reused']} reused."
        )
        self.stdout.write(
            f"Seats: {summary['seats_created']} created, {summary['seats_reused']} reused."
        )
        self.stdout.write(
            self.style.WARNING(
                "No completed bookings or payments were created. Seed seats are available when first created."
            )
        )

    def _seat_numbers(self):
        return [f"A{number}" for number in range(1, 11)]
