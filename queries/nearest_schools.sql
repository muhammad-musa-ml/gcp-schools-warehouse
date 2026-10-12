-- The @limit schools closest to a point (standard SQL, to compare with the pipe versions)
SELECT
  school_name,
  city,
  county_name,
  ROUND(ST_DISTANCE(location, ST_GEOGPOINT(@lon, @lat)) / 1000, 2) AS distance_km
FROM `{{ project }}.{{ warehouse }}.wi_county_schools`
ORDER BY distance_km
LIMIT @limit
