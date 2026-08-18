"""
Management command to refresh student topic performance cache.

Usage:
    # Refresh all offerings
    python manage.py refresh_topic_cache

    # Refresh a specific offering
    python manage.py refresh_topic_cache --offering <id>

    # Refresh a specific student in an offering
    python manage.py refresh_topic_cache --offering <id> --student <id>
"""
from django.core.management.base import BaseCommand, CommandError

from academics.models import CourseOffering
from ai_integration.services import refresh_student_topic_performance


class Command(BaseCommand):
    help = "Refresh cached student topic performance records for course offerings."

    def add_arguments(self, parser):
        parser.add_argument(
            "--offering",
            type=int,
            help="Course offering ID to refresh (all offerings if omitted)",
        )
        parser.add_argument(
            "--student",
            type=int,
            help="Student user ID to refresh (all students in offering if omitted)",
        )

    def handle(self, *args, **options):
        from accounts.models import User

        offering_id = options.get("offering")
        student_id = options.get("student")

        if offering_id:
            try:
                offering = CourseOffering.objects.select_related("course").get(pk=offering_id)
            except CourseOffering.DoesNotExist:
                raise CommandError(f"Course offering {offering_id} does not exist.")
            offerings = [offering]
        else:
            offerings = CourseOffering.objects.select_related("course").all()

        student = None
        if student_id:
            try:
                student = User.objects.get(pk=student_id, role="student")
            except User.DoesNotExist:
                raise CommandError(f"Student {student_id} does not exist.")

        total_refreshed = 0
        for offering in offerings:
            count = refresh_student_topic_performance(offering, student=student)
            total_refreshed += count
            self.stdout.write(
                self.style.SUCCESS(
                    f"Refreshed {count} student(s) for {offering.course.code}"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(f"\nTotal: {total_refreshed} student(s) refreshed.")
        )
