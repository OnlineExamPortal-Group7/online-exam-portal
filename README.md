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
`config.settings.prod` (PostgreSQL, TLS settings); copy `.env.example` for variables.

## Workflow
Branch from `main` (`feature/issue-N-short-name`), open a pull request that says
`Closes #N`, and get one teammate's review before merging.
