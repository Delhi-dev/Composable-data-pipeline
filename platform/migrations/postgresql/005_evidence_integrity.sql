\set ON_ERROR_STOP on

ALTER TABLE cbcr_control.schema_migration
    ADD COLUMN IF NOT EXISTS checksum varchar(64);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname='fk_enrichment_report'
          AND conrelid='cbcr_enriched.attribute'::regclass
    ) THEN
        ALTER TABLE cbcr_enriched.attribute
            ADD CONSTRAINT fk_enrichment_report
            FOREIGN KEY(dataset_id,dataset_version,report_id)
            REFERENCES cbcr_enriched.report(dataset_id,dataset_version,report_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname='fk_risk_result_report'
          AND conrelid='cbcr_risk.result'::regclass
    ) THEN
        ALTER TABLE cbcr_risk.result
            ADD CONSTRAINT fk_risk_result_report
            FOREIGN KEY(dataset_id,dataset_version,report_id)
            REFERENCES cbcr_risk_ready.report(dataset_id,dataset_version,report_id);
    END IF;
END $$;

DO $$
DECLARE
    relation_name text;
    trigger_name text;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'cbcr_control.lot',
        'cbcr_control.dataset',
        'cbcr_control.dataset_lineage',
        'cbcr_control.audit_event',
        'cbcr_dq.finding',
        'cbcr_dq.gate_evaluation',
        'cbcr_dq.record_disposition',
        'cbcr_dq.promotion_event',
        'cbcr_enriched.attribute',
        'cbcr_risk.result',
        'cbcr_risk.score_component',
        'cbcr_selection.decision_history'
    ] LOOP
        trigger_name := 'immutable_' || replace(relation_name, '.', '_');
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger
            WHERE tgname=trigger_name AND tgrelid=relation_name::regclass
        ) THEN
            EXECUTE format(
                'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %s '
                'FOR EACH ROW EXECUTE FUNCTION cbcr_control.reject_published_mutation()',
                trigger_name,
                relation_name
            );
        END IF;
    END LOOP;
END $$;

INSERT INTO cbcr_control.schema_migration(migration_id,description)
VALUES (
    '005_evidence_integrity',
    'Enforce report-level provenance, migration checksums and append-only evidence'
)
ON CONFLICT (migration_id) DO NOTHING;
