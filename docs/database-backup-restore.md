# Database Backup and Restore Procedures

## 1. Purpose

This document describes the procedures for backing up, validating, and restoring the Online Exam Portal databases.

The project uses:

- SQLite for development (`config.settings.dev`).
- PostgreSQL for production (`config.settings.prod`).

These procedures help protect examination data, user information, and application records against accidental loss or database corruption.

## 2. General Precautions

1. Store database backups outside the application repository.
2. Restrict access to backup files because they may contain user and examination data.
3. Never commit database backups, passwords, or credentials to Git.
4. Validate backups before attempting restoration.
5. Create a safety backup before restoring over an existing database.
6. Test restoration using a separate database before replacing production data.
7. Follow the organisation's backup retention and access policies.

## 3. SQLite Backup and Restoration

SQLite is used for local development. The development database is `db.sqlite3` in the project root.

### 3.1 Create a SQLite Backup

Stop the Django development server before performing file-level database maintenance.

Run the following command from the project root:

```powershell
python -c "import sqlite3; src=sqlite3.connect('db.sqlite3'); dst=sqlite3.connect('backup.sqlite3'); src.backup(dst); dst.close(); src.close(); print('Backup created successfully')"
```

This uses SQLite's backup API to create `backup.sqlite3`.

Keep the backup outside the repository when storing it for long-term use.

### 3.2 Validate the SQLite Backup

Run:

```powershell
python -c "import sqlite3; conn=sqlite3.connect('backup.sqlite3'); print(conn.execute('PRAGMA integrity_check').fetchone()[0]); conn.close()"
```

Expected result:

```text
ok
```

The `ok` result indicates that SQLite's integrity check did not detect database corruption.

### 3.3 Restore SQLite to a Separate Test Database

Do not overwrite the original database during a restoration test.

Create a separate test database from the backup:

```powershell
python -c "import sqlite3; src=sqlite3.connect('backup.sqlite3'); dst=sqlite3.connect('restore-test.sqlite3'); src.backup(dst); dst.close(); src.close(); print('Restoration completed')"
```

Validate the restored database:

```powershell
python -c "import sqlite3; conn=sqlite3.connect('restore-test.sqlite3'); print(conn.execute('PRAGMA integrity_check').fetchone()[0]); conn.close()"
```

Expected result:

```text
ok
```

### 3.4 Verify Restored Data

Compare the original and restored database:

- Confirm that both databases pass the SQLite integrity check.
- Compare the table names.
- Compare the number of records in application tables.
- Verify important application data using the application or database queries.

A successful integrity check alone does not prove that every application record has been restored correctly.

## 4. PostgreSQL Backup and Restoration

PostgreSQL is used for the production environment.

The PostgreSQL client utilities `pg_dump`, `pg_restore`, and `createdb` are required.

### 4.1 Create a PostgreSQL Backup

Ensure that the PostgreSQL server is accessible and the required database credentials are configured.

Run:

```bash
pg_dump -U <username> -h <hostname> -p 5432 -d <database_name> -F c -f backup.dump
```

Replace the placeholders with the appropriate database connection details.

The `-F c` option creates a custom-format backup suitable for restoration using `pg_restore`.

### 4.2 Validate the PostgreSQL Backup

Run:

```bash
pg_restore --list backup.dump
```

This lists the database objects recorded in the backup archive.

Confirm that the expected database objects are present and that the command completes successfully.

### 4.3 Restore PostgreSQL to a Separate Test Database

Create a separate test database:

```bash
createdb -U <username> -h <hostname> -p 5432 <test_database_name>
```

Restore the backup into the test database:

```bash
pg_restore -U <username> -h <hostname> -p 5432 -d <test_database_name> backup.dump
```

Do not use the production database as the restoration test destination.

### 4.4 Verify the PostgreSQL Restoration

After restoration:

1. Connect to the test database.
2. Confirm that the expected tables and database objects exist.
3. Compare important record counts with the source database.
4. Check relationships and constraints.
5. Test application access using the restored database in a safe test environment.

Do not replace the production database until the restoration has been validated and approved.

## 5. Verification Results

### 5.1 SQLite Verification

The SQLite backup and restoration procedure was tested locally.

The following checks were completed:

| Verification | Result |
|---|---|
| Original database integrity | Passed (`ok`) |
| Restored database integrity | Passed (`ok`) |
| Original and restored table count | 20 each |
| Table names | Matched |
| Application table record counts | Matched |

The original and restored databases had matching record counts across the 19 application tables checked.

The comparison confirmed that the restoration test completed successfully for the local SQLite database. A complete row-by-row comparison of every database record was not performed.

### 5.2 PostgreSQL Verification

PostgreSQL backup and restoration were documented but were not tested locally because the required PostgreSQL client utilities (`pg_dump` and `pg_restore`) were unavailable in the local environment.

The PostgreSQL procedure must be tested in an environment with a running PostgreSQL server and the required client utilities before being considered verified.

## 6. Backup Storage and Retention

- Store backups in an approved secure location outside the source-code repository.
- Restrict backup access to authorised personnel.
- Use appropriate retention periods according to organisational requirements.
- Avoid storing database credentials in scripts or source files.
- Remove temporary restoration-test databases and files after verification, when they are no longer required.
- Periodically perform restoration tests to confirm that backups remain usable.

## 7. Conclusion

These procedures describe how to back up, validate, and restore the SQLite development database and PostgreSQL production database.

The SQLite backup and restoration procedure was verified locally. The PostgreSQL procedure is documented and requires verification in a suitable PostgreSQL environment.
