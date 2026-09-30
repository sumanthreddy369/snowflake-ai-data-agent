-- Override dbt's default schema naming. By default, a model with
-- `+schema: gold` under a profile whose schema is GOLD lands in
-- `<target.schema>_<custom>` = GOLD_GOLD -- but the Row Access Policy, the
-- Semantic View, the YAML semantic model, and sql/08_validation all point at
-- MARKET_AGENT.GOLD.*. Using the custom schema verbatim makes marts land in
-- GOLD and staging in STAGING, matching what everything downstream expects.
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim | upper }}
    {%- endif -%}
{%- endmacro %}
