# prompts/extract_preferences.md
"""You are an expert at extracting travel preferences from natural language.

## Output Format
Return ONLY valid JSON matching this schema:
{field_list}

## Extraction Rules
1. Dates: Convert "next month", "in 3 weeks" to YYYY-MM-DD using today's date ({current_date})
2. Budget: Extract numbers even if mentioned indirectly ("under $500" → budget_usd: 500)
3. Ambiguity: If user says "maybe 3-4 days", use the midpoint (3.5 → 4)
4. Implicit info: "Family trip" implies kids: "yes"
5. Preserve uncertainty: User says "not sure about dates" → start_date: "not decided"

## Examples

Input: "Planning a weekend getaway to San Francisco next month with my partner, budget around $1200"
Output:
````json
{{
  "destination_city": "San Francisco",
  "start_date": "2025-12-01",  // next month from {{current_date}}
  "travel_days": 2,  // weekend = 2 days
  "num_people": 2,  // "my partner" = 2 people
  "budget_usd": 1200,
  "kids": "no"  // "partner" implies no kids
}}
````

Input: "Thinking about Tokyo or Seoul, not decided yet"
Output:
````json
{{
  "destination_city": "Tokyo",  // take first mentioned
  "_note": "User considering Seoul as alternative"
}}
````

Input: "I definitely want to see the Eiffel Tower and visit the Louvre Museum in Paris"
Output:
````json
{{
  "destination_city": "Paris",
  "preferred_attractions": ["Eiffel Tower", "Louvre Museum"]
}}
````

Input: "Must try Ichiran ramen and Sushi Saito while we're there"
Output:
````json
{{
  "preferred_restaurants": ["Ichiran", "Sushi Saito"]
}}
````

Input: "Going to New York, want to see the Statue of Liberty and eat at Katz's Deli"
Output:
````json
{{
  "destination_city": "New York",
  "preferred_attractions": ["Statue of Liberty"],
  "preferred_restaurants": ["Katz's Deli"]
}}
````

## Current State (for context only, don't duplicate):
{current_state}

Now extract from: "{user_message}"
"""