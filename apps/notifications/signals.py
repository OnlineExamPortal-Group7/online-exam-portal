
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.exams.models import Exam
from apps.results.signals import results_published

from .services import (
    queue_exam_scheduled_notifications,
    queue_results_published_notifications,
)


@receiver(pre_save, sender=Exam)
def remember_previous_exam_status(sender, instance, **kwargs):
    """Remember the exam status before it is saved."""
    if instance.pk:
        instance._previous_status = (
            sender.objects.filter(pk=instance.pk)
            .values_list("status", flat=True)
            .first()
        )
    else:
        instance._previous_status = None


@receiver(post_save, sender=Exam)
def queue_exam_notifications_on_publish(
    sender,
    instance,
    created,
    **kwargs,
):
    """Queue exam emails when an exam first becomes published."""
    previous_status = getattr(instance, "_previous_status", None)

    if (
        instance.status == Exam.Status.PUBLISHED
        and previous_status != Exam.Status.PUBLISHED
    ):
        exam_id = instance.pk

        transaction.on_commit(
            lambda: _queue_exam_notifications(exam_id)
        )


def _queue_exam_notifications(exam_id):
    """Queue notifications after the exam transaction commits."""
    exam = Exam.objects.get(pk=exam_id)
    queue_exam_scheduled_notifications(exam)


@receiver(results_published)
def queue_result_notifications(sender, exam, published_by, **kwargs):
    """Queue result emails after results are published."""
    queue_results_published_notifications(exam)
