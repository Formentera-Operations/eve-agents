-- Master export for ontology-individuals verification (plan U2).
-- Name/key/geography columns only — never widen without a sensitivity check.
-- Run from repo root (schema follows wherever dbt builds gold_dim_well):
--   snow sql -f references/ontology/masters/gold_dim_well.sql \
--     -D "masters_schema=FO_RAW_DB.dev_dbt_rob_stover" --format csv \
--     > agents/doc-intel/analysts/.masters/gold_dim_well.csv
select
    EID,
    API_10,
    WELL_NAME,
    LEASE_NAME,
    COMPANY_NAME,
    OPERATOR_NAME,
    STATE,
    COUNTY
from <% masters_schema %>.DIM_WELL
