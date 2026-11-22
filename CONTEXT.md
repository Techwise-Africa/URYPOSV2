# URY POS

Restaurant point-of-sale built on ERPNext. One branch, one shift, staff with
different levels of money-handling authority.

## Language

**Shift**:
The period a branch's POS is open for trading, recorded as a POS Opening
Entry with an opening cash balance.
_Avoid_: Session, drawer, shift session

**Closed POS**:
The state of a branch with no open shift, in which no POS screen can be used.
_Avoid_: Offline, locked, shut down

**Opener**:
The person recorded on the shift. Owns its money, its invoices and its
closing.
_Avoid_: Main cashier, shift owner, cashier-on-duty

**Billing user**:
A person allowed to take payment, discount, cancel and open or close a shift,
by virtue of a role listed in the POS Profile's billing roles.
_Avoid_: Cashier (a role name, not a capability), manager

**Captain**:
A person who takes table orders. Never opens, closes or bills.
_Avoid_: Waiter, order taker, server

**Waiter**:
The person who took a specific order. Recorded on the invoice and preserved
regardless of who owns the shift.
_Avoid_: Captain (the role), user

**KOT slip**:
The kitchen/waiter ticket for the items a send actually changed. Printed from
`URY KOT`, never from the POS Invoice.
_Avoid_: Kitchen receipt, order slip (ambiguous with the bill), ticket

**Default customer**:
The customer a new order starts on, taken from the POS Profile. Still editable
per order.
_Avoid_: Walk-in (a value, not the concept), house customer, default guest

**Draft**:
An order that has been taken but not yet paid for.
_Avoid_: Open order, held bill, pending invoice

**Closing**:
The end-of-shift reconciliation of a shift's invoices and cash, recorded
under the opener.
_Avoid_: Cash-up, day end, settlement

**Join**:
Working under a shift someone else opened, without creating a second shift.
_Avoid_: Share shift, piggyback
