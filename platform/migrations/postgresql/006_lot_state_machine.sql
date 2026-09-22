\set ON_ERROR_STOP on

-- A lot is a workflow aggregate, not a published data row. Its state must advance
-- from registered to canonicalised/rejected while its source snapshots stay immutable.
DROP TRIGGER IF EXISTS immutable_cbcr_control_lot ON cbcr_control.lot;

INSERT INTO cbcr_control.schema_migration(migration_id,description)
VALUES (
    '006_lot_state_machine',
    'Permit governed lot status transitions while keeping source and published rows immutable'
)
ON CONFLICT (migration_id) DO NOTHING;
