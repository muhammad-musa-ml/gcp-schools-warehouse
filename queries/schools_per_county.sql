-- Schools, cities and rural share per county
FROM `{{ project }}.{{ warehouse }}.wi_county_schools`
|> AGGREGATE
     COUNT(*) AS schools,
     COUNT(DISTINCT city) AS cities,
     COUNTIF(locale_group = 'Rural') AS rural_schools
   GROUP BY county_name
|> EXTEND ROUND(100 * rural_schools / schools, 1) AS pct_rural
|> ORDER BY schools DESC, county_name
