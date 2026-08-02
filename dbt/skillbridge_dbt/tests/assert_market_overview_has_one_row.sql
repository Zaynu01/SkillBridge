-- Test that market overview has exactly one row --
WITH overview_count AS (
    SELECT
        COUNT(*) AS total_rows
    FROM {{ ref('mart_market_overview') }}
)

SELECT
    total_rows
FROM overview_count
WHERE total_rows <> 1