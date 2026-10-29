# Admin registrations are added by later issues.

from django.contrib import admin
from .models import (
    Answer,
    Choice,
    Exam,
    ExamAttempt,
    ExamQuestion,
    Question,
)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "course", "question_type", "difficulty", "marks")
    search_fields = ("text", "course__name")
    list_filter = ("course", "difficulty", "question_type")


@admin.register(Choice)
class ChoiceAdmin(admin.ModelAdmin):
    list_display = ("id", "question", "is_correct")
    search_fields = ("text",)


class ExamQuestionInline(admin.TabularInline):
    model = ExamQuestion
    extra = 1


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "start_time", "end_time", "status")
    search_fields = ("title", "course__name")
    list_filter = ("status", "course")
    inlines = [ExamQuestionInline]


@admin.register(ExamAttempt)
class ExamAttemptAdmin(admin.ModelAdmin):
    list_display = ("id", "exam", "student", "status", "started_at")
    list_filter = ("status", "exam")
    search_fields = ("student__username", "exam__title")


@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
    list_display = ("attempt", "question", "selected_choice", "saved_at")
