from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from core.models import Projects


class Command(BaseCommand):
    help = 'Clear all project data from the database. Optionally specify a user by username to clear only their data.'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, help='Username of the user to import the data for')

    def handle(self, *args, **options):
        if options['username']:
            # check if the user exists
            try:
                user = User.objects.get(username=options['username'])
                self.stdout.write(f'Clearing all project data for user: {user.username}...')
                Projects.objects.filter(user=user).delete()
            except User.DoesNotExist:
                raise CommandError(f'User not found: {options["username"]}')
        else:
            self.stdout.write('Clearing project data for all users...')
            Projects.objects.all().delete()

        self.stdout.write(self.style.SUCCESS('All data has been cleared'))