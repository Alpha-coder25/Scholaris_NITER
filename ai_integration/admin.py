from django.contrib import admin

from .models import AIUsageLog, StudentTopicPerformance


@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
    list_display = ("feature", "status", "model_used", "latency_ms", "input_tokens", "output_tokens", "created_at")
    list_filter = ("feature", "status", "created_at")
    readonly_fields = ("created_at",)


@admin.register(StudentTopicPerformance)
class StudentTopicPerformanceAdmin(admin.ModelAdmin):
    list_display = ("student", "course_offering", "topic", "accuracy_pct", "strength_level", "last_analyzed")
    list_filter = ("strength_level", "course_offering")
    search_fields = ("student__first_name", "student__last_name", "student__username", "topic")
