# The single-shift POS model

How a restaurant branch runs its POS after this change: **one shift per branch,
opened by a cashier or manager, with captains taking orders under it, billing by
cashier/manager, and one closing at the end of the day.**

Branch: `feat/single-shift-pos`, based on `version-2` of
`Techwise-Africa/URYPOSV2` (URY `3.0.0-beta.1`, Frappe 15, ERPNext 15).

---

## 1. Objective

Before this change the POS treated a shift as a personal possession: any user
who logged in was pushed through a POS Opening Entry, captains included. In
practice that produced:

- **Fragmented money.** Several opening entries per branch per day, each with
  its own drawer, invoices and closing. Deciding whose cash was whose meant
  reconciling entries the staff never intended to create.
- **Captains managing money they don't handle.** A captain taking table orders
  had to open (and later close) a shift even though billing is done at the
  counter.
- **Stranded work.** If a captain's entry was left open, or an order was left as
  a draft, the closing either refused or silently omitted it, and unfinished
  business accumulated on the branch.
- **Ambiguous accountability.** "Who owns this invoice?" had no stable answer,
  because ERPNext only consolidates invoices whose `owner` matches the person
  closing.

**Goal:** one unambiguous shift per branch; captains take orders freely under
it; the cashier or manager opens, bills and closes; nobody can work a closed
POS; and every invoice, opening and closing traces back to one accountable
person.

Explicit constraint: **no DocType or schema changes.** Everything below is
implemented with hooks, existing fields, and client behaviour.

---

## 2. Decisions

| # | Decision | Alternative rejected | Why |
|---|---|---|---|
| 1 | **One open shift per branch.** A second POS Opening Entry for the same branch is refused on submit. | Per-user shifts; the legacy main-cashier / sub-cashier room topology. | "The open shift" must be unambiguous, since every invoice and the closing attach to it. Multi-cashier mode stays off (see §6). |
| 2 | **Invoices belong to the shift's opener.** `owner` is stamped to the opener; the captain stays in `waiter`. | Reimplement ERPNext's closing selection by branch/cashier, or override its `validate_pos_invoices`. | ERPNext's POS Closing only accepts invoices whose `owner` is the closing user, and its query filters on `owner`. Stamping is a 5-line change; overriding the closing is a large, risky fork. |
| 3 | **Captains never open, close or declare amounts.** Only billing users do. | Letting captains open a shift and hand it to the cashier. | Removes money handling from the role that doesn't handle money, and removes orphan shifts when a captain leaves. |
| 4 | **Any billing user may close the branch shift**, and the closing is recorded under its opener. | Only the opener may close (upstream behaviour). | The person present at closing time may not be the opener; refusing would strand the shift. |
| 5 | **Closing is refused while unbilled drafts exist**, with the table names listed. | Closing and silently dropping drafts. | A draft owned by the opener would never appear in any closing once the shift ends — its revenue would vanish. |
| 6 | **The server refuses order creation with no open shift.** | Relying on the UI gate alone. | The client gate is UX; an already-open tab, a stale bundle or a direct API call must still fail safely. |
| 7 | **No open shift ⇒ every screen is blocked for everyone.** Billing user sees the open-shift form; captain sees a waiting screen. | Gate only "transactional" routes and let dashboard/settings render. | First implementation exempted some routes; a cashier could wander the app with no shift, which is exactly the confusion this removes. See `docs/gotchas.md`. |
| 8 | **The Opening checklist gates before the shift form.** | Checklist after a shift exists (upstream order). | The log is per POS Profile per day, so it is opening work; gating before avoids an open shift whose opener is then stuck on a checklist. |
| 9 | **Captains are routed out of the cashier shell** to `/order` and cannot reach dashboard/register/orders/settings. | Leaving routing to the user (upstream default). | The cashier shell exposes money actions and screens irrelevant to a captain. |
| 10 | **The waiting screen offers Retry only**; no polling. | Auto-polling while blocked. | The status check flips a full-screen loading state, so polling would visibly flicker without a new "silent refresh" path. |
| 11 | **`custom_enable_multiple_cashier` must stay OFF.** | Maintaining both models in the client. | The client is now single-shift by design; the server retains the legacy branch for other installations. |
| 12 | **Audit via the Desk trail**, no new fields. | Adding `billed_by` / `billed_at` fields. | No schema changes allowed; `owner`, `waiter`, `modified_by` and Version history already tell the story. |

The invoice-ownership decision has its own record:
`docs/adr/0001-invoice-ownership-is-the-shift-opener.md`.

---

## 3. How it works now

### 3.1 Opening (cashier or manager)

1. The branch has no open shift, so every route is gated.
2. A billing user is asked to complete today's **Opening checklist** (only if
   the POS Profile defines one and today's log isn't `Complete`).
3. They then see the open-shift form, declare payment-mode opening balances and
   submit.
4. `POS Opening Entry.before_submit` runs
   `validate_single_shift_per_branch()`: if another `Open`, submitted entry
   already exists for the branch, the submit is refused with its name.
5. On success the entry is the branch's shift. Its `user` is the **opener**.

Captains skip steps 2–3 entirely; they only ever see the waiting screen while
the POS is closed.

### 3.2 Taking orders (captain)

1. Captain opens `/order` (the captain module), chooses a table, adds items and
   sends.
2. `sync_order()` resolves the branch's open shift with
   `_open_shift_for_branch()`. **No shift ⇒ `frappe.throw` — "The POS is closed
   for branch X…"** The order is not created.
3. For a **new** invoice in single-shift mode:
   - `cashier` = the shift's opener,
   - `waiter` = the session user (the captain),
   - after insert, `owner` is rewritten to the opener
     (`frappe.db.set_value(..., update_modified=False)`), because Frappe stamps
     `owner` with the session user.
4. Updates to an existing invoice keep the original `owner`, so re-saving a
   table's order never re-attributes it.

### 3.3 Billing (cashier or manager)

1. Billing happens on the cashier surfaces (`/tables`, `/orders`, register),
   using `make_invoice()`.
2. Nothing in the billing path rewrites `owner`; the invoice still belongs to
   the opener, while Version history records who actually billed
   (`modified_by`).
3. `getPosProfile()` now reports the **opener** as the profile's cashier, so the
   UI names the person whose shift owns the money even when a different billing
   user is logged in.

### 3.4 Closing (cashier or manager)

1. Any billing user opens the close dialog. `POSClosingDialog` selects the
   branch's open shift (not the session user's own) and loads that shift's
   invoices by `owner = opener`.
2. Client-side, the dialog records the closing under the **opener**
   (`user: openingEntry.user`), not under whoever clicked.
3. Server-side `validate()` runs, in order:
   - `populate_pos_transactions()` — fills `pos_transactions` from submitted,
     not-yet-consolidated invoices whose `owner` is the opener and whose
     posting date falls inside the shift, and computes `grand_total`,
     `net_total` and `total_quantity` when the client didn't.
   - `calculate_closing_amount()` / `validate_cashier()` — existing validation.
   - `validate_no_open_orders()` — refuses while the branch has draft POS
     Invoices, listing their tables.
4. On submit, ERPNext consolidates the referenced invoices (the existing,
   unmodified behaviour) and the shift's POS Opening Entry becomes `Closed`.

### 3.5 Failure modes, and what the user sees

| Situation | Result |
|---|---|
| Captain takes an order with no shift | Server refuses: "The POS is closed for branch X. Ask the cashier or manager to open a shift." |
| Anyone opens any page with no shift | Cashier: open-shift form. Captain: "Shift not open yet" waiting screen with Retry. |
| A second shift for the branch | Refused: "Branch X already has an open shift (POS-OPE-…). Close it before opening a new one." |
| Close with unbilled orders | Refused: "Cannot close: these tables still have unbilled orders — T1, T2. Bill or cancel them first." |
| Shift closed while a captain has the app open | The next order attempt hits the server guard and shows the POS-closed message; the captain retries after the cashier reopens. |
| Billing user opens `/tables` and then closes the shift | The gate re-evaluates and blocks the app until a shift exists again. |

---

## 4. Enforcement map

| Concern | Where | When |
|---|---|---|
| Shift is branch-level, not per user | `POSOpeningProvider.tsx` (reads `get_open_pos_opening_entries`) | every mount / status check |
| No screen without a shift | `POSOpeningProvider.tsx` (universal gate) | render |
| Captains out of the cashier shell | `AppLayout.tsx` + `lib/billing.ts` | render of any cashier route |
| One shift per branch | `ury_pos_opening_entry.validate_single_shift_per_branch` via `hooks.py` `before_submit` | submit |
| No orders without a shift | `ury_order._open_shift_for_branch()` in `sync_order` | order create/update |
| Invoice owner = opener | `ury_order.sync_order` (`is_new_invoice`) | insert |
| Closing recorded under opener | `POSClosingDialog.tsx` (`user: openingEntry.user`) | close submission |
| Closing carries its invoices | `ury_pos_closing_entry.populate_pos_transactions` | `validate` |
| No closing with drafts | `ury_pos_closing_entry.validate_no_open_orders` | `validate` |
| Cashier shown as the opener | `ury_pos/api.getPosProfile` | profile fetch |

No DocType JSON, no schema migration, no client-side persistence changes.

---

## 5. Data and audit footprint

- **POS Opening Entry** — unchanged. `user` = opener; `status`/`docstatus` carry
  the open state.
- **POS Invoice** — unchanged fields, new meaning for one: `owner` = opener
  (shift), `waiter` = captain (order), `cashier` = opener. `modified_by` +
  Version history = who edited/billed.
- **POS Closing Entry** — unchanged; now always populated with
  `pos_transactions` by the server and recorded under the opener.

Reporting consequences: "sales per captain" must read `waiter`; "who touched
this invoice" must read `modified_by` / Version history. `owner` answers "which
shift owns this money".

---

## 6. Known limitations / deliberately out of scope

- **Multi-cashier is unsupported in the client.** The provider takes the
  branch's first open entry as *the* shift regardless of
  `custom_enable_multiple_cashier`. Keep that flag OFF (see `docs/gotchas.md`);
  re-enabling it means restoring the per-user check.
- **`get_production_units_for_branch` does not exist** in this branch, so
  `KotAlertListener` gets a 417 and KOT-error toast monitoring stays inactive.
  Unrelated to the shift work and left untouched.
- **No automatic unlock.** Captains refresh via Retry when the cashier opens the
  shift.
- **Captain module styling is upstream.** The `/order` surface is URY's
  mobile-first captain UI and was not modified here; the difference from the
  cashier table screen is by URY's design.
- **Earlier verification left test data** on the local bench (extra invoices and
  closings). Not part of the code change.

---

## 7. Verification performed (real bench, real users)

Site `ury.localhost`, POS Profile `Havenflow`, users `cashier@`,
`manager@`, `waiter@` (captain). End-to-end script exercised the public
endpoints (`sync_order`, `make_invoice`) and the hooks:

| Check | Result |
|---|---|
| Captain order with no shift | blocked — POS closed |
| Cashier opens shift | `POS-OPE-…` Open |
| Captain order under it | invoice `owner` = cashier, `waiter` = captain, `cashier` = cashier |
| Manager opens a second shift | blocked — branch already has an open shift |
| Close with a draft order | blocked — unbilled tables listed |
| Cashier bills the captain's order | invoice Paid, `owner` unchanged, `modified_by` = cashier |
| Cashier closes | closing Submitted, invoice pulled in, totals server-computed |

Frontend: `npx tsc --noEmit` clean; `yarn build` succeeds (bundle assets are
gitignored). Browser-level checks (redirect, waiting screen, close dialog) were
confirmed manually per user role.

---

## 8. Related documents

- `CONTEXT.md` — glossary (Shift, Opener, Billing user, Captain, Waiter, Draft,
  Closing, Join, Closed POS).
- `docs/adr/0001-invoice-ownership-is-the-shift-opener.md` — why `owner` is the
  opener.
- `docs/gotchas.md` — operational traps: multi-cashier flag, owner meaning, the
  missing production-units endpoint, captain routing, checklist timing.
- `docs/default-customer.md` — how new orders inherit the POS Profile's
  customer.
