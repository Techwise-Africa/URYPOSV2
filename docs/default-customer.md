# Default customer from the POS Profile

How new orders start on the profile's customer instead of asking staff to type
it every time: **`POS Profile.customer` seeds every new order for every role,
stays editable, and never rewrites an existing order.**

Branch: `feat/single-shift-pos` (same branch as the single-shift model), based
on `version-2` of `Techwise-Africa/URYPOSV2`.

---

## 1. Objective

Order-taking required a customer on every ticket, but almost every dine-in
ticket is a walk-in. Captains and cashiers retyped or re-picked the same
customer hundreds of times a day, and a busy service could stall on a field
that was effectively constant.

The POS Profile already carries a `customer` link — a standard ERPNext field,
already set to `Walk-In` on `Havenflow` — which nothing in URY read. This
change gives it its obvious meaning: **the customer a new order starts on.**

Constraints: no DocType or schema changes, no new fields, and no forced
behaviour — staff can always change the customer on a ticket.

---

## 2. Decisions

| # | Decision | Alternative rejected | Why |
|---|---|---|---|
| 1 | **`POS Profile.customer` is the source of truth.** | A new `custom_default_customer` field; a global default. | The field already exists and already holds `Walk-In`. Per-profile means per-branch defaults without schema work. |
| 2 | **Prefill only the order screens** — cashier `OrderPanel` and captain `CaptainOrder`. | Every customer picker, including reservations and bill splits. | A reservation is for a named guest with a phone number; a bill split exists to move part of a bill to someone else. Prefilling those would create wrong data, not save typing. |
| 3 | **The server falls back too.** `sync_order` resolves the profile default when the caller sends no customer. | UI-only prefill. | A prefill is convenience, not a guarantee. The rule should hold for API callers and stale clients. |
| 4 | **The default applies to new orders only.** Updates keep the invoice's existing customer unless someone explicitly changes it. | Re-defaulting on every call. | `sync_order` re-assigns `customer` on every call; a naive default would silently turn a named guest into Walk-In mid-order. |
| 5 | **Aggregator orders ignore the default.** The aggregator's customer wins. | Defaulting all order types. | Aggregator attribution already comes from Branch settings; a second source would let the two disagree. |
| 6 | **No usable default fails loudly.** Empty profile field = manual selection as before; configured-but-deleted/disabled customer = a configuration error naming the profile. | Silently skipping a bad default, or picking "the first customer". | Guessing is how wrong counterparties end up on invoices. |
| 7 | **Seed at every new-order event**: profile load, opening an empty table, after send/clear, new tab, empty restored tab. | Reactive "if empty, refill". | The picker's Change button clears the field on purpose; a reactive rule would make it unusable. |
| 8 | **Resolve the customer's name and phone once at profile load.** | Showing the raw link ID only; extending the `getPosProfile` payload. | One extra cached request gives the picker a real display name for any future default, without changing the limited-profile contract. |
| 9 | **Empty tabs are seeded; busy tabs are preserved.** | Re-seeding every tab on reload. | A tab holding a draft must keep the invoice's customer, including a deliberately cleared one. |
| 10 | **Editable prefill, not a locked field.** | Locking orders to the profile customer. | Named guests still exist; "saves typing" is the goal, not "forces attribution". |
| 11 | **Walk-In attribution accepted.** | Imposing a staff convention for named guests. | Walk-In is the only customer in the DB today; the default just removes the typing. |
| 12 | **Backend tests + manual UI checks.** | Introducing a frontend test runner. | `pos` has no vitest setup; the money-path logic is server-side and already has a Frappe test module. |
| 13 | **Signature unchanged; clients send an empty string.** | Making `customer` optional (requires defaulting the four parameters after it) or reordering the signature. | Reordering a whitelisted endpoint risks silently misbinding positional callers. The trade-off: a caller that omits the key entirely still gets a raw `TypeError`. |
| 14 | **Docs: this document + glossary + gotcha. No ADR.** | An ADR for reusing the standard field. | Easy to reverse and it follows the existing self-ordering pattern, so it fails the ADR test. |

---

## 3. How it works now

### 3.1 Cashier or manager takes an order

1. `AuthGuard` loads the POS Profile; `fetchPosProfile` resolves
   `POS Profile.customer` into a `{id, name, phone}` customer and stores it as
   `defaultCustomer`.
2. If the order state is empty (no customer, no invoice, not updating), the
   same customer is seeded into `selectedCustomer`.
3. Opening a table with no existing order, sending/clearing an order, adding a
   tab, or closing the last tab all re-seed it.
4. The picker shows the customer already filled in; Change still works and
   clears it for that order.

### 3.2 Captain takes an order

Identical mechanics — the captain module uses the same store and
`CustomerSelect` — so `/order` arrives prefilled without any captain-specific
code.

### 3.3 Server resolution in `sync_order`

In order:

1. **Explicit customer** from the request → used as-is.
2. **Existing invoice** (update, caller sent nothing) → the invoice's current
   customer.
3. **`POS Profile.customer`** → used for a new invoice.
4. Nothing usable → `"Please enter valid customer details"`.

A profile default that no longer exists or is disabled raises a titled
configuration error naming the POS Profile and the customer, before the order
is written.

### 3.4 What does not change

- Reservations and bill splits — still an explicit choice.
- Aggregator orders — the aggregator's customer.
- Invoice ownership — `owner` stays the shift's opener; `waiter` stays the
  captain (see `docs/single-shift-model.md`).
- Billing — `make_invoice` receives an invoice that already has a customer.

---

## 4. Enforcement map

| Concern | Where | When |
|---|---|---|
| Default customer resolved | `pos/src/lib/pos-profile-api.ts` `resolveDefaultCustomer` | profile load |
| Seed on new order | `pos/src/store/pos-store.ts` `applyProfileDefaults` + the reset paths | render / state reset |
| Empty restored tabs seeded | `pos-store.ts` `switchTab`, `resetOrderState`, `closeTab` | tab change |
| Server fallback | `ury_order._default_customer_for`, used in `sync_order` | order create |
| Updates preserved | `sync_order` (`if not customer and invoice.name`) | order update |
| Clear error for a bad default | `ury_order._default_customer_for` | order create |

No DocType JSON, no migration, no new fields.

---

## 5. Failure modes

| Situation | Result |
|---|---|
| Profile has no customer | Picker starts empty; sending without a pick shows the existing "select a customer" message. |
| Profile customer deleted | Order refused: "POS Profile X has default customer Y, which no longer exists." |
| Profile customer disabled | Order refused: "POS Profile X has default customer Y, which is disabled." |
| Existing order, caller sends no customer | Invoice keeps its customer. |
| Aggregator order | Aggregator customer; the default is not consulted. |
| Staff presses Change then Send | Blocked with "select a customer"; the default returns on the next new order. |
| Caller omits `customer` entirely | Raw `TypeError` from Python (signature still requires it). Accepted trade-off of decision 13. |

---

## 6. Verification

Backend: `ury/ury/doctype/ury_order/test_ury_order.py`,
`TestSyncOrderDefaultCustomer`:

| Test | Asserts |
|---|---|
| `test_new_order_uses_profile_default_customer` | new invoice gets `Walk-In` |
| `test_update_keeps_existing_invoice_customer` | update keeps `Rahul` |
| `test_explicit_customer_wins_over_default` | explicit value wins |
| `test_missing_default_customer_raises_clear_error` | empty profile → "Please enter valid customer details" |
| `test_disabled_default_customer_raises_clear_error` | disabled → error naming the profile |

Module result: 33 tests, all passing (the four shift-era failures in this
module were repaired in the same change).

Frontend: `npx tsc --noEmit` clean, `yarn build` succeeds.

Manual checks: cashier and captain both arrive prefilled; an existing named
order keeps its customer; aggregator orders ignore the default; clearing and
sending is blocked; an empty or disabled profile default behaves as above.

---

## 7. Known limitations

- **The client guard sits in front of the server fallback.** Because the UI
  refuses to send with an empty field, the server fallback is reachable from
  the API (a caller sending `""`) but not from normal use. This is intentional:
  pressing Send after Change should not silently bill Walk-In.
- **One customer bucket.** Every defaulted ticket is attributed to Walk-In, so
  per-customer sales reports show a single dominant line. Table, captain and
  shift attribution are unaffected.
- **Two defaults exist by design.** `URY Self Ordering Profile.default_customer`
  covers QR/kiosk orders. It is a different profile for a different surface; do
  not merge them.
- **`POS Profile.customer` now has meaning.** It was unused before; if another
  integration starts reading it, review that assumption first.

---

## 8. Related documents

- `CONTEXT.md` — glossary (Default customer, Captain, Waiter, Opener).
- `docs/single-shift-model.md` — one shift per branch, invoice ownership,
  closing.
- `docs/gotchas.md` — operational traps, including this feature's prefill
  semantics.
- `docs/kot-printing.md` — the KOT slip printed for each send.
