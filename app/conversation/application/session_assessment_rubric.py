# 세션 수준 평가의 5개 영역별 1~5단계 루브릭을 정의하는 모듈

SESSION_LEVEL_ASSESSMENT_RUBRIC = """Level Assessment Rubric:
Use each scale for the named domain, not as an overall proficiency label.

Situation performance (situationPerformance):
1 = only isolated related words; cannot complete the task.
2 = basic intent is conveyed, but important information or help is missing.
3 = the core task is completed with a reason or relevant detail.
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
3 = reasons, order, and details are connected.
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
Use OBSERVED when genuine performance is present and judge it at the level supported by the text.
Use NOT_OBSERVED only when this message offered no opportunity to judge that domain.
Use INSUFFICIENT_EVIDENCE only when relevant evidence is missing because of a technical or processing problem.
An off-topic or short answer is still evidence when it is observable; a related, off-topic, or short answer can still be genuine observed performance when a judgment is possible.
For every OBSERVED domain, evidenceExcerpt must be an exact contiguous substring of the corresponding userMessage; otherwise use null level and null evidenceExcerpt."""
