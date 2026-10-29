"""Who may see question-bank data and answer keys (OEP-F-014, OEP-SR-003).

Any page that shows questions, choices or `is_correct` outside a student's own
running attempt must use `question_bank_required` (function views) or
`QuestionBankAccessMixin` (class-based views). Students get HTTP 403 and
anonymous users are sent to the login page.
"""
from apps.accounts.models import User
from apps.accounts.permissions import RoleRequiredMixin, role_required

from .models import Question

QUESTION_BANK_ROLES = (User.Role.INSTRUCTOR, User.Role.ADMINISTRATOR)

question_bank_required = role_required(*QUESTION_BANK_ROLES)


class QuestionBankAccessMixin(RoleRequiredMixin):
    allowed_roles = QUESTION_BANK_ROLES


def questions_for(user):
    """Question-bank questions the user may see.

    Instructors see their own courses' questions, administrators see all, anyone else none.
    """
    if not (user.is_authenticated and user.is_active):
        return Question.objects.none()
    if user.role == User.Role.ADMINISTRATOR:
        return Question.objects.all()
    if user.role == User.Role.INSTRUCTOR:
        return Question.objects.filter(course__instructor=user)
    return Question.objects.none()
