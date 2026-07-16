from django.core.management.base import BaseCommand
from django.db.models import Count

from core.models import SessionSubproject, Sessions


class Command(BaseCommand):
    help = "Report session-subproject allocation migration statistics."

    def handle(self, *args, **options):
        mode_counts = dict(
            Sessions.objects.values_list('allocation_mode')
            .annotate(total=Count('id'))
            .order_by()
        )

        self.stdout.write(f"Total link rows: {SessionSubproject.objects.count()}")
        self.stdout.write(
            "Links with allocation_bp != 10000: "
            f"{SessionSubproject.objects.exclude(allocation_bp=10000).count()}"
        )
        self.stdout.write("Sessions by allocation_mode:")
        for mode, _label in Sessions._meta.get_field('allocation_mode').choices:
            self.stdout.write(f"  {mode}: {mode_counts.get(mode, 0)}")
        self.stdout.write(
            "Sessions with >1 link: "
            f"{Sessions.objects.annotate(link_count=Count('subproject_links')).filter(link_count__gt=1).count()}"
        )
