from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Create or update a demo-only superuser for local testing.'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='demo_admin')
        parser.add_argument('--email', default='demo@example.com')
        parser.add_argument('--password', required=True)

    def handle(self, *args, **options):
        username = options['username']
        email = options['email']
        password = options['password']

        if not username or not email or not password:
            raise CommandError('Username, email, and password are required.')

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'email': email,
                'is_staff': True,
                'is_superuser': True,
                'is_active': True,
            },
        )
        user.email = email
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(password)
        user.save()

        action = 'Created' if created else 'Updated'
        self.stdout.write(self.style.SUCCESS(f'{action} demo admin user: {username}'))
        self.stdout.write(self.style.SUCCESS(f'Demo admin username: {username}'))
        self.stdout.write(self.style.WARNING(f'Demo admin password: {password}'))
        self.stdout.write(
            self.style.WARNING(
                'Demo-only credentials. Do not use this password in production.'
            )
        )
