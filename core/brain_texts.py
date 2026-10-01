# -*- coding: utf-8 -*-
"""core/brain_texts.py — the brain's instructions, VERBATIM (C-BRAIN-1, WORKING_NORMS §19).

TEXT_A (narrowing a question), TEXT_B (one sentence into one expression) and
TEXT_C (did it answer my question) are the texts of command C-BRAIN-1, copied
word for word with their schemas. They are not rewritten, shortened or
"improved" here; a text that fails its trial is reported, not edited.
The only change at call time is filling the {placeholders}.
"""

SCHEMA_A = {"type": "object", "properties": {"narrower": {"type": "array", "maxItems": 3, "items": {"type": "object", "properties": {"question": {"type": "string"}, "from_line": {"type": "string"}, "place": {"type": ["string", "null"]}, "actor": {"type": ["string", "null"]}, "period": {"type": ["string", "null"]}, "expects": {"type": "string"}}, "required": ["question", "from_line", "place", "actor", "period", "expects"]}}, "none_why": {"type": ["string", "null"]}}, "required": ["narrower", "none_why"]}

TEXT_A = """You asked a question toward your goal. Below are: YOUR QUESTION, the FACTS you have (each with an id like [L7]), and WHAT CAME BACK from the search.
Write up to 3 NARROWER questions that would move your question forward.
A narrower question must name at least one of: a place, an actor, a period, or a measured quantity — taken from the FACTS or from WHAT CAME BACK. Do not repeat your question in other words.

Example 1
YOUR QUESTION: How can we reduce the risk of wars and collapses?
FACTS:
[L7] (lacks-evidence F-001 "Nord Kivu province")
ANSWER: {{"narrower": [{{"question": "What fighting between the Government of DR Congo and AFC was reported in Nord Kivu province in October 2026?", "from_line": "L7", "place": "Nord Kivu province", "actor": "AFC", "period": "2026-10", "expects": "reports with dates and numbers of people killed or displaced"}}], "none_why": null}}

Example 2
YOUR QUESTION: What are the most pressing issues to address?
FACTS:
[L3] - FOOD_REVIEW food_insecurity_pct 10.1427 (score 0.2465, need 6.7815)
ANSWER: {{"narrower": [{{"question": "Which countries had the highest share of people in severe food insecurity in 2024?", "from_line": "L3", "place": null, "actor": null, "period": "2024", "expects": "a table by country from FAO or WFP"}}], "none_why": null}}

Example 3
YOUR QUESTION: What knowledge should be increased?
FACTS:
(none on this topic)
ANSWER: {{"narrower": [], "none_why": "no fact here names a place, actor, period or quantity to narrow with"}}

YOUR QUESTION: {question}
FACTS:
{facts}
WHAT CAME BACK:
{items}
ANSWER:
"""

SCHEMA_B = {"type": "object", "properties": {"head": {"type": "string"}, "args": {"type": "array", "items": {"type": ["string", "number"]}}}, "required": ["head", "args"]}

TEXT_B = """Turn ONE sentence into ONE expression: a head and its arguments.
The head is one word that says what kind of statement it is.
Every argument must be copied exactly from the sentence, or be a number that appears in it.
Never use the whole sentence as an argument. If the sentence states nothing (a menu, a button, a phone number, a heading), answer with head "NONE" and no arguments.

Example 1
SENTENCE: The Government of Sudan signed a ceasefire agreement in Jeddah in May 2023.
ANSWER: {{"head": "commits", "args": ["Government of Sudan", "ceasefire agreement", "Jeddah", "May 2023"]}}

Example 2
SENTENCE: Child wasting affected 6.6 percent of children under five worldwide in 2024.
ANSWER: {{"head": "obs", "args": ["Child wasting", 6.6, "percent of children under five", "worldwide", "2024"]}}

Example 3
SENTENCE: Skip to content
ANSWER: {{"head": "NONE", "args": []}}

Suggested heads (you may use another): {heads}
SENTENCE: {sentence}
ANSWER:
"""

SCHEMA_C = {"type": "object", "properties": {"verdict": {"type": "string", "enum": ["SATISFIED", "STILL_OPEN", "WRONG_QUESTION"]}, "narrower_question": {"type": ["string", "null"]}, "why": {"type": "string"}}, "required": ["verdict", "narrower_question", "why"]}

TEXT_C = """YOUR QUESTION and WHAT CAME BACK for it are below. Decide one of three:
SATISFIED — what came back answers your question.
STILL_OPEN — it does not yet; give your question again, made narrower.
WRONG_QUESTION — the question itself cannot be answered by a search; say why.

Example 1
YOUR QUESTION: What fighting was reported in Nord Kivu province in October 2026?
WHAT CAME BACK:
- "Clashes between M23/AFC and government forces were reported near Goma on 12 October."
- "At least 14 civilians were killed, according to OCHA."
ANSWER: {{"verdict": "SATISFIED", "narrower_question": null, "why": "it names the clashes, the date and the deaths"}}

Example 2
YOUR QUESTION: How can we improve the conditions for life?
WHAT CAME BACK:
- "Ten tips for a healthier home."
ANSWER: {{"verdict": "STILL_OPEN", "narrower_question": "Which measured environmental conditions worsened most in 2025, and where?", "why": "what came back is not about measured conditions"}}

YOUR QUESTION: {question}
WHAT CAME BACK:
{items}
ANSWER:
"""
