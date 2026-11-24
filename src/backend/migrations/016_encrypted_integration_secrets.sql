-- =============================================================================
-- 016: Encrypted integration secrets (inspection finding F-30)
-- =============================================================================
-- tenant_channel_integrations.webhook_secret now holds AES-256-GCM ciphertext
-- ("enc:v1:<nonce>:<ciphertext>", written by the application). Ciphertext is longer
-- than the original VARCHAR(255). After applying this file, run
--   python -m src.backend.migrations.encrypt_channel_secrets
-- to re-encrypt rows that were stored in plaintext.
ALTER TABLE tenant_channel_integrations ALTER COLUMN webhook_secret TYPE TEXT;
