# Gotchas

Traps worth knowing before changing POS behaviour in this app. For the
narrative versions — objective, decisions, flow — see
`docs/single-shift-model.md` and `docs/default-customer.md`.

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

## Default customer is a prefill, not a rule

New orders start on `POS Profile.customer` — resolved once by
`resolveDefaultCustomer` in `pos/src/lib/pos-profile-api.ts`, seeded by
`applyProfileDefaults` in the store, and enforced server-side by
`_default_customer_for` in `sync_order`.

It seeds **new orders only**. An existing invoice keeps its customer, Aggregator
orders use the aggregator's customer, and the picker stays editable. Do not
turn the seed into a reactive "if empty, refill": the Change button clears the
field on purpose, and a deliberate clear must survive until the next new order.

The profile field may be empty; then the picker starts blank as before. A
configured-but-disabled or deleted customer blocks the order with a
configuration error naming the profile — it is never silently skipped.

`URY Self Ordering Profile` has its own `default_customer` for QR/kiosk orders.
Two separate defaults by design; do not merge them.

The client sends `""` rather than omitting `customer`; `sync_order`'s signature
still requires the argument, so a caller that omits the key gets a raw
`TypeError` before any default logic runs.

## Opening checklist is per profile per day

`get_checklist` looks up the `URY POS Checklist Log` by POS Profile + type +
today's `shift_date`, so one completion covers every user and every shift that
day. It deliberately gates *before* the open-shift form for billing users; do
not move it after an entry is found or a shift can be opened by someone who is
then stuck on the checklist.

## `bench run-tests` deletes every Item Price

ERPNext runs `before_tests` before the suite
(`erpnext.setup.utils.before_tests`, wired in `erpnext/hooks.py`). It executes
`delete from tabItem Price` and **commits** — outside the test transaction, so
it is not rolled back. The same hook also sets
`Stock Settings.auto_insert_price_list_rate_if_missing = 0`, seeds
`Selling Settings.customer_group` / `territory`, and adds all roles to
Administrator.

Consequence on this bench: running the suite against `ury.localhost` empties
the menu's prices, and the POS then fails with
"No item price found for Item: … in Price List: Default Menu".

Always pass the flag here:

```
bench --site ury.localhost run-tests --module <module> --skip-before-tests
```

If it is ever run without it, restore `Item Price` from the newest database
backup in `sites/ury.localhost/private/backups/` (replay the
`INSERT INTO \`tabItem Price\`` block), and put the settings above back.

