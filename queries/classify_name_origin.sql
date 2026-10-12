-- Is a school named after a person, a place or something else?
-- Elementary schools in @city; the model name comes from the endpoint argument.
FROM `{{ project }}.{{ warehouse }}.wi_county_schools`
|> WHERE city = @city AND REGEXP_CONTAINS(school_name, r'\bElementary\b')
|> EXTEND TRIM(REGEXP_REPLACE(school_name, r'\b(Elementary|School)\b', '')) AS bare_name
|> EXTEND
     AI.CLASSIFY(
       bare_name,
       categories => [
         ('Person', 'named after a person'),
         ('Place', 'named after a place, landmark or natural feature'),
         ('Other', 'anything else, such as a concept, a program or a number')
       ],
       connection_id => '{{ connection }}',
       endpoint => '{{ endpoint }}'
     ) AS name_origin
|> SELECT school_name, bare_name, name_origin
|> ORDER BY school_name
