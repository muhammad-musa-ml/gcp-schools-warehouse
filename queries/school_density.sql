-- Schools per 100 square km of land, by county
FROM `{{ project }}.{{ warehouse }}.wi_county_schools` AS s
|> AGGREGATE COUNT(*) AS schools GROUP BY county_geo_id
|> JOIN `{{ project }}.{{ warehouse }}.wi_counties` AS c ON county_geo_id = c.geo_id
|> EXTEND ROUND(c.area_land_meters / 1e6, 0) AS land_km2
|> EXTEND ROUND(100 * schools / (c.area_land_meters / 1e6), 2) AS schools_per_100_km2
|> SELECT c.county_name, schools, land_km2, schools_per_100_km2
|> ORDER BY schools_per_100_km2 DESC
