# Browser KOT printing

How a sent order produces a KOT slip in the browser, without touching the
bill's state: **the POS prints the combined `URY KOT` slip for the items that
send changed, using whatever print format Desk currently resolves.**

Branch: `feat/single-shift-pos` (same branch as the single-shift model and the
default customer), based on `version-2` of `Techwise-Africa/URYPOSV2`.

---

## 1. Objective

Staff need a kitchen/waiter ticket the moment an order is sent. Today the only
browser print is the POS Invoice, and that print is **not** free of side
effects: `updatePrintStatus()` → `qz_print_update()` sets
`invoice_printed = 1`, which the POS shows as **Unbilled** and which blocks
non-billing users from editing the order.

So the ticket has to be its own artefact. URY already has one:
**`URY KOT`** documents, created by `kot_execute()` from the delta between the
invoice's stored items and the items being sent. This change prints those, and
only those.

Constraints: no DocType or schema changes, no new configuration fields, and no
change to how the POS, shifts, ownership or billing work.

---

## 2. Decisions

| # | Decision | Alternative rejected | Why |
|---|---|---|---|
| 1 | **Print a `URY KOT` slip, never the invoice.** | Reusing `printOrder()` with a KOT format. | The invoice print sets `invoice_printed = 1` and releases merged tables. A kitchen ticket must not change billing state. |
| 2 | **One combined slip per send**, not one per station. | Printing each production unit's KOT. | Staff hand one ticket to the pass; per-station tickets are already the optional server path. |
| 3 | **Delta only.** The slip contains the items this send added or cancelled. | Reprinting the whole order each time. | `kot_execute()` already computes the delta; resending the order must not re-fire earlier items. |
| 4 | **The server resolves the print format per request.** | Hardcoding the format name or bundling its HTML in the POS. | Desk must stay the source of truth (see §3). |
| 5 | **Desk's default KOT format wins**; then the shipped `URY Waiter Order Slip`; then Standard. | A new POS-Profile field to choose the format. | Zero schema change, and it uses Frappe's standard "Set as Default" lever. |
| 6 | **Auto-open the browser print dialog** on every successful send that created a KOT. | Silent printing, or a button. | Chosen by the operator. Silent printing needs a kiosk-mode browser. |
| 7 | **Fire-and-forget.** The send succeeds even if the print does. | Awaiting the print and failing the send. | The order is already committed; a missing slip must not look like a lost order. |
| 8 | **Both roles, all order types.** Cashier (`/pos`) and captain (`/order`), dine-in, takeaway and aggregator. | Captain-only or dine-in-only. | The send path is shared; gating would add rules without a user need. |
| 9 | **Hidden iframe, not `window.open`.** | Opening a print window. | After an `await`, popups are blocked; iframe printing is not. |
| 10 | **Browser suggests 80mm page size.** | Editing the Print Format to add `@page`. | The format is a database record; the suggestion belongs to the browser path. |
| 11 | **No server-print work in this change.** | Installing pycups and configuring printers. | The operator asked for the POS side only. The existing CUPS path is untouched and inert. |

---

## 3. Which print format is used

Resolved in `ury/ury/api/ury_waiter_print.py` on **every** request:

1. `URY KOT`'s **default print format** — set in Desk by opening a Print Format
   and pressing **Set as Default** (`make_default()` writes
   `default_print_format` on the DocType).
2. The shipped **`URY Waiter Order Slip`**, if it still exists and is enabled.
3. Otherwise Frappe renders its own **Standard** format.

Rendering is live. `frappe.get_print()` → `get_print_format_doc()` does
`frappe.get_doc("Print Format", name)`, and custom formats are compiled with
`jenv.from_string(get_print_format(...))`. There is no cached template and the
POS has no service worker, so:

- **Editing a format in Desk** — HTML, fields, styling — is used by the next
  send. No `bench migrate`, no `yarn build`, no restart.
- **Creating a new `URY KOT` format** and pressing **Set as Default** is used by
  the next send.
- **Clearing the default** makes the shipped slip come back.

The app file `ury/ury/print_format/ury_waiter_order_slip/ury_waiter_order_slip.json`
is a **seed only** (`"standard": "No"`). Editing it changes nothing at runtime;
the database record is what prints.

---

## 4. How it works now

1. Cashier or captain sends an order. `sync_order` saves the invoice and calls
   `kot_execute()`.
2. `kot_execute()` creates the delta KOTs (new and cancelled items) and returns
   their names.
3. `sync_order` returns `{...invoice, "kot_names": [...]}`.
4. The POS resets the cart and shows its normal success toast.
5. When `kot_names` is non-empty, `printKotSlip()` fetches
   `get_combined_kot_print_html(invoice, kot_names)`.
6. The endpoint checks `POS Invoice` read permission and the caller's branch,
   keeps only the KOTs that belong to that invoice, builds the combined URY KOT
   document, and renders it with the resolved format.
7. The POS writes the HTML into a hidden iframe and calls `print()`, so the
   browser dialog opens with "Save as PDF" available.

### What a send does *not* do

- It does not write `POS Invoice.invoice_printed`.
- It does not release merged tables or change table occupancy (beyond the
  normal "table occupied" mark for a new order).
- It does not call `printOrder`, `updatePrintStatus`, `qz_print_update`,
  `network_printing` or `print_pos_page`.

---

## 5. Enforcement map

| Concern | Where | When |
|---|---|---|
| KOT names returned to the client | `ury_kot_generate.kot_execute`, `ury_order.sync_order` | order create/update |
| Read permission + branch gate | `ury_waiter_print.get_combined_kot_print_html` | print request |
| Cross-invoice protection | same (`invoice` filter on `URY KOT`) | print request |
| Format resolved from Desk | `ury_waiter_print.resolve_kot_print_format` | print request |
| Slip rendering | `frappe.get_print("URY KOT", ..., doc=combined_doc)` | print request |
| Browser print | `pos/src/lib/kot-print.ts` | after a successful send |
| Trigger | `OrderPanel.handleSend`, `CaptainOrder.handleSend` | after reset/redirect |

No DocType JSON, no migration, no new fields.

---

## 6. Failure modes

| Situation | Result |
|---|---|
| No new or changed items | No KOT is created; `kot_names` is empty; no dialog. |
| Print endpoint fails | Order stays saved; the slip is skipped and the error is logged in the console. |
| Caller lacks `POS Invoice` read | `PermissionError`. |
| Order belongs to another branch | `PermissionError`. |
| Caller passes another invoice's KOT names | Those names are dropped; if none remain, `ValidationError`. |
| No usable format in Desk | Frappe's Standard format is used. |
| Browser blocks the iframe/print | No dialog; the order is unaffected. |
| KOT cancelled/removed between send and print | Only the remaining, invoice-matching KOTs render. |

---

## 7. Verification

Backend:

- `ury/ury/api/test_ury_waiter_print.py :: TestKotBrowserPrint`
  - resolver prefers the Desk default;
  - resolver falls back to the shipped slip;
  - resolver skips an unusable default;
  - resolver returns `None` when nothing is usable;
  - endpoint renders the resolved format, sets `name`/`docstatus` on the copy,
    and **writes nothing** (`frappe.db.set_value` not called);
  - endpoint rejects KOTs from another invoice;
  - endpoint requires `POS Invoice` read permission.
- `TestURYOrder.test_sync_order_authorized` asserts the response carries
  `name` and `kot_names`.

Run both with `--skip-before-tests` (ERPNext's test hook empties `Item Price`).

Frontend: `npx tsc --noEmit`, `yarn build`.

Manual: send a captain order → dialog shows only the delta and no prices; the
order stays **Draft**, `invoice_printed = 0`, the table stays occupied; add an
item and resend → only the new item; takeaway and aggregator; cashier send;
dismiss the dialog and confirm the cart already reset. Then edit the slip in
Desk and send again → the new HTML is used without a rebuild.

---

## 8. Known limitations

- **Not silent.** The dialog opens on every send that creates a KOT. Removing
  the dialog requires launching Chrome/Edge with `--kiosk-printing` and a
  configured default printer.
- **Paper size is a suggestion.** The browser injects `@page { size: 80mm auto }`;
  the user can still choose another destination or paper.
- **The slip is not stored.** It exists only in the print dialog; there is no
  PDF file on the server.
- **The server CUPS path is separate.** It stays behind
  `URY Printer Settings.custom_waiter_print`, untouched. If both channels are
  ever enabled, point them at the same format so they do not diverge.
- **`URY KOT`'s Desk default is global.** Setting it also changes what Desk
  prints for a KOT. That is the cost of using Frappe's standard lever.

---

## 9. Related documents

- `CONTEXT.md` — glossary (KOT slip, Captain, Waiter, Draft).
- `docs/default-customer.md` — new orders start on the POS Profile's customer.
- `docs/single-shift-model.md` — one shift per branch, invoice ownership,
  closing.
- `docs/gotchas.md` — bill printing marks the order Unbilled; Desk is the
  runtime source for print formats.
