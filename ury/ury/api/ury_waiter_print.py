import frappe
from frappe import _
from frappe.utils.print_format import print_by_server

WAITER_PRINT_FORMAT = "URY Waiter Order Slip"
ADD_KOT_TYPES = ("New Order", "Order Modified")
CANCEL_KOT_TYPES = ("Partially cancelled", "Cancelled")


def _is_usable_kot_format(name):
	"""True if `name` is an enabled Print Format for the URY KOT doctype."""
	if not name:
		return False

	row = frappe.db.get_value("Print Format", name, ["doc_type", "disabled"])
	return bool(row) and row[0] == "URY KOT" and not row[1]


def resolve_kot_print_format():
	"""Pick the KOT slip format at request time, entirely from Desk.

	Resolution is deliberately live (not cached) and has no schema behind it:

	1. `URY KOT`'s default Print Format — what Desk's "Set as Default" writes
	   on a Print Format form.
	2. The shipped `URY Waiter Order Slip`, when it still exists and is
	   enabled.
	3. `None`, which makes Frappe render its own "Standard" format.

	Editing either format in Desk changes the next slip: `frappe.get_print`
	reads the Print Format record and compiles its HTML on every call.
	"""
	default_format = frappe.get_meta("URY KOT").default_print_format

	if _is_usable_kot_format(default_format):
		return default_format

	if _is_usable_kot_format(WAITER_PRINT_FORMAT):
		return WAITER_PRINT_FORMAT

	return None


def _get_room_waiter_printers(room):
	return frappe.get_all(
		"URY Printer Settings",
		fields=["printer", "custom_waiter_print_format"],
		filters={
			"parent": room,
			"parenttype": "URY Room",
			"custom_waiter_print": 1,
		},
		order_by="idx",
	)


def _is_takeaway_table(restaurant_table):
	if not restaurant_table:
		return True
	return frappe.db.get_value("URY Table", restaurant_table, "is_take_away") == 1


def _aggregate_kot_items(kot_docs):
	add_items = {}
	cancel_items = {}

	for kot in kot_docs:
		for row in kot.kot_items:
			key = (row.item, row.comments or "")
			if kot.type in CANCEL_KOT_TYPES:
				if key not in cancel_items:
					cancel_items[key] = {
					"item": row.item,
					"item_name": row.item_name,
					"quantity": int(row.quantity or 0),
					"cancelled_qty": int(row.cancelled_qty or 0),
					"comments": row.comments,
					"course": row.course,
					}
			elif kot.type in ADD_KOT_TYPES:
				if key not in add_items:
					add_items[key] = {
					"item": row.item,
					"item_name": row.item_name,
					"quantity": int(row.quantity or 0),
					"comments": row.comments,
					"course": row.course,
					}
				else:
					# The same item can appear on more than one add KOT in a
					# single send (e.g. two stations sharing an item group).
					# The slip shows the quantity for the whole send, so sum
					# rather than keep only the first line.
					add_items[key]["quantity"] += int(row.quantity or 0)

	return list(add_items.values()) + list(cancel_items.values())


def _get_invoice_item_qty_map(invoice_id):
	if not invoice_id:
		return {}

	qty_map = {}
	for row in frappe.get_all(
		"POS Invoice Item",
		filters={"parent": invoice_id},
		fields=["item_code", "qty", "comment"],
	):
		key = (row["item_code"], row.get("comment") or "")
		qty_map[key] = int(row.get("qty") or 0)

	return qty_map


def _enrich_item_display_fields(items, invoice_id):
	invoice_qty_map = _get_invoice_item_qty_map(invoice_id)
	enriched_items = []

	for item in items:
		item = dict(item)
		key = (item["item"], item.get("comments") or "")

		if item.get("cancelled_qty"):
			old_qty = int(item.get("quantity") or 0)
			cancelled_qty = int(item.get("cancelled_qty") or 0)
			new_qty = max(old_qty - cancelled_qty, 0)
			item["display_mode"] = "old_new"
			item["old_qty"] = old_qty
			item["new_qty"] = new_qty
		else:
			delta_qty = int(item.get("quantity") or 0)
			new_qty = invoice_qty_map.get(key, delta_qty)
			old_qty = new_qty - delta_qty

			if old_qty <= 0:
				item["display_mode"] = "single_qty"
				item["old_qty"] = 0
				item["new_qty"] = delta_qty
			else:
				item["display_mode"] = "old_new"
				item["old_qty"] = old_qty
				item["new_qty"] = new_qty

		enriched_items.append(item)

	return enriched_items


def build_combined_kot_doc(kot_names):
	if not kot_names:
		return None

	kot_docs = [frappe.get_doc("URY KOT", name) for name in kot_names]
	combined_doc = frappe.copy_doc(kot_docs[0])
	combined_doc.kot_items = []

	if combined_doc.invoice:
		waiter = frappe.db.get_value("POS Invoice", combined_doc.invoice, "waiter")
		if waiter:
			combined_doc.waiter = waiter

	for item in _enrich_item_display_fields(
		_aggregate_kot_items(kot_docs),
		combined_doc.invoice,
	):
		combined_doc.append("kot_items", item)

	return combined_doc


def _validate_waiter_print_format(waiter_print_format, room, printer):
	if not waiter_print_format:
		frappe.log_error(
			f"No waiter print format set for printer {printer} in room {room}.",
			"URY Waiter Print",
		)
		return False

	if not frappe.db.exists("Print Format", waiter_print_format):
		frappe.log_error(
			f"Waiter print format '{waiter_print_format}' not found.",
			"URY Waiter Print",
		)
		return False

	print_format_doctype = frappe.db.get_value("Print Format", waiter_print_format, "doc_type")
	if print_format_doctype != "URY KOT":
		frappe.log_error(
			f"Waiter print format '{waiter_print_format}' must be for URY KOT, not {print_format_doctype}.",
			"URY Waiter Print",
		)
		return False

	return True


def print_combined_waiter_order_slip(invoice_id, kot_names, restaurant_table):
	"""Print one combined waiter slip for all delta KOTs created in an order update."""
	if not invoice_id or not kot_names:
		return

	if not restaurant_table or _is_takeaway_table(restaurant_table):
		return

	room = frappe.db.get_value("URY Table", restaurant_table, "restaurant_room")
	if not room:
		return

	waiter_printers = _get_room_waiter_printers(room)
	if not waiter_printers:
		return

	combined_doc = build_combined_kot_doc(kot_names)
	if not combined_doc or not combined_doc.kot_items:
		return

	for printer_row in waiter_printers:
		waiter_print_format = printer_row.custom_waiter_print_format
		if not _validate_waiter_print_format(
			waiter_print_format, room, printer_row.printer
		):
			continue

		try:
			print_by_server(
				"URY KOT",
				kot_names[0],
				printer_row.printer,
				waiter_print_format,
				doc=combined_doc,
				no_letterhead=1,
			)
		except Exception as e:
			frappe.log_error(
				f"Waiter print failed for invoice {invoice_id}: {e}",
				"URY Waiter Print",
			)


@frappe.whitelist()
def get_combined_kot_print_html(invoice, kot_names=None):
	"""Render the combined KOT slip for the POS browser print dialog.

	This is a read-only render: it never touches `POS Invoice.invoice_printed`,
	table occupancy or merged tables. Printing the *bill* is what advances the
	order to Unbilled; a KOT slip must not.

	The slip content is the same combined URY KOT document the server path
	prints, and the format is resolved from Desk on every call, so a print
	format edited or newly set as default in Desk is used on the next send.
	"""
	invoice_doc = frappe.get_doc("POS Invoice", invoice)

	if not frappe.has_permission("POS Invoice", "read", doc=invoice_doc):
		frappe.throw(_("Not permitted to print this order"), frappe.PermissionError)

	# Same branch gate as reprint_kot: a POS user may only print their own
	# branch's slips. Imported lazily to keep this module free of a
	# ury_pos.api import cycle at load time.
	from ury.ury_pos.api import getBranch

	try:
		user_branch = getBranch()
	except frappe.ValidationError:
		if frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles():
			user_branch = None
		else:
			raise

	if user_branch and invoice_doc.branch and invoice_doc.branch != user_branch:
		frappe.throw(
			_("Not permitted to print KOTs for orders outside your active branch"),
			frappe.PermissionError,
		)

	requested = frappe.parse_json(kot_names) or []
	if isinstance(requested, str):
		requested = [requested]

	# Never let a caller print another invoice's KOTs, and keep the caller's
	# order so the slip reads the same way the send produced it.
	belonging = set(
		frappe.get_all(
			"URY KOT",
			filters={"name": ["in", requested], "invoice": invoice},
			pluck="name",
		)
	)
	names = [name for name in requested if name in belonging][:50]

	if not names:
		frappe.throw(_("No KOTs found for this order"), frappe.ValidationError)

	combined_doc = build_combined_kot_doc(names)
	if not combined_doc or not combined_doc.kot_items:
		frappe.throw(_("No KOT items found for this order"), frappe.ValidationError)

	# copy_doc() drops name and docstatus outside tests. The source KOTs are
	# submitted, so mirror that here: otherwise rendering depends on the
	# site-wide "allow print for draft" setting.
	combined_doc.name = names[0]
	combined_doc.docstatus = 1

	print_format = resolve_kot_print_format()
	html = frappe.get_print(
		"URY KOT",
		names[0],
		print_format,
		doc=combined_doc,
		no_letterhead=1,
	)

	return {
		"html": html,
		"kot_names": names,
		"print_format": print_format or "Standard",
	}

