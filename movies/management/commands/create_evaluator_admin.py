import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from movies.models import (
    Booking,
    BookingEmailNotification,
    Genre,
    Language,
    Movie,
    PaymentTransaction,
    PaymentWebhookEvent,
    Seat,
    SeatReservation,
    Theater,
)


VIEW_ONLY_MODELS = [
    Genre,
    Language,
    Movie,
    Theater,
    Seat,
    SeatReservation,
    Booking,
    PaymentTransaction,
    PaymentWebhookEvent,
    BookingEmailNotification,
]


class Command(BaseCommand):
    help = "Create or update the restricted evaluator admin account."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            default=os.environ.get(
                "EVALUATOR_ADMIN_USERNAME",
                "evaluator_admin",
            ),
            help="Username for the restricted evaluator account.",
        )
        parser.add_argument(
            "--email",
            default=os.environ.get(
                "EVALUATOR_ADMIN_EMAIL",
                "evaluator@example.com",
            ),
            help="Email address for the restricted evaluator account.",
        )
        parser.add_argument(
            "--password",
            default=os.environ.get(
                "EVALUATOR_ADMIN_PASSWORD",
                "BookMySeatEval@2026",
            ),
            help="Password for the restricted evaluator account.",
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
        analytics_group, _ = Group.objects.get_or_create(name="analytics_admin")

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "is_active": True,
                "is_staff": True,
                "is_superuser": False,
            },
        )

        user.email = email
        user.is_active = True
        user.is_staff = True
        user.is_superuser = False
        user.set_password(password)
        user.save(
            update_fields=[
                "email",
                "is_active",
                "is_staff",
                "is_superuser",
                "password",
            ]
        )

        # Keep this dedicated public evaluator account tightly scoped.
        user.groups.set([analytics_group])
        user.user_permissions.clear()
        user.user_permissions.add(*self._view_permissions())

        action = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} restricted evaluator account: {username}"
            )
        )
        self.stdout.write(
            "The evaluator password was hashed and was not printed."
        )
        self.stdout.write(
            "Granted read-only view permissions for project evaluation records."
        )

    def _view_permissions(self):
        permissions = []
        for model in VIEW_ONLY_MODELS:
            content_type = ContentType.objects.get_for_model(model)
            permissions.append(
                Permission.objects.get(
                    content_type=content_type,
                    codename=f"view_{model._meta.model_name}",
                )
            )
        return permissions
