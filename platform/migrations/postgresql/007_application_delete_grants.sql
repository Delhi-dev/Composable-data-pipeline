\set ON_ERROR_STOP on

-- These are the only application-managed replacement/draft-delete tables.
-- Published datasets, source snapshots, evidence and history remain non-deletable.
GRANT DELETE ON TABLE
    cbcr_control.user_role,
    cbcr_control.mapping_dictionary_entry,
    cbcr_control.function_definition
TO cbcr_user;

INSERT INTO cbcr_control.schema_migration(migration_id,description)
VALUES (
    '007_application_delete_grants',
    'Grant narrowly scoped deletes for role replacement, dictionary replacement and draft removal'
)
ON CONFLICT (migration_id) DO NOTHING;
