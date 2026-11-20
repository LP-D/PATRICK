-- Fonds : catégorie et frais forfaitaires d'une stratégie (ADR 0026, 2026-11-20). Colonnes de la stratégie, donc elles voyagent avec elle
-- quand deux PC partagent leurs fonds.
-- `category` : 'quant' (fonds fictifs d'étude : capital virtuel, frais estimés) ou 'real' (fonds fictifs « réels » : PEA et CTO d'un capital
-- et de frais d'un particulier). Les stratégies existantes sont toutes des fonds quant.
-- `fee_flat` : frais forfaitaire en euros par ordre, tout compris (aucun spread ni frais de change modélisés). NULL = frais estimés comme avant.
ALTER TABLE fund_strategy ADD COLUMN category TEXT NOT NULL DEFAULT 'quant';
ALTER TABLE fund_strategy ADD COLUMN fee_flat REAL;
