-- Distance from each school to the closest school at a different location (several schools
-- often share one campus, which would make the answer zero), summarised by locale group
FROM `{{ project }}.{{ warehouse }}.wi_county_schools` AS a
|> CROSS JOIN `{{ project }}.{{ warehouse }}.wi_county_schools` AS b
|> EXTEND ST_DISTANCE(a.location, b.location) AS metres
|> WHERE metres > 0
|> AGGREGATE MIN(metres) AS nearest_m
   GROUP BY a.ncessch, a.locale_group
|> AGGREGATE
     COUNT(*) AS schools,
     ROUND(APPROX_QUANTILES(nearest_m, 100)[OFFSET(50)] / 1000, 2) AS median_km,
     ROUND(MAX(nearest_m) / 1000, 1) AS max_km
   GROUP BY locale_group
|> ORDER BY median_km
