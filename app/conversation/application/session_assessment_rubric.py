# 세션 수준 평가의 5개 영역별 1~100점 루브릭을 정의하는 모듈

SESSION_LEVEL_ASSESSMENT_RUBRIC = """Level Assessment Rubric:
Give an integer score from 1 to 100 for each OBSERVED domain, independently.
These are direct evidence-based scores, not converted five-level ratings.
Choose the matching performance band below, then judge control within that band:
- bottom 1-6 points of a band: emerging, inconsistent performance with substantial limitations;
- middle 7-13 points: generally demonstrated but with identifiable lapses or limited flexibility;
- top 14-20 points: consistent, independent control of that band's descriptors.
Use the full integer range; do not default to band midpoints or multiples of 20.
Compare accuracy, completeness, precision, coherence, or pragmatic appropriateness only within the named domain.
A one-point difference is a rubric judgment, not a statistically validated measurement.
Reserve 100 for consistently exceptional observed control; task completion alone never warrants 100.
The backend combines scores and maps them to learning levels 1-5; do not output a learning level.

Situation performance (situationPerformance):
1-20 = only isolated related words; cannot complete the task.
21-40 = basic intent is conveyed, but important information or help is missing.
41-60 = the core task is completed, including requested reasons or details when applicable.
61-80 = multiple requirements are handled and the answer adapts to conditions.
81-100 = complex alternatives are handled through negotiation or persuasion.

Grammar:
1-20 = isolated words with no sentence control.
21-40 = simple sentences with limited control.
41-60 = common structures are mostly accurate.
61-80 = varied structures are mostly accurate.
81-100 = complex structures are used flexibly and consistently.

Vocabulary:
1-20 = only basic words are available and expression is very limited.
21-40 = basic vocabulary is repetitive or imprecise.
41-60 = everyday vocabulary is used, with paraphrase when needed.
61-80 = precise, natural vocabulary and collocations are used.
81-100 = vocabulary and register are nuanced and flexible.

Discourse:
1-20 = ideas are disconnected.
21-40 = ideas are presented as a simple list.
41-60 = ideas connect coherently to the preceding turn, or reasons, order, and details are connected.
61-80 = ideas develop clearly with reasons and examples.
81-100 = complex ideas are organized with summary and expansion.

Interaction pragmatics (interactionPragmatics):
1-20 = response or help-seeking is very limited.
21-40 = the exchange is basic, direct, or socially inapt.
41-60 = requests, apologies, and refusals are appropriate.
61-80 = register and politeness are controlled and adapted to the situation.
81-100 = sensitive negotiation and disagreement are handled appropriately.

Calibration rules:
An error-free simple answer does not prove high capability.
ACHIEVED means that the task requirements were met; it does not mean an 81-100 score.
A short natural answer is not automatically incorrect, low-level, or insufficient evidence.
Evaluate the response against what this specific question requests, not against the complexity of the question's wording.
For taskPerformance, ACHIEVED means every explicit required element is answered in substance.
PARTIAL requires an identifiable missing required element; do not add unstated reasons, explanations, or the scenario's later goals.
When requiredElements contains the whole question, extract only what the learner is explicitly asked to provide; background and offered alternatives are not additional tasks.
A concise choice, time, or contact preference can be a complete coherent discourse turn in the 41-60 band; do not assign discourse 1-40 solely because there is only one sentence or no explanation was requested.
The discourse 1-20 band requires disconnected ideas and the 21-40 band requires list-like organization; brevity alone proves neither.
Do not assign vocabulary 21-40 solely because the words are common; look for actual repetition or imprecision limiting the answer.
Do not assign grammar 61-80 solely for a correct future tense or infinitive; varied structural control needs evidence.
Appropriate short answers do not automatically earn scores in 61-100. Lack of advanced evidence is not proof that the learner cannot perform at a higher level.
Calibration examples (judge other domains independently):
- Asked 'Would you rather get a text or an email?', 'Please send it by email' achieves the choice and is a coherent discourse turn in the 41-60 band, not disconnected discourse in the 1-20 band. A reason is not required.
- Instructed to report losing a key and ask how to enter, 'I lost my room key. How can I get into my room?' is ACHIEVED; replacement timing and notification preference are later tasks, not missing opening requirements.
- Asked to choose a pickup time, 'Tomorrow morning works for me' is ACHIEVED. Asked 'When, and why that time?', the same answer is PARTIAL because the requested reason is missing.
Use OBSERVED when genuine performance is present and judge it at the score supported by the text.
Use NOT_OBSERVED only when this message offered no opportunity to judge that domain.
Use INSUFFICIENT_EVIDENCE only when relevant evidence is missing because of a technical or processing problem.
An off-topic or short answer is still evidence when it is observable; a related, off-topic, or short answer can still be genuine observed performance when a judgment is possible.
For every OBSERVED domain, evidenceExcerpt must be an exact contiguous substring of the corresponding userMessage; otherwise use null score and null evidenceExcerpt."""


LEGACY_SESSION_LEVEL_ASSESSMENT_RUBRIC = """Level Assessment Rubric:
Use each scale for the named domain, not as an overall proficiency label.

Situation performance (situationPerformance):
1 = only isolated related words; cannot complete the task.
2 = basic intent is conveyed, but important information or help is missing.
3 = the core task is completed, including requested reasons or details when applicable.
4 = multiple requirements are handled and the answer adapts to conditions.
5 = complex alternatives are handled through negotiation or persuasion.

Grammar:
1 = isolated words with no sentence control.
2 = simple sentences with limited control.
3 = common structures are mostly accurate.
4 = varied structures are mostly accurate.
5 = complex structures are used flexibly and consistently.

Vocabulary:
1 = only basic words are available and expression is very limited.
2 = basic vocabulary is repetitive or imprecise.
3 = everyday vocabulary is used, with paraphrase when needed.
4 = precise, natural vocabulary and collocations are used.
5 = vocabulary and register are nuanced and flexible.

Discourse:
1 = ideas are disconnected.
2 = ideas are presented as a simple list.
3 = ideas connect coherently to the preceding turn, or reasons, order, and details are connected.
4 = ideas develop clearly with reasons and examples.
5 = complex ideas are organized with summary and expansion.

Interaction pragmatics (interactionPragmatics):
1 = response or help-seeking is very limited.
2 = the exchange is basic, direct, or socially inapt.
3 = requests, apologies, and refusals are appropriate.
4 = register and politeness are controlled and adapted to the situation.
5 = sensitive negotiation and disagreement are handled appropriately.

Calibration rules:
An error-free simple answer does not prove high capability.
ACHIEVED means that the task requirements were met; it does not mean proficiency level 5.
A short natural answer is not automatically incorrect, low-level, or insufficient evidence.
Evaluate the response against what this specific question requests, not against the complexity of the question's wording.
For taskPerformance, ACHIEVED means every explicit required element is answered in substance.
PARTIAL requires an identifiable missing required element; do not add unstated reasons, explanations, or the scenario's later goals.
When requiredElements contains the whole question, extract only what the learner is explicitly asked to provide; background and offered alternatives are not additional tasks.
A concise choice, time, or contact preference can be a complete coherent discourse turn at level 3; do not assign discourse 1 or 2 solely because there is only one sentence or no explanation was requested.
Discourse 1 requires disconnected ideas and discourse 2 requires list-like organization; brevity alone proves neither.
Do not assign vocabulary 2 solely because the words are common; look for actual repetition or imprecision limiting the answer.
Do not assign grammar 4 solely for a correct future tense or infinitive; varied structural control needs evidence.
Appropriate short answers do not automatically earn levels 4 or 5. Lack of advanced evidence is not proof that the learner cannot perform at a higher level.
Calibration examples (judge other domains independently):
- Asked 'Would you rather get a text or an email?', 'Please send it by email' achieves the choice and is a coherent discourse level 3 turn, not disconnected discourse level 1. A reason is not required.
- Instructed to report losing a key and ask how to enter, 'I lost my room key. How can I get into my room?' is ACHIEVED; replacement timing and notification preference are later tasks, not missing opening requirements.
- Asked to choose a pickup time, 'Tomorrow morning works for me' is ACHIEVED. Asked 'When, and why that time?', the same answer is PARTIAL because the requested reason is missing.
Use OBSERVED when genuine performance is present and judge it at the level supported by the text.
Use NOT_OBSERVED only when this message offered no opportunity to judge that domain.
Use INSUFFICIENT_EVIDENCE only when relevant evidence is missing because of a technical or processing problem.
An off-topic or short answer is still evidence when it is observable; a related, off-topic, or short answer can still be genuine observed performance when a judgment is possible.
For every OBSERVED domain, evidenceExcerpt must be an exact contiguous substring of the corresponding userMessage; otherwise use null level and null evidenceExcerpt."""
