# Codex / GPT SOL prompt — Milestone 5 calibration

Paste the block below into **Codex with computer use** (GPT SOL). Cursor cannot open Google Maps and click the review desk; this agent can.

Work on this machine, in this folder. The GUI is on local branch `calibration-review-gui` and may not be on GitHub yet. Do not clone `master`.

```xml
<task>
Complete Customer Finder Milestone 5 (Wrocław human calibration) on the local Windows machine using the localhost review-desk GUI. Do not fill reviews from memory or from Overture CSV guesses. For every lead, open Google Maps, inspect the place, then click the five review fields in the GUI.

Repository: D:\adasj\Documents\CustomerFinder
Branch: calibration-review-gui
GUI command: finder calibration gui
GUI URL: http://127.0.0.1:8765/

Done means:
1. venv installed and GUI running
2. live 3 km Wrocław search finished (or existing leads loaded if already present and complete_count is 0)
3. all 30 cards have complete five-field reviews grounded in Maps evidence
4. Evaluate clicked
5. final report includes pass/fail plus the numbers from the evaluate panel and from out/calibration.summary.json
</task>

<default_follow_through_policy>
Default to the most reasonable low-risk interpretation and keep going.
Only stop to ask questions when Maps is blocked (login, captcha, consent wall you cannot pass), the GUI will not start, or an irreversible action is required (git push, merge, force overwrite of existing human reviews).
If out/calibration.csv already has saved reviews, do not overwrite them. Continue empty ranks only.
</default_follow_through_policy>

<completeness_contract>
Resolve all 30 ranks before evaluate.
Do not stop after a few sample rows.
Do not skip a lead because the Overture bucket already looks right.
If a Maps listing is ambiguous, mark the relevant fields uncertain and write a short note. Do not invent a website or an independent/chain decision.
</completeness_contract>

<verification_loop>
Before finalizing:
1. Confirm GUI status-text shows COMPLETE 30 / 30.
2. Click btn-evaluate and read the evaluate panel.
3. Open out/calibration.summary.json and confirm the same passed / top20.target_precision / top20.no_site_precision numbers.
4. If evaluate errors because a row is incomplete, go back to that rank and finish it, then evaluate again.
5. Do not claim PASSED unless both the panel and the JSON say passed=true.
</verification_loop>

<grounding_rules>
Ground every review in what you actually saw on Google Maps (name, category, open/closed, chain vs independent, website / social / none).
Overture fields on the card (bucket, owned_domains, socials, is_chain) are hints only. They may be wrong. Do not copy them blindly.
If Maps shows an owned domain, choose owned_site even if there are also Facebook/Instagram links.
If there is no owned domain but there is Facebook/Instagram/TikTok, choose social_only.
If there is no owned domain and no socials (or only aggregators like pyszne.pl / Google), choose no_owned_site.
Never assume no_owned_site without looking.
If you cannot see the listing, use uncertain and say so in notes.
</grounding_rules>

<action_safety>
Keep changes tightly scoped to Milestone 5 review data under out/.
Do not commit out/, .env, or API keys.
Do not run --enrich google.
Do not change scoring, YAML, or thresholds to make the gate pass.
Do not merge PRs or tag v0.1.0.
Do not bind the GUI to 0.0.0.0.
Do not click chk-overwrite unless the user already confirmed destroying existing reviews.
</action_safety>

<computer_use_playbook>
Setup:
1. Open PowerShell.
2. cd D:\adasj\Documents\CustomerFinder
3. git status and confirm branch calibration-review-gui (or that src/customer_finder/calibration_gui.py exists).
4. If needed:
   $py = "D:\adasj\Programs\Python312\python.exe"
   if (!(Test-Path .venv)) { & $py -m venv .venv }
   .\.venv\Scripts\Activate.ps1
   pip install -e ".[dev]"
5. Start the GUI and leave it running:
   finder calibration gui --no-open-browser --port 8765
6. Open Chrome/Edge to http://127.0.0.1:8765/
7. Confirm the page title contains "biurko kalibracji" and #status-text is visible.

Search:
- If status-text shows RANK of 0 or "Brak kart", click #btn-search ("Uruchom wyszukiwanie 3 km").
- Defaults are already Wrocław 51.1079, 17.0385, 3 km, cafe,bakery,pastry,ice_cream.
- Wait until #busy overlay disappears and status-text no longer says JOB running. First Overture run may take several minutes.
- Do not start a second search.

Review loop for ranks 1..30:
1. Click #rank-item-N if not already on that card.
2. Read #place-name and #place-meta.
3. Click #btn-open-maps. Inspect the Maps tab: identity, category, open/closed, chain, website.
4. Return to the GUI tab.
5. Click exactly one button in each group:
   - #field-entity_status-valid | #field-entity_status-wrong_entity | #field-entity_status-uncertain
   - #field-target_category-yes | #field-target_category-no | #field-target_category-uncertain
   - #field-operating_status_review-open | #field-operating_status_review-closed | #field-operating_status_review-uncertain
   - #field-independence-independent | #field-independence-chain | #field-independence-uncertain
   - #field-site_status-owned_site | #field-site_status-social_only | #field-site_status-no_owned_site | #field-site_status-uncertain
6. Optional: put evidence in #notes (URL seen, "sieć XYZ", "tylko Facebook").
7. Click #btn-save-next.
8. If #status-text starts with ERROR, fix the five fields and save again.
9. Close extra Maps tabs as you go so you do not mix places.

Evaluate:
- Click #btn-evaluate.
- Read #evaluate-panel. PASSED requires complete_rows=30, top20.target_precision>=0.80, top20.no_site_precision>=0.70.
- If FAILED, do not tweak code. Report which ranks are not valid-open-independent target businesses or have owned sites, with Maps evidence.

Target-category yes means cafe, bakery, pastry shop, or ice cream shop. A restaurant, grocery, bar, or hotel is no.
</computer_use_playbook>

<structured_output_contract>
Return exactly this shape and nothing else.

## Result
- passed: true|false|blocked
- complete_rows / expected_rows
- top20.target_precision
- top20.no_site_precision
- approved_path or none

## Setup evidence
- branch / GUI URL / whether search ran

## Blockers
- captcha/login/GUI crash, or none

## Notes on uncertain or wrong-entity rows
- rank, name, chosen fields, what Maps showed

## Do not
- do not include a full 30-row dump unless passed is false or blocked
</structured_output_contract>

<progress_updates>
If you provide progress updates, keep them brief and outcome-based.
Example: "search done, 30 cards" / "reviewed 10/30" / "evaluate failed, going back to rank 4".
</progress_updates>
```
