from django.core.management.base import BaseCommand, CommandError
from core.models import Projects, SubProjects, Sessions


class Command(BaseCommand):
    help = 'Clear all data from the database'

    def handle(self, *args, **options):
        self.stdout.write('Clearing all data...')
        Projects.objects.all().delete()
        self.stdout.write(self.style.SUCCESS('All data has been cleared'))