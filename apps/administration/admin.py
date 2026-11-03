
from django.contrib import admin

from .models import AuditLog, Course, Enrollment


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "instructor", "is_active", "created_at")
    search_fields = ("code", "name")
    list_filter = ("is_active",)


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "course", "enrolled_at")
    search_fields = ("student__username", "course__code")
    list_filter = ("course",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "timestamp",
        "actor_name",
        "action",
        "target_type",
        "target_id",
        "target_name",
    )
    search_fields = (
        "actor_name",
        "action",
        "target_type",
        "target_name",
    )
    list_filter = ("action", "target_type", "timestamp")

    readonly_fields = (
        "actor",
        "actor_name",
        "action",
        "target_type",
        "target_id",
        "target_name",
        "details",
        "timestamp",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
