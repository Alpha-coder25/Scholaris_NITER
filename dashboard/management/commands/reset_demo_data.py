"""Reset the demo database to a pristine, freshly-seeded state.

Deletes ALL data (users, attempts, signups, ratings, …) then re-runs the demo
seed. Intended for the shared hackathon demo DB — run with --yes to skip the
confirmation prompt (e.g. in CI or before a live demo).

Usage:
    python manage.py reset_demo_data          # interactive confirmation
    python manage.py reset_demo_data --yes    # non-interactive
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Flush the database and reseed pristine demo data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes", action="store_true", help="Skip the confirmation prompt."
        )

    def handle(self, *args, **options):
        if not options["yes"]:
            answer = input(
                "This deletes ALL data in the current database. Type 'yes' to continue: "
            )
            if answer.strip().lower() != "yes":
                self.stdout.write(self.style.WARNING("Aborted — no changes made."))
                return        call_command("flush", interactive=False, verbosity=1)
        call_command("seed_demo_data", verbosity=1)
        self.stdout.write(self.style.SUCCESS(
            "Demo database reset to pristine seed state. "
            "Seeded account passwords were printed by seed_demo_data above — "
            "there are no published demo credentials."
        ))
