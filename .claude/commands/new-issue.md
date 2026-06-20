Start a new feature or bug fix the right way.

EVERY new issue — no matter how small — must follow these steps in order.
Never start implementing before completing steps 1–3.

## Step 1 — Design chat
Ask the user:
- What problem are we solving? What's the desired behaviour?
- Are there constraints (performance, UX, backward compat)?
- Any approaches we should consider or rule out?

Discuss the options briefly (2–3 sentences each), make a recommendation with the main trade-off, and wait for the user to agree on a direction before moving on.

## Step 2 — Plan
Write a short implementation plan:
- What files change and why
- Any edge cases or risks
- Estimated scope (small / medium / large)

Present it to the user and get explicit sign-off ("ok", "go", "yes", etc.) before touching any code.

## Step 3 — Branch
Create a well-named feature branch off main:
  git checkout main
  git pull
  git checkout -b feature/<short-kebab-description>

Tell the user the branch name.

## Step 4 — Implement
Only now write code. Follow the agreed plan. If you discover something that changes the plan materially, pause and discuss before proceeding.

## Step 5 — PR
When done, commit and open a PR as usual.
