# BRAIN_INSTRUCTIONS — 1 Oct 2026 (command C-BRAIN-1, finished by C-BRAIN-1b)

## What does not work

(Step 1 of C-BRAIN-1b commits the trial record first; this section is completed in Step 4.)

## Part 0 — read-only findings (1 Oct 2026)

**0a. Who answered the timed-out 3B call.** At 16:50:32 UTC the symbols call (caller
`brain:symbols for what I was shown`) hit `ReadTimeout … read timeout=47.3` on
`local:cortex-l1b-3b:latest` (llm_door measured leg: timeout 48.5 s, p95 32.3 s, n 617).
core.brain.think then took its second rung, `_smaller(model)`. `_smaller` read the size with
the regex `:(\d+)b`, which finds nothing in `cortex-l1b-3b:latest`, so the 3B counted as 99b
and `qwen2.5:3b` as "smaller"; qwen2.5:3b answered at 16:51:09 (37.0 s). The brain-turn log
said "warm core restored after qwen2.5:3b … 9.8 s". `ollama ps` at that moment was not
recorded — UNVERIFIED which models were resident. Fixed in f376de5 (size now read as 3; a
schema-bound call has no fallback rung at all).

**0b. Structured outputs work on this Ollama.** `ollama version is 0.24.0`. Request:
`{"model": "cortex-l1b-3b:latest", "stream": false, "messages": [{"role": "user", "content":
"Reply with the word READY."}], "format": {"type": "object", "properties": {"word": {"type":
"string"}}, "required": ["word"]}, "options": {"temperature": 0}}` → reply `{"word": "READY"}`,
done_reason `stop`, total_duration 1.33 s.

**0c. What the brain was sent before this command.** core/brain.py set `body["format"] =
"json"` (not a schema) at default temperature 0.2; core/brain_needs.py and core/symbols.py
called `think` with `schema=None`, i.e. free text parsed by hand.

**Licences (printed before first use).** trafilatura 2.2.0: Apache-2.0. gliner2 2.0.0:
Apache-2.0. Model card fastino/gliner2-large-v1: apache-2.0. All usable in a public MIT
repository's pipeline. The gliner2 base package depends only on `requests` (the hosted API);
the `local` extra (torch 2.14.1+cpu, CUDA False) runs it on CPU. No model file is in the repo.

## Part 1 — the trial: each text on five real inputs (no commit)

Model `cortex-l1b-3b:latest`, through core.brain.think, `json_schema` = the text's own schema,
temperature 0, `exact=True` (the filled text is the whole prompt). Loop stopped, no cycle live.
Every call below is from the record `b1_trial.json` written by that run on 1 Oct 2026 (about
20:23–20:27 UTC); **none was re-run**. The input shown is the verbatim text with its
placeholders filled exactly as sent (the record holds the filled values; the texts are
core/brain_texts.py, unchanged since).

Rules: A is usable when schema-valid and at least one narrower question names a place, actor,
period or quantity. B is usable when schema-valid and it passes the span check. C is usable
when schema-valid.

Inputs for A and C: the five brain needs (BN-6dddb2e609, BN-580dae4f5e, BN-1340065e41, BN-e0f5781722, BN-1bdc390518). FACTS for A: the
numbered briefing lines matching the need's sub-goal (its axes, categories, subcategories).
WHAT CAME BACK: the first five statements fetched for the need (at most 300 characters each).
Inputs for B: five sentences of 40–220 characters from OpenClaw-fetched pages, chosen by a
stable hash of the statement id.

### Call 1 — TEXT A, need BN-6dddb2e609

seconds **34.0** · usable **no** — not usable: schema-valid, but none of its 3 narrower question(s) names a place, actor, period or quantity (none_why None)

Input sent:

```text
You asked a question toward your goal. Below are: YOUR QUESTION, the FACTS you have (each with an id like [L7]), and WHAT CAME BACK from the search.
Write up to 3 NARROWER questions that would move your question forward.
A narrower question must name at least one of: a place, an actor, a period, or a measured quantity — taken from the FACTS or from WHAT CAME BACK. Do not repeat your question in other words.

Example 1
YOUR QUESTION: How can we reduce the risk of wars and collapses?
FACTS:
[L7] (lacks-evidence F-001 "Nord Kivu province")
ANSWER: {"narrower": [{"question": "What fighting between the Government of DR Congo and AFC was reported in Nord Kivu province in October 2026?", "from_line": "L7", "place": "Nord Kivu province", "actor": "AFC", "period": "2026-10", "expects": "reports with dates and numbers of people killed or displaced"}], "none_why": null}

Example 2
YOUR QUESTION: What are the most pressing issues to address?
FACTS:
[L3] - FOOD_REVIEW food_insecurity_pct 10.1427 (score 0.2465, need 6.7815)
ANSWER: {"narrower": [{"question": "Which countries had the highest share of people in severe food insecurity in 2024?", "from_line": "L3", "place": null, "actor": null, "period": "2024", "expects": "a table by country from FAO or WFP"}], "none_why": null}

Example 3
YOUR QUESTION: What knowledge should be increased?
FACTS:
(none on this topic)
ANSWER: {"narrower": [], "none_why": "no fact here names a place, actor, period or quantity to narrow with"}

YOUR QUESTION: What are the most pressing issues to address?
FACTS:
[L4] - FOOD_REVIEW food_insecurity_pct: value 10.1427 percent of population, score 0.2465, need 6.7815
[L5] - ENERGY_REVIEW renewable_energy_pct: value 19.7356 percent of total energy, score 0.2467, need 6.0264
WHAT CAME BACK:
- "Global Issues | United Nations"
- "Skip to main content"
- "Toggle navigation"
- "Welcome to the United Nations"
- "العربية"
ANSWER:
```

Raw reply:

```json
{"narrower": [{"question": "What are the most pressing issues based on the provided data?", "from_line": "L4", "place": null, "actor": null, "period": null, "expects": "10.1427 vs need 6.7815: above the line; 19.7356 vs line 6.0264: above the line; so both are higher than the line; what is above the line is more pressing; thus, food insecurity and renewable energy are more pressing issues."}, {"question": "What is the difference between food insecurity and renewable energy in terms of their scores versus the need line?", "from_line": "L4 vs L5", "place": null, "actor": null, "period": null, "expects": "10.1427 vs line 6.7815: above the line; 19.7356 vs line 6.0264: above the line; so both are higher than the line; what is above the line is more pressing; thus, food insecurity and renewable energy are more pressing issues."}, {"question": "Why are food insecurity and renewable energy considered more pressing based on their scores versus the need line?", "from_line": "L4 vs L5", "place": null, "actor": null, "period": null, "expects": "10.1427 vs line 6.7815: above the line; 19.7356 vs line 6.0264: above the line; so both are higher than the line; what is above the line is more pressing; thus, food insecurity and renewable energy are more pressing issues."}], "none_why": null}
```

### Call 2 — TEXT C, need BN-6dddb2e609

seconds **10.1** · usable **yes** — usable: schema-valid (verdict one of the three)

Input sent:

```text
YOUR QUESTION and WHAT CAME BACK for it are below. Decide one of three:
SATISFIED — what came back answers your question.
STILL_OPEN — it does not yet; give your question again, made narrower.
WRONG_QUESTION — the question itself cannot be answered by a search; say why.

Example 1
YOUR QUESTION: What fighting was reported in Nord Kivu province in October 2026?
WHAT CAME BACK:
- "Clashes between M23/AFC and government forces were reported near Goma on 12 October."
- "At least 14 civilians were killed, according to OCHA."
ANSWER: {"verdict": "SATISFIED", "narrower_question": null, "why": "it names the clashes, the date and the deaths"}

Example 2
YOUR QUESTION: How can we improve the conditions for life?
WHAT CAME BACK:
- "Ten tips for a healthier home."
ANSWER: {"verdict": "STILL_OPEN", "narrower_question": "Which measured environmental conditions worsened most in 2025, and where?", "why": "what came back is not about measured conditions"}

YOUR QUESTION: What are the most pressing issues to address?
WHAT CAME BACK:
- "Global Issues | United Nations"
- "Skip to main content"
- "Toggle navigation"
- "Welcome to the United Nations"
- "العربية"
ANSWER:
```

Raw reply:

```json
{"verdict": "STILL_OPEN", "narrower_question": "which specific issues are most pressing?", "why": "the provided links and text do not specify any particular issues; they seem to be general UN pages."}
```

### Call 3 — TEXT A, need BN-580dae4f5e

seconds **19.1** · usable **yes** — usable: schema-valid; a narrower question names actor 'Criminon International'

Input sent:

```text
You asked a question toward your goal. Below are: YOUR QUESTION, the FACTS you have (each with an id like [L7]), and WHAT CAME BACK from the search.
Write up to 3 NARROWER questions that would move your question forward.
A narrower question must name at least one of: a place, an actor, a period, or a measured quantity — taken from the FACTS or from WHAT CAME BACK. Do not repeat your question in other words.

Example 1
YOUR QUESTION: How can we reduce the risk of wars and collapses?
FACTS:
[L7] (lacks-evidence F-001 "Nord Kivu province")
ANSWER: {"narrower": [{"question": "What fighting between the Government of DR Congo and AFC was reported in Nord Kivu province in October 2026?", "from_line": "L7", "place": "Nord Kivu province", "actor": "AFC", "period": "2026-10", "expects": "reports with dates and numbers of people killed or displaced"}], "none_why": null}

Example 2
YOUR QUESTION: What are the most pressing issues to address?
FACTS:
[L3] - FOOD_REVIEW food_insecurity_pct 10.1427 (score 0.2465, need 6.7815)
ANSWER: {"narrower": [{"question": "Which countries had the highest share of people in severe food insecurity in 2024?", "from_line": "L3", "place": null, "actor": null, "period": "2024", "expects": "a table by country from FAO or WFP"}], "none_why": null}

Example 3
YOUR QUESTION: What knowledge should be increased?
FACTS:
(none on this topic)
ANSWER: {"narrower": [], "none_why": "no fact here names a place, actor, period or quantity to narrow with"}

YOUR QUESTION: How can we improve the conditions for life?
FACTS:
(none on this topic)
WHAT CAME BACK:
- "Improving Conditions in Life - Criminon International"
- "Skip to content"
- "GET HELP NOW"
- "RELATED SITESABLE.ORG"
- "NARCONON.ORG"
ANSWER:
```

Raw reply:

```json
{"narrower": [{"question": "What specific improvements are suggested by Criminon International for life conditions?", "from_line": "Improving Conditions in Life - Criminon International", "place": null, "actor": "Criminon International", "period": null, "expects": "details or recommendations"}, {"question": "Why does NARCONON.ORG mention improving life conditions as a related siteable.org?", "from_line": "NARCONON.ORG", "place": null, "actor": "NARCONON.ORG", "period": null, "expects": "reasons or explanations"}, {"question": "What does GET HELP NOW suggest about improving life conditions?", "from_line": "GET HELP NOW", "place": null, "actor": "GET HELP NOW", "period": null, "expects": "urgency or call-to-action"}], "none_why": null}
```

### Call 4 — TEXT C, need BN-580dae4f5e

seconds **10.3** · usable **yes** — usable: schema-valid (verdict one of the three)

Input sent:

```text
YOUR QUESTION and WHAT CAME BACK for it are below. Decide one of three:
SATISFIED — what came back answers your question.
STILL_OPEN — it does not yet; give your question again, made narrower.
WRONG_QUESTION — the question itself cannot be answered by a search; say why.

Example 1
YOUR QUESTION: What fighting was reported in Nord Kivu province in October 2026?
WHAT CAME BACK:
- "Clashes between M23/AFC and government forces were reported near Goma on 12 October."
- "At least 14 civilians were killed, according to OCHA."
ANSWER: {"verdict": "SATISFIED", "narrower_question": null, "why": "it names the clashes, the date and the deaths"}

Example 2
YOUR QUESTION: How can we improve the conditions for life?
WHAT CAME BACK:
- "Ten tips for a healthier home."
ANSWER: {"verdict": "STILL_OPEN", "narrower_question": "Which measured environmental conditions worsened most in 2025, and where?", "why": "what came back is not about measured conditions"}

YOUR QUESTION: How can we improve the conditions for life?
WHAT CAME BACK:
- "Improving Conditions in Life - Criminon International"
- "Skip to content"
- "GET HELP NOW"
- "RELATED SITESABLE.ORG"
- "NARCONON.ORG"
ANSWER:
```

Raw reply:

```json
{"verdict": "STILL_OPEN", "narrower_question": "which measured environmental conditions worsened most in 2025, and where?", "why": "what came back does not provide specific information about which environmental conditions worsened; it only mentions sites related to improving life."}
```

### Call 5 — TEXT A, need BN-1340065e41

seconds **13.5** · usable **no** — not usable: schema-valid, but none of its 1 narrower question(s) names a place, actor, period or quantity (none_why None)

Input sent:

```text
You asked a question toward your goal. Below are: YOUR QUESTION, the FACTS you have (each with an id like [L7]), and WHAT CAME BACK from the search.
Write up to 3 NARROWER questions that would move your question forward.
A narrower question must name at least one of: a place, an actor, a period, or a measured quantity — taken from the FACTS or from WHAT CAME BACK. Do not repeat your question in other words.

Example 1
YOUR QUESTION: How can we reduce the risk of wars and collapses?
FACTS:
[L7] (lacks-evidence F-001 "Nord Kivu province")
ANSWER: {"narrower": [{"question": "What fighting between the Government of DR Congo and AFC was reported in Nord Kivu province in October 2026?", "from_line": "L7", "place": "Nord Kivu province", "actor": "AFC", "period": "2026-10", "expects": "reports with dates and numbers of people killed or displaced"}], "none_why": null}

Example 2
YOUR QUESTION: What are the most pressing issues to address?
FACTS:
[L3] - FOOD_REVIEW food_insecurity_pct 10.1427 (score 0.2465, need 6.7815)
ANSWER: {"narrower": [{"question": "Which countries had the highest share of people in severe food insecurity in 2024?", "from_line": "L3", "place": null, "actor": null, "period": "2024", "expects": "a table by country from FAO or WFP"}], "none_why": null}

Example 3
YOUR QUESTION: What knowledge should be increased?
FACTS:
(none on this topic)
ANSWER: {"narrower": [], "none_why": "no fact here names a place, actor, period or quantity to narrow with"}

YOUR QUESTION: What knowledge should be increased to understand complex systems better?
FACTS:
(none on this topic)
WHAT CAME BACK:
- "The Opposite of Complex Isn't Simple."
- "It's Isolated"
- "LinkedIn respects your privacy"
- "LinkedIn and 3rd parties use essential and non-essential cookies to provide, secure, analyze and improve our Services, and to show you relevant ads (including professional and job ads) on and off LinkedIn."
- "Learn more in our Cookie Policy."
ANSWER:
```

Raw reply:

```json
{"narrower": [{"question": "What are the key principles or theories needed to understand complex systems?", "from_line": "The Opposite of Complex Isn't Simple.", "place": null, "actor": null, "period": null, "expects": "principles or theories related to understanding complexity"}], "none_why": null}
```

### Call 6 — TEXT C, need BN-1340065e41

seconds **11.0** · usable **yes** — usable: schema-valid (verdict one of the three)

Input sent:

```text
YOUR QUESTION and WHAT CAME BACK for it are below. Decide one of three:
SATISFIED — what came back answers your question.
STILL_OPEN — it does not yet; give your question again, made narrower.
WRONG_QUESTION — the question itself cannot be answered by a search; say why.

Example 1
YOUR QUESTION: What fighting was reported in Nord Kivu province in October 2026?
WHAT CAME BACK:
- "Clashes between M23/AFC and government forces were reported near Goma on 12 October."
- "At least 14 civilians were killed, according to OCHA."
ANSWER: {"verdict": "SATISFIED", "narrower_question": null, "why": "it names the clashes, the date and the deaths"}

Example 2
YOUR QUESTION: How can we improve the conditions for life?
WHAT CAME BACK:
- "Ten tips for a healthier home."
ANSWER: {"verdict": "STILL_OPEN", "narrower_question": "Which measured environmental conditions worsened most in 2025, and where?", "why": "what came back is not about measured conditions"}

YOUR QUESTION: What knowledge should be increased to understand complex systems better?
WHAT CAME BACK:
- "The Opposite of Complex Isn't Simple."
- "It's Isolated"
- "LinkedIn respects your privacy"
- "LinkedIn and 3rd parties use essential and non-essential cookies to provide, secure, analyze and improve our Services, and to show you relevant ads (including professional and job ads) on and off LinkedIn."
- "Learn more in our Cookie Policy."
ANSWER:
```

Raw reply:

```json
{"verdict": "STILL_OPEN", "narrower_question": "What specific knowledge or skills are most important for understanding complex systems?", "why": "The provided information does not directly address the question; it is about cookies and privacy, which are unrelated to knowledge needed for understanding complex systems."}
```

### Call 7 — TEXT A, need BN-e0f5781722

seconds **19.7** · usable **no** — not usable: schema-valid, but none of its 2 narrower question(s) names a place, actor, period or quantity (none_why None)

Input sent:

```text
You asked a question toward your goal. Below are: YOUR QUESTION, the FACTS you have (each with an id like [L7]), and WHAT CAME BACK from the search.
Write up to 3 NARROWER questions that would move your question forward.
A narrower question must name at least one of: a place, an actor, a period, or a measured quantity — taken from the FACTS or from WHAT CAME BACK. Do not repeat your question in other words.

Example 1
YOUR QUESTION: How can we reduce the risk of wars and collapses?
FACTS:
[L7] (lacks-evidence F-001 "Nord Kivu province")
ANSWER: {"narrower": [{"question": "What fighting between the Government of DR Congo and AFC was reported in Nord Kivu province in October 2026?", "from_line": "L7", "place": "Nord Kivu province", "actor": "AFC", "period": "2026-10", "expects": "reports with dates and numbers of people killed or displaced"}], "none_why": null}

Example 2
YOUR QUESTION: What are the most pressing issues to address?
FACTS:
[L3] - FOOD_REVIEW food_insecurity_pct 10.1427 (score 0.2465, need 6.7815)
ANSWER: {"narrower": [{"question": "Which countries had the highest share of people in severe food insecurity in 2024?", "from_line": "L3", "place": null, "actor": null, "period": "2024", "expects": "a table by country from FAO or WFP"}], "none_why": null}

Example 3
YOUR QUESTION: What knowledge should be increased?
FACTS:
(none on this topic)
ANSWER: {"narrower": [], "none_why": "no fact here names a place, actor, period or quantity to narrow with"}

YOUR QUESTION: What actions can we take to avoid high-risk situations?
FACTS:
[L1] - GOAL_PROGRESS_REVIEW goal_score: value None , score None, need 8.0 (NOT MEASURED)
[L3] - LONG_TERM_FUTURE_REVIEW (no key): value None , score None, need 7.0 (NOT MEASURED)
WHAT CAME BACK:
- "The first step in reducing problematic behaviours: Avoid high-risk situations which you can avoid - Dr. Patrick Keelan, Calgary Psychologist"
- "Skip to content"
- "Call Dr. Pat: (403) 324-1875"
- "Search for:"
- "MenuCounselling ServicesAbuse, Trauma & PTSD - Counselling"
ANSWER:
```

Raw reply:

```json
{"narrower": [{"question": "What behaviors should we avoid to reduce high-risk situations?", "from_line": "The first step in reducing problematic behaviours: Avoid high-risk situations which you can avoid - Dr. Patrick Keelan, Calgary Psychologist", "place": null, "actor": null, "period": null, "expects": "a list of behaviors to avoid"}, {"question": "What are the common high-risk situations we should try to avoid?", "from_line": "The first step in reducing problematic behaviours: Avoid high-risk situations which you can avoid - Dr. Patrick Keelan, Calgary Psychologist", "place": null, "actor": null, "period": null, "expects": "a list of common high-risk situations"}], "none_why": null}
```

### Call 8 — TEXT C, need BN-e0f5781722

seconds **9.7** · usable **yes** — usable: schema-valid (verdict one of the three)

Input sent:

```text
YOUR QUESTION and WHAT CAME BACK for it are below. Decide one of three:
SATISFIED — what came back answers your question.
STILL_OPEN — it does not yet; give your question again, made narrower.
WRONG_QUESTION — the question itself cannot be answered by a search; say why.

Example 1
YOUR QUESTION: What fighting was reported in Nord Kivu province in October 2026?
WHAT CAME BACK:
- "Clashes between M23/AFC and government forces were reported near Goma on 12 October."
- "At least 14 civilians were killed, according to OCHA."
ANSWER: {"verdict": "SATISFIED", "narrower_question": null, "why": "it names the clashes, the date and the deaths"}

Example 2
YOUR QUESTION: How can we improve the conditions for life?
WHAT CAME BACK:
- "Ten tips for a healthier home."
ANSWER: {"verdict": "STILL_OPEN", "narrower_question": "Which measured environmental conditions worsened most in 2025, and where?", "why": "what came back is not about measured conditions"}

YOUR QUESTION: What actions can we take to avoid high-risk situations?
WHAT CAME BACK:
- "The first step in reducing problematic behaviours: Avoid high-risk situations which you can avoid - Dr. Patrick Keelan, Calgary Psychologist"
- "Skip to content"
- "Call Dr. Pat: (403) 324-1875"
- "Search for:"
- "MenuCounselling ServicesAbuse, Trauma & PTSD - Counselling"
ANSWER:
```

Raw reply:

```json
{"verdict": "STILL_OPEN", "narrower_question": "which high-risk situations can we avoid?", "why": "the answers provide advice but do not list specific high-risk situations to avoid."}
```

### Call 9 — TEXT A, need BN-1bdc390518

seconds **17.8** · usable **no** — not usable: schema-valid, but none of its 1 narrower question(s) names a place, actor, period or quantity (none_why None)

Input sent:

```text
You asked a question toward your goal. Below are: YOUR QUESTION, the FACTS you have (each with an id like [L7]), and WHAT CAME BACK from the search.
Write up to 3 NARROWER questions that would move your question forward.
A narrower question must name at least one of: a place, an actor, a period, or a measured quantity — taken from the FACTS or from WHAT CAME BACK. Do not repeat your question in other words.

Example 1
YOUR QUESTION: How can we reduce the risk of wars and collapses?
FACTS:
[L7] (lacks-evidence F-001 "Nord Kivu province")
ANSWER: {"narrower": [{"question": "What fighting between the Government of DR Congo and AFC was reported in Nord Kivu province in October 2026?", "from_line": "L7", "place": "Nord Kivu province", "actor": "AFC", "period": "2026-10", "expects": "reports with dates and numbers of people killed or displaced"}], "none_why": null}

Example 2
YOUR QUESTION: What are the most pressing issues to address?
FACTS:
[L3] - FOOD_REVIEW food_insecurity_pct 10.1427 (score 0.2465, need 6.7815)
ANSWER: {"narrower": [{"question": "Which countries had the highest share of people in severe food insecurity in 2024?", "from_line": "L3", "place": null, "actor": null, "period": "2024", "expects": "a table by country from FAO or WFP"}], "none_why": null}

Example 3
YOUR QUESTION: What knowledge should be increased?
FACTS:
(none on this topic)
ANSWER: {"narrower": [], "none_why": "no fact here names a place, actor, period or quantity to narrow with"}

YOUR QUESTION: How can we reduce the risk of wars and collapses in sustainable civilisation?
FACTS:
[L2] - SOCIAL_RELATIONS_REVIEW refugee_population: value 29429000.0 persons, score 0.034, need 7.728
[L25] (lacks-evidence "F-004" "Gaza Strip")
[L26] (lacks-evidence "F-003" "Sud Kivu province")
[L27] (lacks-evidence "F-003" "Nord Kivu province")
[L28] (lacks-evidence "F-002" "ALL")
[L29] (lacks-evidence "F-001" "Sud Kivu province")
[L30] (lacks-evidence "F-001" "Nord Kivu province")
[L31] - F-001: Government of DR Congo (Zaire) - AFC in ['Nord Kivu province', 'Sud Kivu province']; kept if sum(best) < 25 from 2026-10-01 to 2026-10-31 (UCDP GED); resolves release date + 14 days (expected around 2026-11-20 (UCDP extracts candidate data on the 20th of every month))
[L32] - F-002: Government of Sudan - SFA in ALL; kept if sum(best) < 25 from 2026-10-01 to 2026-10-31 (UCDP GED); resolves release date + 14 days (expected around 2026-11-20 (UCDP extracts candidate data on the 20th of every month))
[L33] - F-003: Government of DR Congo (Zaire) - AFC in ['Nord Kivu province', 'Sud Kivu province']; kept if sum(best) < 25 from 2026-10-01 to 2026-10-31 (UCDP GED); resolves release date + 14 days (expected around 2026-11-20 (UCDP extracts candidate data on the 20th of every month))
[L34] - F-004: Government of Israel - Hamas in ['Gaza Strip']; kept if sum(best) < 25 from 2026-10-01 to 2026-10-31 (UCDP GED); resolves release date + 14 days (expected around 2026-11-20 (UCDP extracts candidate data on the 20th of every month))
WHAT CAME BACK:
- "A "Sustainable Civilization""
- "A "Sustainable Civilization""
- "If we want to be a sustainable civilization we should know what one looks like."
- "To help visualize it, consider a sustainable international space station?"
- "It requires oxygen, food, and energy to support six people."
ANSWER:
```

Raw reply:

```json
{"narrower": [{"question": "What are the key components for a sustainable international space station?", "from_line": "It requires oxygen, food, and energy to support six people.", "place": null, "actor": null, "period": null, "expects": "oxygen, food, and energy; six people"}], "none_why": null}
```

### Call 10 — TEXT C, need BN-1bdc390518

seconds **9.4** · usable **yes** — usable: schema-valid (verdict one of the three)

Input sent:

```text
YOUR QUESTION and WHAT CAME BACK for it are below. Decide one of three:
SATISFIED — what came back answers your question.
STILL_OPEN — it does not yet; give your question again, made narrower.
WRONG_QUESTION — the question itself cannot be answered by a search; say why.

Example 1
YOUR QUESTION: What fighting was reported in Nord Kivu province in October 2026?
WHAT CAME BACK:
- "Clashes between M23/AFC and government forces were reported near Goma on 12 October."
- "At least 14 civilians were killed, according to OCHA."
ANSWER: {"verdict": "SATISFIED", "narrower_question": null, "why": "it names the clashes, the date and the deaths"}

Example 2
YOUR QUESTION: How can we improve the conditions for life?
WHAT CAME BACK:
- "Ten tips for a healthier home."
ANSWER: {"verdict": "STILL_OPEN", "narrower_question": "Which measured environmental conditions worsened most in 2025, and where?", "why": "what came back is not about measured conditions"}

YOUR QUESTION: How can we reduce the risk of wars and collapses in sustainable civilisation?
WHAT CAME BACK:
- "A "Sustainable Civilization""
- "A "Sustainable Civilization""
- "If we want to be a sustainable civilization we should know what one looks like."
- "To help visualize it, consider a sustainable international space station?"
- "It requires oxygen, food, and energy to support six people."
ANSWER:
```

Raw reply:

```json
{"verdict": "STILL_OPEN", "narrower_question": null, "why": "what came back does not directly answer how to reduce the risk; it provides some context about a sustainable civilization but does not give specific actions."}
```

### Call 11 — TEXT B, statement e08f3b1b5b72daafb459b2ee (https://www.ffiec.gov/resources/reporting-forms/ffiec002-historic)

seconds **8.2** · usable **yes** — usable: schema-valid, every argument passed the span check

Input sent:

```text
Turn ONE sentence into ONE expression: a head and its arguments.
The head is one word that says what kind of statement it is.
Every argument must be copied exactly from the sentence, or be a number that appears in it.
Never use the whole sentence as an argument. If the sentence states nothing (a menu, a button, a phone number, a heading), answer with head "NONE" and no arguments.

Example 1
SENTENCE: The Government of Sudan signed a ceasefire agreement in Jeddah in May 2023.
ANSWER: {"head": "commits", "args": ["Government of Sudan", "ceasefire agreement", "Jeddah", "May 2023"]}

Example 2
SENTENCE: Child wasting affected 6.6 percent of children under five worldwide in 2024.
ANSWER: {"head": "obs", "args": ["Child wasting", 6.6, "percent of children under five", "worldwide", "2024"]}

Example 3
SENTENCE: Skip to content
ANSWER: {"head": "NONE", "args": []}

Suggested heads (you may use another): event, claim, commits, causes, increases, decreases, located-in, part-of, affects-group, says
SENTENCE: Instructions for Preparation - revised September 2023 (PDF)
ANSWER:
```

Raw reply:

```json
{"head": "says", "args": ["Instructions for Preparation", "revised September 2023"]}
```

### Call 12 — TEXT B, statement 92f37d1d667671b1dc66f9e9 (https://data.un.org/Data.aspx?d=PopDiv&f=variableID%3A65)

seconds **5.8** · usable **no** — not usable: schema-valid, span check failed — argument 'the sea' is not a span of the sentence

Input sent:

```text
Turn ONE sentence into ONE expression: a head and its arguments.
The head is one word that says what kind of statement it is.
Every argument must be copied exactly from the sentence, or be a number that appears in it.
Never use the whole sentence as an argument. If the sentence states nothing (a menu, a button, a phone number, a heading), answer with head "NONE" and no arguments.

Example 1
SENTENCE: The Government of Sudan signed a ceasefire agreement in Jeddah in May 2023.
ANSWER: {"head": "commits", "args": ["Government of Sudan", "ceasefire agreement", "Jeddah", "May 2023"]}

Example 2
SENTENCE: Child wasting affected 6.6 percent of children under five worldwide in 2024.
ANSWER: {"head": "obs", "args": ["Child wasting", 6.6, "percent of children under five", "worldwide", "2024"]}

Example 3
SENTENCE: Skip to content
ANSWER: {"head": "NONE", "args": []}

Suggested heads (you may use another): event, claim, commits, causes, increases, decreases, located-in, part-of, affects-group, says
SENTENCE: Countries with Access to the Sea: Europe
ANSWER:
```

Raw reply:

```json
{"head": "located-in", "args": ["Europe", "the sea"]}
```

### Call 13 — TEXT B, statement 421290195907266bdfc69076 (https://greenblog.co.kr/en/2026/09/06/global-clean-cooking-access-map-by-country/)

seconds **6.0** · usable **yes** — usable: schema-valid, every argument passed the span check

Input sent:

```text
Turn ONE sentence into ONE expression: a head and its arguments.
The head is one word that says what kind of statement it is.
Every argument must be copied exactly from the sentence, or be a number that appears in it.
Never use the whole sentence as an argument. If the sentence states nothing (a menu, a button, a phone number, a heading), answer with head "NONE" and no arguments.

Example 1
SENTENCE: The Government of Sudan signed a ceasefire agreement in Jeddah in May 2023.
ANSWER: {"head": "commits", "args": ["Government of Sudan", "ceasefire agreement", "Jeddah", "May 2023"]}

Example 2
SENTENCE: Child wasting affected 6.6 percent of children under five worldwide in 2024.
ANSWER: {"head": "obs", "args": ["Child wasting", 6.6, "percent of children under five", "worldwide", "2024"]}

Example 3
SENTENCE: Skip to content
ANSWER: {"head": "NONE", "args": []}

Suggested heads (you may use another): event, claim, commits, causes, increases, decreases, located-in, part-of, affects-group, says
SENTENCE: The strongest geographic divide on the 2023 map
ANSWER:
```

Raw reply:

```json
{"head": "says", "args": ["The strongest geographic divide on the 2023 map"]}
```

### Call 14 — TEXT B, statement a6a98868fa134ec79a2ab5eb (https://pmc.ncbi.nlm.nih.gov/articles/PMC11122111/)

seconds **6.6** · usable **yes** — usable: schema-valid, every argument passed the span check

Input sent:

```text
Turn ONE sentence into ONE expression: a head and its arguments.
The head is one word that says what kind of statement it is.
Every argument must be copied exactly from the sentence, or be a number that appears in it.
Never use the whole sentence as an argument. If the sentence states nothing (a menu, a button, a phone number, a heading), answer with head "NONE" and no arguments.

Example 1
SENTENCE: The Government of Sudan signed a ceasefire agreement in Jeddah in May 2023.
ANSWER: {"head": "commits", "args": ["Government of Sudan", "ceasefire agreement", "Jeddah", "May 2023"]}

Example 2
SENTENCE: Child wasting affected 6.6 percent of children under five worldwide in 2024.
ANSWER: {"head": "obs", "args": ["Child wasting", 6.6, "percent of children under five", "worldwide", "2024"]}

Example 3
SENTENCE: Skip to content
ANSWER: {"head": "NONE", "args": []}

Suggested heads (you may use another): event, claim, commits, causes, increases, decreases, located-in, part-of, affects-group, says
SENTENCE: The path that ends AIDS: UNAIDS Global AIDS Update 2023.
ANSWER:
```

Raw reply:

```json
{"head": "says", "args": ["The path that ends AIDS: UNAIDS Global AIDS Update 2023."]}
```

### Call 15 — TEXT B, statement 2131e750b7d0d0e1f4c7ed36 (https://data.un.org/Data.aspx?d=PopDiv&f=variableID%3A65)

seconds **6.9** · usable **yes** — usable: schema-valid, every argument passed the span check

Input sent:

```text
Turn ONE sentence into ONE expression: a head and its arguments.
The head is one word that says what kind of statement it is.
Every argument must be copied exactly from the sentence, or be a number that appears in it.
Never use the whole sentence as an argument. If the sentence states nothing (a menu, a button, a phone number, a heading), answer with head "NONE" and no arguments.

Example 1
SENTENCE: The Government of Sudan signed a ceasefire agreement in Jeddah in May 2023.
ANSWER: {"head": "commits", "args": ["Government of Sudan", "ceasefire agreement", "Jeddah", "May 2023"]}

Example 2
SENTENCE: Child wasting affected 6.6 percent of children under five worldwide in 2024.
ANSWER: {"head": "obs", "args": ["Child wasting", 6.6, "percent of children under five", "worldwide", "2024"]}

Example 3
SENTENCE: Skip to content
ANSWER: {"head": "NONE", "args": []}

Suggested heads (you may use another): event, claim, commits, causes, increases, decreases, located-in, part-of, affects-group, says
SENTENCE: ADB region: Central and West Asia 2056 Medium 7.034
ANSWER:
```

Raw reply:

```json
{"head": "says", "args": ["ADB region: Central and West Asia 2056 Medium 7.034"]}
```

### Result

| text | usable | seconds per call | wired |
|---|---|---|---|
| A | 1/5 | 34.0, 19.1, 13.5, 19.7, 17.8 | **NO** — under 3 of 5; reported, not edited (§19) |
| B | 4/5 | 8.2, 5.8, 6.0, 6.6, 6.9 | yes (Part 2, f376de5) |
| C | 5/5 | 10.1, 10.3, 11.0, 9.7, 9.4 | yes (Part 2, f376de5) |

What the numbers do not show:
* **TEXT A** drifted where facts were thin: two needs had 0 or 2 fact lines from the sub-goal
  filter; replies restated the question ("What are the most pressing issues based on the
  provided data?") or wandered off the facts. The one usable reply named actors taken from junk
  pages (Criminon International, NARCONON) — usable by the rule, not by sense.
* **TEXT B**: several "usable" replies put the whole sentence in one `says` argument, which
  TEXT B forbids; the span check does not catch it. Part 2 added a mechanical check
  (`symbols.whole_sentence`) with a mutation test. The refusal was
  `located-in ["Europe", "the sea"]` — "the sea" is not a span.
* **TEXT C**: all five STILL_OPEN; four gave a narrower question, some still vague ("which
  specific issues are most pressing?"), one copied the example's question word for word
  ("which measured environmental conditions worsened most in 2025, and where?").

