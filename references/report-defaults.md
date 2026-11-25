# Default report behavior

These defaults apply to new reports and report repairs unless the user explicitly requests different behavior. The bundled renderer and local server implement the behavior; do not repeat per-paper patches.

## Authoring and language

- Write the English primary directly against the original paper, including its Methods, relevant Results, figures, captions and supplements. For an English paper, do not derive the English account by back-translating a Chinese summary.
- Translate that English account into Chinese. Keep the same node IDs, graph, parameter values and meanings, source metadata and exact original-language evidence. Missing information stays missing in both versions.
- Default the interface and content to English. The Chinese control changes all report content, including download, print and node question context. Translate every explanatory field; preserve proper technical names where appropriate.
- If a translation is unavailable, disclose that state; a translated toolbar must not be presented as a translated report. Explicit user language requests override defaults.
- A methodological explanation remains an explanation. Do not train a model, build a scientific pipeline or select a research schema unless separately requested.

## Local Codex and continuity

- Set up the bridge for the user with the installed CLI and existing login. Bind the original PDF automatically. Avoid manual address/token/PDF entry during normal use; relocation is appropriate only for a missing or moved original.
- Keep tokens in runtime memory, never in the saved HTML, workflow exports or mirrored files. Serve on loopback only, retaining bearer authentication and source checks.
- Deliver a reusable launch entry which starts or reuses the report's own service, checks readiness and opens its actual URL. Detect port conflicts rather than killing another service. Starting the page must not run a model or require a new API key.
- **Ask Codex** begins a new topic for the selected node. **Follow up** sends the completed questions and answers from that node together with the current question and original PDF. Prior answers are conversation context, not verified source evidence.
- Separate history by source identity, node ID and PDF binding. Keep it when switching nodes or display languages. Failed requests must not erase successful history. Show completed turn counts and reviewable history.
- State history lifetime explicitly: browser page memory until refresh/close. Warn before recommending a refresh that would lose useful exchanges. Do not silently truncate history when limits are reached; reject with an actionable message.

## Canvas interactions

- Vertical wheel zoom is anchored to the pointer and gentle: approximately 5% maximum change per wheel event, normalizing pixel/line/page deltas.
- A horizontal wheel pans horizontally without zooming. Shift plus vertical wheel is an alternative horizontal pan gesture. Handle deltaX explicitly.
- Dragging empty canvas space pans it and prevents native text selection. Node labels are not selectable while interacting with the canvas. Text in the separate detail/evidence panel remains selectable and copyable.
- Keep node activation, keyboard pan/zoom, search, filters and existing readable layout available.

## Source colors and merges

- Assign a stable color to each independent input root. Its outgoing arrows and node provenance strip use that color in light and dark themes.
- Selecting a node may change emphasis, opacity or thickness; it must not replace source colors with generic upstream/downstream colors. Arrowheads use the same source paint as the corresponding path.
- For `a -> c`, `b -> c`, `c -> d`, retain the individual colors on the two incoming arrows and use their gradient on `c -> d`. Continue propagating the union of source origins downstream, deduplicating an origin that arrives along multiple paths.
- Include every distinct origin in merged gradients: three, four, five, 100 or more. Generate additional colors rather than cycling a short fixed palette. Path, arrowhead and node strip must preserve the full set of stops.
- Keep colors stable across node selection, theme and focus filters. A legend explains that provenance colors do not encode weights, probability, effect size or execution order by themselves. Direction and graph dependencies determine prerequisite order.

## Acceptance checks

Run the bundled deterministic regression check after changing the renderer or bridge:

```bash
python3 <skill>/scripts/check_report_defaults.py --node /absolute/path/to/node
```

Node is detected automatically when available; the runner explicitly reports a skipped DOM suite when it is absent. The checks create a temporary second-paper PDF and service, use a fake answer executor without model calls, and clean up afterward. They verify executed JavaScript/HTTP behavior; they do not replace source reading or visual browser review.

Before delivery, verify the actual new-paper output rather than only the earlier VECTOR report:

1. Default English and full Chinese content switching, including selected node details, notes, print/export and question context. Reject changed source/evidence/topology in a purported translation.
2. A fresh report's launch entry starts or reuses its own service and opens a verified page. The bridge auto-connects without manual fields; saved files contain no runtime token. Unauthenticated or foreign-origin API requests remain blocked.
3. A two-turn node question includes the earlier user question and answer. Switching to another node does not send that history; returning restores it. A fresh topic and a failed follow-up behave as labeled. No paid model calls are required for deterministic bridge tests.
4. Pixel/line/page wheel inputs stay gentle. Horizontal and Shift-wheel inputs pan without zoom. Drag/release/cancel do not select text or leave a stuck drag state.
5. In both themes, select a merge and confirm that an orange input stays orange. Verify 3-, 4-, 5- and 100-origin gradients preserve every color and deduplicate repeated origins. Keep selected/upstream/downstream emphasis separate from provenance.
6. Check syntax, console errors, offline browsing, source evidence, focus filters and narrow widths. Distinguish structural checks, browser checks and paper-evidence verification in delivery notes.
7. Read every node title and task as a reader unfamiliar with the method. The pair must explain the concrete input, operation and purpose; a restated title or unexplained technical label fails. Check the full translation as well as the primary account, using the analysis guide's reader check.

8. Audit all node boundaries for complete methodological operations. Merge annotation repetitions and voting into labeling, and other internal rules into their parent method. Check every adjacent pair across the whole graph; a separate threshold, tool call or intermediate output alone does not justify a node. Preserve independent branches and validation designs.
