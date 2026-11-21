# Invoices belong to the shift's opener, not their creator

In a single-shift branch, captains take orders but never open shifts, so the
invoice's creator is not the person accountable for the money. ERPNext's POS
Closing only accepts invoices whose `owner` is the closing user, so ownership
is stamped to the branch's open shift's opener at creation; the captain stays
recorded in `waiter`. We chose this over reworking the closing to select
invoices by branch/cashier, which would have meant overriding ERPNext's
`validate_pos_invoices` — a far larger and riskier change for the same
outcome. Consequence: `owner` no longer means "created by" in this app;
`waiter` and `modified_by` carry the human trail, and per-captain reporting
must use `waiter`.
