  # CbCR Pipeline — Simple Installation Steps

  1. Install Python 3.11+, PostgreSQL 14+, and Git on the computer.
  2. Clone/download this repository and open PowerShell in its root folder.
  3. Create a virtual environment: `python -m venv .venv`.
  4. Activate it: `.\.venv\Scripts\Activate.ps1`.
  5. Install the application packages: `python -m pip install -r platform\requirements.txt`.
  6. Create an empty PostgreSQL database (for example, `cbcr`) and an application user (for example, `cbcr_user`).
  7. Set the PostgreSQL host, port, database, application user and password environment variables shown in
  `README.md`.
  8. Set `CBCR_PG_MIGRATION_PASSWORD` to the migration-role password for the current PowerShell session.
  9. Create all pipeline schemas and tables: `python platform\tools\pg_apply_migrations.py --database cbcr --confirm-
  database cbcr`.
  10. Remove the temporary migration password: `Remove-Item Env:CBCR_PG_MIGRATION_PASSWORD`.
  11. Verify the database structure: `python platform\tools\pg_verify_schema.py --database cbcr`.
  12. If using XML intake, configure the XML-ingestion setup to publish CbCR data to the same database and run its XML
  loader.
  13. Select PostgreSQL as the application backend: `$env:CBCR_PERSISTENCE_BACKEND = 'postgresql'`.
  14. Start the application: `python -m uvicorn --app-dir platform cbcr_backend:app --reload`.
  15. Open the workbench at http://127.0.0.1:8000/.
  16. Check http://127.0.0.1:8000/api/v1/health and confirm that the persistence backend is `postgresql`.