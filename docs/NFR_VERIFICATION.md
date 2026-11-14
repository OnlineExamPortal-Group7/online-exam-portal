# Non-Functional Requirements Verification Report



**Project:** Online Exam Portal – Group 7

**Issue:** #27 – Verify non-functional requirements

**Assessment Date:** 14 November 2026



## 1. Objective



This report documents the verification of the application's non-functional requirements (NFRs), including measured performance results, implemented security controls, identified gaps and requirements that remain unverified.



No performance thresholds or availability targets have been assumed where the project documentation does not specify them.



## 2. Summary of Verification Results



| NFR | Findings | Status |

|---|---|---|

| Answer-save latency | 100 local autosave requests benchmarked | Measured |

| Data protection | Security controls and CSRF tests documented | Implemented and partially verified |

| HTTPS/TLS | Production configuration exists; deployment not tested | Unverified in production |

| Database backup and recovery | SQLite backup and restoration tested | Locally verified |

| PostgreSQL recovery | Procedure documented but not executed | Unverified |

| Availability and uptime | No measurable target or production monitoring evidence found | Unverified |

| Data retention | No defined retention period or automated cleanup job found | Gap identified |

| WCAG 2.1 AA accessibility | Template, CSS and JavaScript inspection performed | Partially inspected |

| 200-student concurrency | No load test performed | Unverified |



## 3. Answer-Save Latency



### 3.1 Test Methodology



A separate diagnostic benchmark was created:



`apps/exams/autosave_latency_benchmark.py`



The benchmark:

- Creates a test student and an active examination attempt.

- Sends one warm-up autosave request.

- Measures 100 subsequent autosave requests.

- Calculates average, median, 95th percentile (P95) and maximum response time.

- Verifies that all measured requests return HTTP 200 with successful save acknowledgements.



Command executed:



```bash

python manage.py test apps.exams.autosave_latency_benchmark --settings=config.settings.dev -v 2

```



### 3.2 Measured Results



| Metric | Measured Result |

|---|---:|

| Requests measured | 100 |

| Average latency | 2.908 ms |

| Median latency | 2.635 ms |

| P95 latency | 4.338 ms |

| Maximum latency | 9.991 ms |

| Test execution time | 1.388 seconds |

| Benchmark test | Passed |



### 3.3 Test Environment and Limitations



- Django test client.

- In-memory SQLite test database.

- Local application execution.

- No real network or external client latency.

- No production database or deployment infrastructure.



These measurements represent local application-level test-client performance. They must not be interpreted as production response times or network latency.



No formal answer-save latency threshold was found in the repository. Therefore, the measurements are recorded without claiming that a specified NFR threshold has been met.



## 4. Data Protection and Security



The existing security documentation is available at:



`docs/SECURITY.md`



The project implements the following controls:



- Django CSRF middleware.

- CSRF tokens in protected POST requests.

- Secure session and CSRF cookies in production settings.

- HTTPS redirection and HSTS configuration in production settings.

- Environment-based production secret and database configuration.

- Password validation and Django password hashing.

- Authentication and session middleware.

- Clickjacking protection through XFrameOptionsMiddleware.



### Verification Evidence



The existing security documentation records:



- Requests without valid CSRF tokens are rejected.

- Requests with valid CSRF tokens are accepted.

- 419 application tests passed during the security implementation.

- Flake8 and Django development checks passed.



### Limitations



Actual production TLS certificate installation and HTTPS deployment verification have not been performed.



The production deployment check also reports HSTS subdomain and preload warnings. These remain deployment-dependent decisions.



**Assessment:** Security controls are implemented, with documented test evidence. Production deployment security remains unverified.



## 5. Database Backup and Recovery

The project includes a backup and restoration procedure documented in:

`docs/database-backup-restore.md`

### Verification Evidence

The SQLite backup and restoration procedure was tested locally.

- Original database integrity check returned `ok`.
- Restored database integrity check returned `ok`.
- Both databases contained 20 tables.
- Table names matched between the original and restored databases.
- Record counts matched across 19 application tables.

### Limitations

- PostgreSQL backup and restoration were not executed.
- No row-by-row comparison of all restored records was performed.
- A formal backup retention duration has not been established.

**Assessment:** SQLite backup and restoration were locally verified. PostgreSQL recovery remains unverified.

## 6. Availability and Uptime

No measurable availability or uptime target was identified in the repository.

No production deployment or monitoring evidence was available to verify service availability over time.

**Assessment:** Availability and uptime requirements remain unverified. A measurable uptime target and production monitoring are required.

## 7. Data Retention

The application includes examination-attempt timeout handling.

However, inspection of the application did not identify:

- A formally defined data retention period.
- An automated cleanup or purge mechanism for expired records.
- A documented archival and deletion policy.

**Assessment:** Data retention is a gap requiring a defined retention policy and an appropriate implementation.

## 8. WCAG 2.1 AA Accessibility

A preliminary inspection of templates, CSS and JavaScript was performed.

### Positive Findings

- Semantic HTML elements are used for page structure.
- Form labels are associated with input controls.
- Examination navigation includes accessible labels.
- Autosave status uses `role="status"` and `aria-live`.
- Timeout notifications use alert semantics.
- The examination timer uses timer semantics.

### Limitations

The following checks were not performed:

- Complete keyboard-only navigation testing.
- Screen-reader compatibility testing.
- Colour contrast measurements.
- Browser zoom and responsive accessibility testing.
- Automated WCAG accessibility scanning.
- Full WCAG 2.1 AA conformance assessment.

**Assessment:** Preliminary accessibility inspection was performed, but WCAG 2.1 AA compliance has not been established.

## 9. Concurrent Student Capacity

The project requirement specifies support for 200 concurrent students.

The autosave implementation includes safeguards such as sequence-based updates and guarded database writes to reduce the risk of stale answer updates.

However, no load test simulating 200 concurrent students was performed.

The local SQLite benchmark measures sequential requests using Django's test client. It does not establish production concurrency capacity.

**Assessment:** The 200-student concurrency target remains unverified. A load test using a production-like PostgreSQL environment and deployment configuration is required.

## 10. Overall Conclusion

The verification exercise produced the following results:

- Answer-save latency was measured across 100 local test-client requests.
- Existing application security controls have supporting test evidence.
- SQLite backup and restoration were successfully tested.
- PostgreSQL recovery, production availability and uptime remain unverified.
- Data retention requirements need to be formally defined and implemented.
- WCAG 2.1 AA compliance requires further testing.
- The 200-student concurrency target requires dedicated load testing.

The measured latency results demonstrate local application-level performance only. They do not establish production performance or fulfilment of an unspecified response-time threshold.

Overall, the project has evidence for selected non-functional requirements, while several requirements need further implementation or environment-specific verification before they can be considered fully satisfied.
