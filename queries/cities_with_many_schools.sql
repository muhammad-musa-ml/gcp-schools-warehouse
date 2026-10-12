-- Counties that have at least @min_cities cities with @min_schools or more schools each
FROM `{{ project }}.{{ warehouse }}.wi_county_schools`
|> AGGREGATE COUNT(*) AS schools GROUP BY county_name, city
|> WHERE schools >= @min_schools
|> AGGREGATE
     COUNT(*) AS qualifying_cities,
     STRING_AGG(city, ', ' ORDER BY schools DESC, city) AS cities
   GROUP BY county_name
|> WHERE qualifying_cities >= @min_cities
|> ORDER BY qualifying_cities DESC, county_name
