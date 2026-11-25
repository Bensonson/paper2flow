# Reconstructing a paper's procedure

## What a node represents

A node is a meaningful experimental or analytical action: recruit a cohort, prepare samples, estimate a model, evaluate against a baseline, or compare outcomes. A paper section, a background concept, a citation, or a sentence is not automatically a step.

Do not create standalone nodes for trivial bookkeeping, such as preparing a text prefix, attaching an existing embedding, copying records or passing inputs onward. Explain the necessary preparation briefly inside the labeling, fitting or analysis step that uses it. If collapsing a node, carry its supporting evidence into the consuming step and reconnect only the inputs each consumer actually needs. Attribute algorithms and tools to operations that execute them, not to preparation that merely handles their inputs or outputs. Keep different experimental arms separate when they have different inputs, methods, or results. A review paper or commentary may have no recoverable experimental workflow; explain that limitation rather than fabricating one.

## Choose the level of a complete method

A nontrivial rule is not automatically a standalone step. Ask what scientific or analytical job the reader is trying to understand. Prompting three times, taking a majority label and excluding three-way disagreement belong inside one annotation procedure. Similarly, category generation, matching and definition can be phases of category construction; regularization selection, participant-separated fitting and probability prediction can be phases of decoding. Explain their internal order and distinct training/test pools in the task, parameters and evidence, rather than presenting each phase as another major method.

Keep a separate node when it serves a distinct explanatory purpose: an independent input branch, a method with a separately needed product, or an independent scientific comparison or validation. Having its own algorithm, tool call, threshold or intermediate artifact is insufficient by itself. Avoid flattening distinct experiments merely to reduce the count.

Audit the entire proposed graph before rendering. For every adjacent pair, ask whether readers need two methods or one method with two internal actions. Merge fragmentary pairs, then review the resulting graph again, preserving evidence, parameters, findings, meaningful branches and precise dependencies. Verify that each node's tool actually executes part of that node, and that downstream outputs are not presented as an operation already performed upstream.

## Write tasks that explain the method

Write for an interested reader who has not already learned this paper's method. A title should identify the concrete operation and object; the task should add an explanation, not repeat that label in more words. Explain the problem being solved, the input being changed or compared, the rule used, and what the result enables next. Include detail in proportion to the operation; extra length alone does not make an explanation useful.

Introduce essential terms at first use. For example, explain an embedding as a list of numbers representing text meaning before saying that candidate embeddings occupy a semantic space. Explain the decision being optimized before naming its algorithm or giving its equation. Retain named methods, exact parameters, evidence and uncertainty without letting them displace the explanation.

Weak: “Select a non-overlapping human utterance path.”

Better title: “Choose where to split each person's narrative.”

Better task opening: “The previous steps proposed several possible text chunks and scored each against reference sentences. Compare combinations that follow the person's original word order without reusing words, and choose the combination with the highest total score. This produces the sequence of chunks that will receive event labels.” Then explain the paper's length weighting, dynamic programming and any unresolved coverage rules.

Before delivery, read each title and task together without relying on the graph or adjacent steps. Can an unfamiliar reader say what is being acted on, what actually happens, and why the output matters? Rewrite descriptions that require the reader to already understand the procedure. Check both language versions; a fluent translation of an opaque description still fails this check. This is an editorial check, not something schema validation establishes.

## What an edge asserts

`B.depends_on = ["A"]` asserts that B needs something produced or established by A. Include direct prerequisites. Avoid transitive edges unless they communicate a separate direct requirement.

- **Explicit:** the paper states the relationship, such as evaluating weights trained in an earlier step. Include the source passage.
- **Inferred:** the relationship is necessary to reconstruct the procedure but is not directly stated. Explain the supplied input or constraint and mark the uncertainty. An inference must still be grounded in the paper.

Two analyses performed on the same cohort can be parallel children of cohort preparation. Their placement in consecutive paragraphs does not make one dependent on the other. A comparison can consume both branches. Feedback described in an iterative optimization loop usually belongs inside one step; the report graph depicts prerequisites between major steps and must be acyclic.

## Connect methods and results

For each step, look for corresponding Results paragraphs, figures, tables, and captions. Keep outcomes attached to the action that produced them.

| Field | Appropriate content |
| --- | --- |
| outputs | Cleaned feature matrix; fitted weights; effect estimate with units |
| findings | The reported treatment group differed from the control; include uncertainty and conditions |
| parameters | Sample size, split definition, thresholds, units, hyperparameters explicitly reported |
| algorithm | Named statistical tests, mathematical models, or learning algorithms |
| software | Explicitly named packages, applications, libraries, or pretrained models |

Do not invent a software library from the algorithm name, infer missing hyperparameters from common defaults, or turn an association into a causal claim. Preserve negative findings, limitations, confidence intervals, and out-of-sample versus training distinctions when relevant.

## Evidence and uncertainty

PDF `page` values are physical PDF page numbers starting at 1, matching extraction markers; printed page labels can go in `section`. For TXT/Markdown use `page: null` and a real section or `[line N]` range. A section locator should identify where to check, not merely say “the paper”.

Quotes should be short exact excerpts. Keep excerpts in their original language even when descriptions are translated. The deterministic validator checks structure and page ranges; the host agent must check that quotes exist in the source and support the claims. Never suggest that passing validation proves scientific correctness.

When an unreported field is genuinely absent, leave its array empty or its finding null. If extraction missed pages or a supplement is unavailable, describe the resulting coverage gap in `notes`. Do not promote an uncertain link to `explicit` just to make the diagram look complete.

For competing interpretations, choose a defensible conservative graph and state the uncertainty. Request clarification only when it materially prevents useful analysis. Keep human-readable explanations concise; hidden reasoning traces are neither required nor part of the output.
