
from django.core.management.base import BaseCommand

from apps.notifications.services import process_pending_notifications


class Command(BaseCommand):
    help = "Process pending examination email notifications."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Maximum number of notifications to process.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]

        if batch_size <= 0:
            self.stderr.write(
                self.style.ERROR("Batch size must be greater than zero.")
            )
            return

        sent_count = process_pending_notifications(
            batch_size=batch_size
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully sent {sent_count} email notification(s)."
            )
        )
