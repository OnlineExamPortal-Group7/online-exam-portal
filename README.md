# Online Exam Portal (Group 7)

Django-based online MCQ exam portal. See the SRS for requirements.

## Project structure
| Folder | Purpose | SRS module |
|---|---|---|
| `config/` | settings (`base`, `dev`, `prod`), root URLs, WSGI | - |
| `apps/accounts/` | custom User + roles, login, RBAC | AuthModule |
| `apps/exams/` | question bank, exams, timer, attempts | ExamsModule |
| `apps/results/` | evaluation, publishing, analytics | ResultsModule |
| `apps/administration/` | audit log, courses, backup | AdminModule |
| `templates/`, `static/` | shared templates and assets | - |

## Setup
```bash
git clone https://github.com/OnlineExamPortal-Group7/online-exam-portal.git
cd online-exam-portal
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```
Open http://127.0.0.1:8000/

## Tests and lint
```bash
python manage.py test
flake8 .
```

## Settings
`manage.py` uses `config.settings.dev` (SQLite). Production uses
`config.settings.prod` (PostgreSQL, TLS settings). Production refuses to start
(`ImproperlyConfigured`) unless `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `POSTGRES_DB`,
`POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_HOST` are set and non-empty. See `.env.example`.
Generate a key with:
`python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"`

## Workflow
Branch from `main` (`feature/issue-N-short-name`), open a pull request that says
`Closes #N`, and get one teammate's review before merging.

## Authentication and roles
- Log in at `/accounts/login/` with e-mail and password. Roles: Student, Instructor, Administrator.
- Protect views with `@role_required(User.Role.INSTRUCTOR)` or `RoleRequiredMixin`
  (`apps/accounts/permissions.py`). Wrong role gives HTTP 403; anonymous users go to login.
- Creating an administrator: `python manage.py createsuperuser` (gets the Administrator role).
- One active session per user (OEP-F-005): logging in on another device or browser signs out
  the previous session. To sign a user out from code, use `end_sessions(user)` in
  `apps/accounts/sessions.py`.
- Question bank and answer keys (OEP-F-014): any page that shows questions, choices or
  `is_correct` outside a student's own running attempt must use `QuestionBankAccessMixin` or
  `@question_bank_required` (`apps/exams/access.py`), and list questions with
  `questions_for(user)`. A test fails if any exams page lets a Student through, unless it is one
  of the attempt pages in `STUDENT_ALLOWED_EXAM_URLS` (`apps/exams/test_question_bank_guard.py`).

## User administration
Administrators manage accounts at `/manage/users/` (OEP-F-004):
- **Create** a user with a role at `/manage/users/new/`.
- **Deactivate / reactivate** an account. A deactivated user cannot log in.
- **Change a role.** The user is signed out and gets the new role on their next login.
- An administrator cannot deactivate their own account or remove their own Administrator role.
- Every route under `/manage/` returns HTTP 403 for Students and Instructors.

Change users through `apps/administration/services.py` (`create_user`, `deactivate`,
`reactivate`, `change_role`), not by editing `User` directly, so these rules and the
audit hook (`audit_hook`, implemented by the audit-log issue #22) always apply.

## Course and enrolment management
Administrators manage courses at `/manage/courses/` (OEP-F-042):
- **Create / edit** a course (code, name, description, instructor) at `/manage/courses/new/`
  and `/manage/courses/<id>/edit/`. Course codes are unique ignoring case. Each course has one
  instructor, chosen from active instructors; changing it also moves the course's question bank
  to the new instructor.
- **Roster** at `/manage/courses/<id>/` lists the enrolled students. Enrol active students
  into an active course, or unenrol a student. Only enrolled students see the course's
  published exams and can start them.
- **Deactivate / reactivate** a course. A deactivated course keeps its enrolments but cannot
  be chosen for new exams or question imports, and no new students can be enrolled.
- Courses are never deleted, because questions and exams refer to them.

Change courses and enrolments through `apps/administration/services.py` (`create_course`,
`update_course`, `set_course_active`, `enrol_students`, `unenrol_student`) so the same rules
and the audit hook apply.

## Result review and publication
Instructors review and publish exam results at `/results/exams/` (OEP-F-031), also linked
from the instructor dashboard:
- **Review** at `/results/exams/<id>/` lists every enrolled student with their attempt status,
  score and percentage ("Not attempted" if none), plus the average. Attempts left in progress
  after their deadline are timed out and scored when the page opens.
- **Publish** results once the exam window has closed. Publishing happens once per exam and
  cannot be undone. Until then students see "Result: Not published yet" on their dashboard;
  afterwards they see their score.
- Only the course's instructor can review or publish. Another instructor gets HTTP 404;
  Students and Administrators get HTTP 403.

For other features, use `apps/results/services.py` rather than querying `Result` directly:
- `published_results_for(student)`: the only query to use when showing scores to a student
  (results history, #19).
- `results_for_exam(exam)` and `is_published(exam)`: all scores of an exam, published or not
  (class analytics, #20).
- `publish_results(exam, actor)`: applies the rules above and calls the audit hook.
- The `results_published` signal (`apps/results/signals.py`) is sent with `exam` and
  `published_by` after a publish is saved (notifications, #25).

## Question import (CSV)
Instructors and administrators import questions in bulk at `/exams/questions/import/`
(OEP-F-011). Instructors can use their own active courses; administrators any active course.
Students get HTTP 403. Download an example file from the import page.

CSV format (UTF-8, header row first, up to 1 MB and 500 questions):

| Column | Rule |
|---|---|
| `course` | course code |
| `topic` | required, up to 100 characters |
| `difficulty` | `easy`, `medium` or `hard` |
| `question` | required |
| `option_1` to `option_6` | 2 to 6 options, filled in order, all different |
| `correct` | number of the one correct option, e.g. `2` |
| `marks` | optional, whole number of at least 1 (default 1) |

The whole file is checked first. If any row has a problem, nothing is imported and every
problem is listed with its row number (the header is row 1). Otherwise all questions are saved
in one transaction, so a fixed file can simply be uploaded again.
