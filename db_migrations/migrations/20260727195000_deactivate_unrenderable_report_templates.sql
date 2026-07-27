-- Applied live 2026-07-27 (MCP: deactivate_unrenderable_report_templates).
-- The 8 templates created 2026-07-27 reference section keys the CRM
-- frontend cannot render yet. Parked until the render layer ships
-- (Wave 6 of the 2026-07-27 pipeline program), then reactivated.
UPDATE report_templates SET is_active = false
WHERE code IN ('land_survey_civil','mining_aggregates','environmental_forestry',
               'utilities_corridor','public_safety_scene','insurance_claim',
               'pavement_pci','cemetery_survey');
