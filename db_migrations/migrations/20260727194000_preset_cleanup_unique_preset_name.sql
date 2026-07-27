-- Applied live 2026-07-27 (MCP: preset_cleanup_unique_preset_name).
-- Duplicate preset_name cleanup (Adam decision 2026-07-27); sortie map
-- keys shipped first (PortfolioMaker dev 2f20b56). path_code has a UNIQUE
-- index, so the donor 'mapping' row is deleted BEFORE canonical claims 'C'.
-- Deleted rows: 25dac198 (mapping 2/27, 0 FKs) and the four empty 2/12
-- stubs (basic/construction/premium/standard, inactive, 0 FKs).
UPDATE processing_templates SET
  step_definitions = (SELECT step_definitions FROM processing_templates WHERE id='25dac198-4617-404f-b926-19ef06b912ef'),
  default_steps   = (SELECT default_steps   FROM processing_templates WHERE id='25dac198-4617-404f-b926-19ef06b912ef')
WHERE id = '711c7567-b4de-4330-8cc4-73afa8a01a63';
DELETE FROM processing_templates WHERE id = '25dac198-4617-404f-b926-19ef06b912ef'
  AND NOT EXISTS (SELECT 1 FROM drone_jobs WHERE processing_template_id = '25dac198-4617-404f-b926-19ef06b912ef');
UPDATE processing_templates SET path_code = 'C'
WHERE id = '711c7567-b4de-4330-8cc4-73afa8a01a63';
UPDATE processing_templates SET preset_name='adiat_roof'      WHERE id='7f300013-4dbe-4528-a543-48b74e64e789';
UPDATE processing_templates SET preset_name='adiat_insurance' WHERE id='6e2584c2-f272-47b9-b51f-2a11addbba34';
DELETE FROM processing_templates pt
WHERE pt.created_at::date = '2026-02-12'
  AND pt.active = false
  AND coalesce(jsonb_array_length(pt.step_definitions),0) = 0
  AND NOT EXISTS (SELECT 1 FROM drone_jobs dj WHERE dj.processing_template_id = pt.id);
ALTER TABLE processing_templates ADD CONSTRAINT processing_templates_preset_name_key UNIQUE (preset_name);
