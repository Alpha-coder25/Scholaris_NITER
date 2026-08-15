from django.contrib import admin

from .models import Exam, ExamAnswer, ExamAttempt, ExamQuestion, Question


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("type", "text", "course_offering", "source", "status")
    list_filter = ("type", "source", "status")


class ExamQuestionInline(admin.TabularInline):
    model = ExamQuestion
    extra = 0


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("title", "course_offering", "total_duration_seconds", "start_time")
    inlines = [ExamQuestionInline]


@admin.register(ExamAttempt)
class ExamAttemptAdmin(admin.ModelAdmin):
    list_display = ("student", "exam", "started_at", "status")


@admin.register(ExamAnswer)
class ExamAnswerAdmin(admin.ModelAdmin):
    list_display = ("attempt", "exam_question", "auto_score", "manual_score", "locked")
