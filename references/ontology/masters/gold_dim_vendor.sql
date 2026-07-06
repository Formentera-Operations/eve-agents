-- Master export for ontology-individuals verification (plan U2).
-- Name/key columns only — dim_vendor also carries TAX_ID and payment fields;
-- never widen this select without a sensitivity check.
-- Run from repo root (schema follows wherever dbt builds gold_dim_vendor):
--   snow sql -f references/ontology/masters/gold_dim_vendor.sql \
--     -D "masters_schema=FO_RAW_DB.dev_dbt_rob_stover" --format csv \
--     > agents/doc-intel/analysts/.masters/gold_dim_vendor.csv
select
    VENDOR_ID,
    VENDOR_NAME,
    VENDOR_FULL_NAME
from <% masters_schema %>.DIM_VENDOR
