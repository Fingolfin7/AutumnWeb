import json

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from core.importer import iter_import
from core.models import Context
from core.utils import json_decompress


# usage:  python manage.py import 'username' project_file.json --force/--merge --tolerance 0.5
# e.g.: python manage.py import kuda "C:\\path\\to\\projects.json" --merge --tolerance 2


class Command(BaseCommand):
    help = 'Import data from projects.json'

    def add_arguments(self, parser):
        parser.add_argument(
            'username', type=str, help='Username of the user to import the data for'
        )
        parser.add_argument(
            'filepath', type=str, help='Path to an Autumn project json file'
        )
        parser.add_argument(
            '--autumn_import',
            action='store_true',
            help='Import data in Autumn (CLI version) format',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force import even if projects already exist',
        )
        parser.add_argument(
            '--merge',
            action='store_true',
            help='Merge sessions and subprojects into existing projects',
        )
        parser.add_argument(
            '--tolerance',
            type=float,
            default=0.5,
            help=(
                'Tolerance for total time mismatch in minutes due to rounding '
                'errors (default 0.5)'
            ),
        )
        parser.add_argument(
            '--verbose', action='store_true', help='Print verbose output'
        )
        parser.add_argument(
            '--context',
            type=str,
            default=None,
            help=(
                'Import all projects under this context name (overrides any '
                'Context field inside the file). If the context does not exist, '
                'import will fail unless --create-context is provided.'
            ),
        )
        parser.add_argument(
            '--create-context',
            action='store_true',
            help=(
                'If used with --context, create the context if it does not '
                'already exist.'
            ),
        )

    def handle(self, *args, **options):
        filepath = options['filepath']

        try:
            user = User.objects.get(username=options['username'])
        except User.DoesNotExist:
            raise CommandError(f'User not found: {options["username"]}')

        import_into_context_name = (options.get('context') or '').strip() or None
        import_into_context = None
        if import_into_context_name:
            import_into_context = Context.objects.filter(
                user=user, name=import_into_context_name
            ).first()
            if not import_into_context and options.get('create_context'):
                import_into_context = Context.objects.create(
                    user=user, name=import_into_context_name
                )
            if not import_into_context:
                raise CommandError(
                    f"Context not found: '{import_into_context_name}'. "
                    f"Create it first or pass --create-context."
                )

        self.stdout.write(f'Reading data from {filepath}...')
        try:
            with open(filepath) as import_file:
                try:
                    data = json_decompress(import_file.read())
                except RuntimeError:
                    data = json.load(import_file)
        except FileNotFoundError:
            raise CommandError(f'File not found: {filepath}')
        except json.JSONDecodeError:
            raise CommandError(f'Invalid JSON file: {filepath}')

        generator = iter_import(
            user,
            data,
            force=options['force'],
            merge=options['merge'],
            tolerance=options['tolerance'],
            verbose=options['verbose'],
            autumn_import=options['autumn_import'],
            import_into_context=import_into_context,
        )
        mismatch_error = None
        while True:
            try:
                message = next(generator)
            except StopIteration as stop:
                summary = stop.value
                break
            self.stdout.write(message)
            if message.startswith('Error: Total time mismatch'):
                mismatch_error = message.removeprefix('Error: ')

        if mismatch_error:
            raise CommandError(mismatch_error)

        self.stdout.write(
            self.style.SUCCESS(
                'Import summary: '
                f"{summary['projects_created']} projects created, "
                f"{summary['projects_updated']} projects updated, "
                f"{summary['sessions_imported']} sessions imported."
            )
        )
        if summary['skipped']:
            self.stdout.write(
                self.style.WARNING(
                    'Skipped existing projects: ' + ', '.join(summary['skipped'])
                )
            )
