# Online Exam Portal

An online examination management system built using Django. The application allows administrators and faculty to manage users, courses, examinations, and questions, while students can attempt exams and view their results.

## Project Structure

```text
online-exam-portal/
│
├── apps/
│   ├── accounts/
│   ├── administration/
│   ├── exams/
│   └── results/
│
├── config/
│   ├── settings/
│   │   ├── dev.py
│   │   └── prod.py
│   └── urls.py
│
├── docs/
│   └── database-backup-restore.md
│
├── manage.py
├── requirements.txt
├── README.md
└── db.sqlite3
```

## Technologies Used

- Python
- Django
- SQLite (development database)
- PostgreSQL (production database)
- HTML, CSS and JavaScript
- Git and GitHub
- Flake8 for code quality

## Prerequisites

Install the following before running the project:

- Python 3
- pip
- Git
- Visual Studio Code (recommended)

## Installation and Setup

### 1. Clone the repository

```bash
git clone https://github.com/OnlineExamPortal-Group7/online-exam-portal.git
```

### 2. Navigate to the project directory

```bash
cd online-exam-portal
```

### 3. Create a virtual environment

```bash
python -m venv venv
```

### 4. Activate the virtual environment

**Windows PowerShell:**

```powershell
.\venv\Scripts\Activate.ps1
```

### 5. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 6. Apply database migrations

```bash
python manage.py migrate --settings=config.settings.dev
```

### 7. Create a superuser

```bash
python manage.py createsuperuser --settings=config.settings.dev
```

### 8. Start the development server

```bash
python manage.py runserver --settings=config.settings.dev
```

Open the application at:

http://127.0.0.1:8000/

## Application Features

### Authentication and Roles

- User authentication and login.
- Role-based access control.
- Password reset functionality.
- Account lockout security.
- Separate access permissions for different user roles.

### User Administration

- Manage application users.
- Maintain user information and account details.
- Control access based on assigned roles.

### Course and Enrolment Management

- Create and manage courses.
- Enrol students in courses.
- Maintain course and student enrolment information.

### Examination Management

- Create and manage examinations.
- Add questions and choices.
- Randomise examination questions.
- Configure examination duration.
- Support student examination attempts.

### Student Examination Interface

- Display examination questions.
- Navigate between questions.
- Select and save answers.
- Track examination time.
- Support manual submission.
- Automatically submit examinations when the time expires.

### Evaluation and Results

- Automatically evaluate multiple-choice questions.
- Calculate marks based on correct answers.
- Assign zero marks for incorrect or unanswered questions.
- Store examination results.
- Calculate the percentage score.

### Question Import (CSV)

The application supports importing examination questions using CSV files.

- The uploaded file is validated before importing.
- Validation errors are reported with their corresponding row numbers.
- If any row contains an error, the import is cancelled.
- Valid questions are saved in a single database transaction.

## Database Configuration

The project supports separate development and production settings.

| Environment | Database |
|---|---|
| Development | SQLite |
| Production | PostgreSQL |

Development commands use:

```bash
--settings=config.settings.dev
```

Production commands use:

```bash
--settings=config.settings.prod
```

Configure the required environment variables and database credentials before running the production configuration.

## Database Backup and Restoration

The procedures for backing up, validating, and restoring the development SQLite database and production PostgreSQL database are documented here:

[Database Backup and Restore Procedures](docs/database-backup-restore.md)

**Important:** Database backups may contain sensitive user and examination information. Do not commit database backup files or credentials to GitHub.

## Running Tests

Run the complete test suite:

```bash
python manage.py test
```

Run Django system checks:

```bash
python manage.py check
```

Run tests for the examinations application:

```bash
python manage.py test apps.exams
```

## Code Quality and Linting

Install Flake8 if it is not already installed:

```bash
python -m pip install flake8
```

Run Flake8 across the project:

```bash
python -m flake8 .
```

## Git Workflow

The project follows a feature-branch workflow.

### 1. Update the main branch

```bash
git checkout main
git pull origin main
```

### 2. Create a feature branch

```bash
git checkout -b feature/your-issue-description
```

### 3. Stage and commit changes

```bash
git add .
git commit -m "Describe your changes"
```

### 4. Push the feature branch

```bash
git push -u origin feature/your-issue-description
```

### 5. Create a Pull Request

- Open the repository on GitHub.
- Create a Pull Request from your feature branch into `main`.
- Provide a meaningful title and description.
- Link the related GitHub issue.
- Wait for review and required checks before merging.

## Contribution Guidelines

- Work on a separate feature branch for each issue.
- Follow the existing project structure and coding conventions.
- Test changes before creating a Pull Request.
- Run Django checks and Flake8 before submitting.
- Do not commit virtual environments, database backups, credentials, or unnecessary generated files.
- Keep commits meaningful and focused.

## Project Team

**Online Exam Portal – Group 7**

Developed as a collaborative academic project.

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
