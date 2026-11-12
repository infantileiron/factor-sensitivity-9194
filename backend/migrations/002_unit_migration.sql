-- Incremental migration for affine unit migration (2026-11).
-- Fresh databases create these columns automatically from SQLAlchemy metadata.
-- Existing production databases apply the statements below after review:
ALTER TABLE response_models
  ADD COLUMN source_model_id VARCHAR(36) NULL,
  ADD COLUMN migration JSON NULL,
  ADD CONSTRAINT fk_response_models_source FOREIGN KEY (source_model_id) REFERENCES response_models(id);
ALTER TABLE spaces
  ADD COLUMN source_space_id VARCHAR(36) NULL,
  ADD COLUMN migration JSON NULL,
  ADD CONSTRAINT fk_spaces_source FOREIGN KEY (source_space_id) REFERENCES spaces(id);
-- Legacy rows keep NULL provenance and their original coefficients/ranges;
-- migrated rows are new versions, never in-place edits.
