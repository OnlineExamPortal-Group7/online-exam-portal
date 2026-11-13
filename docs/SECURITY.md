# Application Security Configuration

## 1. Overview

The Online Exam Portal uses Django's built-in security features to protect authentication, user sessions, examination submissions and application access.

The project maintains separate development and production settings:

- Development: `config.settings.dev`
- Production: `config.settings.prod`
- Shared configuration: `config/settings/base.py`

Production security settings must be configured through environment variables. Sensitive credentials must never be committed to the repository.

## 2. HTTPS and TLS Configuration

Production settings enforce HTTPS using Django security settings.

The following configuration is implemented in `config/settings/prod.py`:

```python
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
```

### Configuration details

| Setting | Purpose |
|---|---|
| `SECURE_PROXY_SSL_HEADER` | Identifies HTTPS requests forwarded by the trusted reverse proxy. |
| `SECURE_SSL_REDIRECT` | Redirects HTTP requests to HTTPS. |
| `SESSION_COOKIE_SECURE` | Sends session cookies only over HTTPS. |
| `CSRF_COOKIE_SECURE` | Sends CSRF cookies only over HTTPS. |
| `SECURE_HSTS_SECONDS` | Enables HTTP Strict Transport Security for one year. |

### Deployment requirements

The production deployment must:

1. Configure a valid TLS certificate for the application domain.
2. Configure the reverse proxy (such as Nginx) to terminate TLS.
3. Redirect HTTP traffic to HTTPS at the proxy.
4. Forward the `X-Forwarded-Proto` header correctly.
5. Ensure the application is accessible through the trusted proxy configuration.

The reverse proxy must overwrite untrusted incoming forwarded-protocol headers rather than accepting client-supplied values.

**Note:** The Django configuration is implemented, but actual TLS certificate installation and deployment verification depend on the production hosting environment.

## 3. CSRF Protection

Cross-Site Request Forgery (CSRF) protection is enabled using Django's built-in middleware.

The following middleware is configured in `config/settings/base.py`:

```python
"django.middleware.csrf.CsrfViewMiddleware"
```

### CSRF implementation

- POST forms include Django CSRF tokens.
- Authentication and form submissions use Django's CSRF protection.
- Exam answer autosave requests send the CSRF token through the `X-CSRFToken` request header.
- CSRF validation is enforced for protected POST requests.

The exam autosave JavaScript obtains the CSRF token from the form and includes it in its requests.

### Verification

CSRF protection is tested using Django's test client with CSRF enforcement enabled.

The tests verify that:

- Requests without a valid CSRF token are rejected.
- Requests with a valid CSRF token are accepted.

## 4. Session and Cookie Security

Production settings enable secure session and CSRF cookies.

```python
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

These settings ensure that the corresponding cookies are transmitted only over HTTPS.

The project also uses Django's session middleware and authentication middleware.

## 5. HSTS Configuration

HTTP Strict Transport Security (HSTS) instructs browsers to access the application through HTTPS.

The production configuration enables HSTS for one year:

```python
SECURE_HSTS_SECONDS = 31536000
```

The following settings are not currently enabled:

The following settings are not explicitly enabled in the production
configuration. Their Django defaults are False:

- `SECURE_HSTS_INCLUDE_SUBDOMAINS`
- `SECURE_HSTS_PRELOAD`

These settings must only be enabled after confirming that all relevant subdomains support HTTPS and that the domain satisfies the browser preload requirements.

Django deployment checks currently report warnings for these two settings. They are documented as deployment-dependent decisions rather than enabled without verification.

## 6. Production Environment Variables

Production configuration requires the following environment variables:

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Django secret key |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated allowed hostnames |
| `POSTGRES_DB` | PostgreSQL database name |
| `POSTGRES_USER` | PostgreSQL username |
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `POSTGRES_HOST` | PostgreSQL server hostname |
| `POSTGRES_PORT` | PostgreSQL port; defaults to 5432 |

The production application uses `require_env()` to reject missing or blank mandatory values.

The `DJANGO_ALLOWED_HOSTS` configuration is also validated to ensure that at least one usable hostname is provided.

Refer to `.env.example` for the environment variable names and configuration format.

**Security requirements:**

- Use a strong, randomly generated production secret key.
- Do not commit actual `.env` files or credentials.
- Do not expose database passwords or secret keys in source code.
- Store production credentials securely in the deployment environment.

## 7. Authentication and Password Security

The application uses Django authentication and password validation.

The following password validators are configured:

- User attribute similarity validation.
- Minimum password length validation.
- Common password validation.
- Numeric password validation.

The project also implements a custom email/username authentication backend and account lockout functionality.

The default Django PBKDF2 password hasher is retained.

## 8. Security Middleware

The following Django middleware components are enabled:

| Middleware | Purpose |
|---|---|
| SecurityMiddleware | Provides Django security-related response handling. |
| SessionMiddleware | Manages user sessions. |
| CommonMiddleware | Provides common HTTP processing. |
| CsrfViewMiddleware | Protects against CSRF attacks. |
| AuthenticationMiddleware | Associates requests with authenticated users. |
| MessageMiddleware | Manages application messages. |
| XFrameOptionsMiddleware | Provides clickjacking protection through frame headers. |

## 9. Security Verification

The following checks were performed during implementation.

| Verification | Result |
|---|---|
| Complete Django test suite | 419 tests passed |
| Flake8 | Passed |
| Django development system check | Passed |
| Migration check | No changes detected |
| Git diff check | No whitespace errors |
| Production deployment check | Two HSTS warnings |
| CSRF enforcement test | Verified |
| Template inline-code scan | No inline scripts, styles or event handlers detected |

### Commands used for verification

Run the complete test suite:

```bash
python manage.py test --settings=config.settings.dev
```

Run code quality checks:

```bash
flake8 .
```

Run Django system checks:

```bash
python manage.py check --settings=config.settings.dev
```

Check for model changes:

```bash
python manage.py makemigrations --check --dry-run --settings=config.settings.dev
```

Run production deployment checks with valid temporary audit configuration:

```bash
python manage.py check --deploy --settings=config.settings.prod
```

The production deployment check currently reports warnings for HSTS subdomain inclusion and preload. These require confirmation of the production domain and HTTPS readiness before enabling.

## 10. Deployment Checklist

Before deploying the application to production:

- [ ] Configure a valid TLS certificate.
- [ ] Configure HTTPS redirection at the reverse proxy.
- [ ] Verify trusted proxy header handling.
- [ ] Configure all required production environment variables.
- [ ] Verify PostgreSQL connectivity.
- [ ] Confirm that production `DEBUG` is disabled.
- [ ] Verify allowed hostnames.
- [ ] Verify secure session and CSRF cookies.
- [ ] Confirm that CSRF protection works through the production domain.
- [ ] Review HSTS subdomain and preload requirements.
- [ ] Verify production deployment security checks.
- [ ] Use a shared cache if deploying multiple application workers and requiring consistent login lockout enforcement.

## 11. Important Security Notes

- Never commit production credentials or secret keys.
- Never use development settings for production deployment.
- Do not disable CSRF middleware to resolve request validation errors.
- Enable HSTS subdomain and preload settings only after verifying domain readiness.
- Review security configuration whenever deployment infrastructure changes.

---

**Project:** Online Exam Portal – Group 7
**Security scope:** HTTPS/TLS
configuration, CSRF protection and security documentation
**Django settings:** `config.settings.base` and `config.settings.prod`