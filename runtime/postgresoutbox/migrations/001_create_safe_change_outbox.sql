BEGIN;

CREATE TABLE public.safe_change_outbox (
    operation_id text PRIMARY KEY,
    content_type text NOT NULL,
    body bytea NOT NULL,
    body_hash text NOT NULL,
    fact_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT safe_change_outbox_operation_id_v1
        CHECK (operation_id ~ '^op-[0-9a-f]{64}$'),
    CONSTRAINT safe_change_outbox_content_type_v1
        CHECK (octet_length(content_type) <= 1024),
    CONSTRAINT safe_change_outbox_body_v1
        CHECK (octet_length(body) <= 1048576),
    CONSTRAINT safe_change_outbox_body_hash_v1
        CHECK (body_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT safe_change_outbox_fact_hash_v1
        CHECK (fact_hash ~ '^[0-9a-f]{64}$')
);

COMMENT ON TABLE public.safe_change_outbox IS
    'Operation facts committed by the safe-change PostgreSQL adapter';
COMMENT ON COLUMN public.safe_change_outbox.body_hash IS
    'SHA-256 of body, checked by the adapter on every read';
COMMENT ON COLUMN public.safe_change_outbox.fact_hash IS
    'Versioned length-framed fact hash, checked by the adapter on every read';

COMMIT;
