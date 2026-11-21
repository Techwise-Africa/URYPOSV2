# Gotchas

Traps worth knowing before changing POS behaviour in this app. For the
narrative version — objective, decisions, flow — see
`docs/single-shift-model.md`.

## `custom_enable_multiple_cashier` must stay OFF

The POS frontend is single-shift by design: `POSOpeningProvider` treats the
branch's first open `POS Opening Entry` as *the* shift, `sync_order` stamps new
invoices with that shift's opener, and `POSClosingDialog` closes the branch
shift rather than the session user's own.

The server still contains the legacy multi-cashier branch (main cashier / sub
cashier rooms, `Sub POS Closing`). If `custom_enable_multiple_cashier` is set
to 1 on a POS Profile, the backend follows that path while the frontend keeps
the single-shift one — invoices, shift attribution and closing then disagree.
Keep the flag at 0 on every profile this app serves. Re-enabling it means
restoring the per-user shift check in `POSOpeningProvider` first.

## Invoice `owner` is the shift's opener, not the creator

Captains never own invoices: `ury_order.sync_order` rewrites `owner` to the
open shift's opener so ERPNext's POS Closing (which only accepts invoices whose
owner is the closing user) can consolidate them. Use `waiter` for per-captain
reporting and `modified_by` / version history for the audit trail. See
`docs/adr/0001-invoice-ownership-is-the-shift-opener.md`.

## `get_production_units_for_branch` does not exist on this branch

`pos/src/lib/production-api.ts` calls
`ury.ury_pos.api.get_production_units_for_branch`, which is absent from this
codebase (and its git history). Frappe answers a missing whitelisted method
with HTTP **417** ("Failed to get method for command…"). `KotAlertListener`
catches it, so the only effect is that KOT-error toast monitoring stays
inactive — not a page crash. Implement the endpoint (a plain list of
`URY Production Unit` names for the user's branch) if those alerts are needed.

## Captains are pinned to `/order` (our change, not upstream)

Upstream ships two independent table surfaces and never routes between them:
the cashier shell (`AppLayout` + `pages/Table.tsx`, Header/Footer, layout view,
room/seat/status cards) and the captain module (`captain/pages/CaptainTables.tsx`
at `/order`, mobile-first, minimal header, "Free" badges). Both are URY's
design — the captain module arrived upstream in `be185afb feat(captain):
Captain order-taking migration to V2`.

We added the routing: `AppLayout` redirects anyone without a billing role to
`/order` (`pos/src/lib/billing.ts` defines the billing check). Consequence:
captains never see the richer cashier table UI, and the two screens look like
different apps to staff who know both.

If that ever needs to change, the lever is the four-line guard in
`pos/src/components/AppLayout.tsx` — remove it to let captains roam the cashier
shell again, or keep it and restyle `CaptainTables` instead. Do not assume the
captain screen lost features: nothing under `pos/src/captain/` was ever
modified by us, so an upstream rebase will not resurrect a "missing" UI.

## Opening checklist is per profile per day

`get_checklist` looks up the `URY POS Checklist Log` by POS Profile + type +
today's `shift_date`, so one completion covers every user and every shift that
day. It deliberately gates *before* the open-shift form for billing users; do
not move it after an entry is found or a shift can be opened by someone who is
then stuck on the checklist.
