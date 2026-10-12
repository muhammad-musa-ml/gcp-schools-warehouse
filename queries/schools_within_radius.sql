-- Schools within @radius_km of a point, by city
FROM `{{ project }}.{{ warehouse }}.wi_county_schools`
|> WHERE ST_DWITHIN(location, ST_GEOGPOINT(@lon, @lat), @radius_km * 1000)
|> AGGREGATE COUNT(*) AS schools GROUP BY city, county_name
|> ORDER BY schools DESC, city
