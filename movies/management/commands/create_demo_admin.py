from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = (
        "Create or update a demo administrator account. "
        "The password is securely hashed and never printed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            default="demo_admin",
            help="Username for the demo administrator.",
        )
        parser.add_argument(
            "--email",
            default="demo@example.com",
            help="Email address for the demo administrator.",
        )
        parser.add_argument(
            "--password",
            required=True,
            help="Password for the demo administrator.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        username = options["username"].strip()
        email = options["email"].strip()
        password = options["password"]

        if not username:
            raise CommandError("Username is required.")

        if not email:
            raise CommandError("Email is required.")

        if not password:
            raise CommandError("Password is required.")

        User = get_user_model()

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )

        user.email = email
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True

        # set_password hashes the password before it is stored.
        user.set_password(password)
        user.save(
            update_fields=[
                "email",
                "is_staff",
                "is_superuser",
                "is_active",
                "password",
            ]
        )

        action = "Created" if created else "Updated"

        self.stdout.write(
            self.style.SUCCESS(
                f"{action} demo administrator account: {username}"
            )
        )
        self.stdout.write(
            "The password was securely hashed and was not written to logs."
        )
        self.stdout.write(
            self.style.WARNING(
                "Demo-only credentials. Store and share them securely."
            )
        )