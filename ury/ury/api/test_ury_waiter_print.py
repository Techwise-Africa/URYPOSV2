from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from ury.ury.api.ury_waiter_print import (
	WAITER_PRINT_FORMAT,
	build_combined_kot_doc,
	get_combined_kot_print_html,
	print_combined_waiter_order_slip,
	resolve_kot_print_format,
)


class TestURYWaiterPrint(FrappeTestCase):
	def _make_kot_doc(self, name, kot_type, items):
		kot_doc = frappe._dict(
			{
				"doctype": "URY KOT",
				"name": name,
				"type": kot_type,
				"invoice": "INV-001",
				"restaurant_table": "T-01",
				"customer_name": "Customer",
				"order_no": "101",
				"kot_items": [],
			}
		)
		for item in items:
			kot_doc.kot_items.append(frappe._dict(item))
		return kot_doc

	def _waiter_printer(self, **kwargs):
		defaults = {
			"printer": "Waiter Printer",
			"custom_waiter_print_format": WAITER_PRINT_FORMAT,
		}
		defaults.update(kwargs)
		return frappe._dict(defaults)

	def _invoice_qty_side_effect(self, qty_map=None):
		qty_map = qty_map or {}

		def get_all(doctype, filters=None, fields=None):
			if doctype == "POS Invoice Item":
				return [
					{"item_code": item_code, "qty": qty, "comment": comment}
					for (item_code, comment), qty in qty_map.items()
				]
			return []

		return get_all

	def _build_combined(self, kot_names, invoice_qty_map=None):
		combined = frappe._dict({"invoice": "INV-001", "kot_items": []})
		combined.append = lambda field, item: combined.kot_items.append(frappe._dict(item))
		return combined, invoice_qty_map

	@patch("ury.ury.api.ury_waiter_print.frappe.get_all")
	@patch("ury.ury.api.ury_waiter_print.frappe.copy_doc")
	@patch("ury.ury.api.ury_waiter_print.frappe.get_doc")
	def test_build_combined_kot_doc_merges_multiple_kots(
		self, mock_get_doc, mock_copy_doc, mock_get_all
	):
		mock_get_doc.side_effect = [
			self._make_kot_doc(
				"KOT-1",
				"New Order",
				[{"item": "Pizza", "item_name": "Pizza", "quantity": "1", "comments": ""}],
			),
			self._make_kot_doc(
				"KOT-2",
				"Order Modified",
				[{"item": "Pasta", "item_name": "Pasta", "quantity": "2", "comments": ""}],
			),
		]
		combined, invoice_qty_map = self._build_combined(["KOT-1", "KOT-2"])
		mock_copy_doc.return_value = combined
		mock_get_all.side_effect = self._invoice_qty_side_effect(invoice_qty_map)

		combined_doc = build_combined_kot_doc(["KOT-1", "KOT-2"])

		self.assertEqual(len(combined_doc.kot_items), 2)
		self.assertEqual(combined_doc.kot_items[0].item, "Pizza")
		self.assertEqual(combined_doc.kot_items[0].display_mode, "single_qty")
		self.assertEqual(combined_doc.kot_items[1].quantity, 2)
		self.assertEqual(combined_doc.kot_items[1].display_mode, "single_qty")

	@patch("ury.ury.api.ury_waiter_print.frappe.get_all")
	@patch("ury.ury.api.ury_waiter_print.frappe.copy_doc")
	@patch("ury.ury.api.ury_waiter_print.frappe.get_doc")
	def test_build_combined_kot_doc_aggregates_same_item(
		self, mock_get_doc, mock_copy_doc, mock_get_all
	):
		mock_get_doc.side_effect = [
			self._make_kot_doc(
				"KOT-1",
				"New Order",
				[{"item": "Pizza", "item_name": "Pizza", "quantity": "1", "comments": ""}],
			),
			self._make_kot_doc(
				"KOT-2",
				"Order Modified",
				[{"item": "Pizza", "item_name": "Pizza", "quantity": "2", "comments": ""}],
			),
		]
		combined, invoice_qty_map = self._build_combined(
			["KOT-1", "KOT-2"],
			{("Pizza", ""): 3},
		)
		mock_copy_doc.return_value = combined
		mock_get_all.side_effect = self._invoice_qty_side_effect(invoice_qty_map)

		combined_doc = build_combined_kot_doc(["KOT-1", "KOT-2"])

		self.assertEqual(len(combined_doc.kot_items), 1)
		self.assertEqual(combined_doc.kot_items[0].quantity, 3)
		self.assertEqual(combined_doc.kot_items[0].display_mode, "single_qty")

	@patch("ury.ury.api.ury_waiter_print.frappe.get_all")
	@patch("ury.ury.api.ury_waiter_print.frappe.copy_doc")
	@patch("ury.ury.api.ury_waiter_print.frappe.get_doc")
	def test_build_combined_kot_doc_includes_cancel_lines(
		self, mock_get_doc, mock_copy_doc, mock_get_all
	):
		mock_get_doc.side_effect = [
			self._make_kot_doc(
				"KOT-1",
				"New Order",
				[{"item": "Pizza", "item_name": "Pizza", "quantity": "1", "comments": ""}],
			),
			self._make_kot_doc(
				"KOT-2",
				"Partially cancelled",
				[
					{
						"item": "Soup",
						"item_name": "Soup",
						"quantity": "2",
						"cancelled_qty": 1,
						"comments": "",
					}
				],
			),
		]
		combined, invoice_qty_map = self._build_combined(
			["KOT-1", "KOT-2"],
			{("Pizza", ""): 1},
		)
		mock_copy_doc.return_value = combined
		mock_get_all.side_effect = self._invoice_qty_side_effect(invoice_qty_map)

		combined_doc = build_combined_kot_doc(["KOT-1", "KOT-2"])

		self.assertEqual(len(combined_doc.kot_items), 2)
		self.assertEqual(combined_doc.kot_items[0].display_mode, "single_qty")
		self.assertEqual(combined_doc.kot_items[1].display_mode, "old_new")
		self.assertEqual(combined_doc.kot_items[1].old_qty, 2)
		self.assertEqual(combined_doc.kot_items[1].new_qty, 1)
		self.assertEqual(combined_doc.kot_items[1].cancelled_qty, 1)

	@patch("ury.ury.api.ury_waiter_print.frappe.get_all")
	@patch("ury.ury.api.ury_waiter_print.frappe.copy_doc")
	@patch("ury.ury.api.ury_waiter_print.frappe.get_doc")
	def test_first_time_add_shows_single_quantity(self, mock_get_doc, mock_copy_doc, mock_get_all):
		mock_get_doc.return_value = self._make_kot_doc(
			"KOT-1",
			"New Order",
			[{"item": "Pizza", "item_name": "Pizza", "quantity": "3", "comments": ""}],
		)
		combined, invoice_qty_map = self._build_combined(["KOT-1"], {("Pizza", ""): 3})
		mock_copy_doc.return_value = combined
		mock_get_all.side_effect = self._invoice_qty_side_effect(invoice_qty_map)

		combined_doc = build_combined_kot_doc(["KOT-1"])

		self.assertEqual(combined_doc.kot_items[0].display_mode, "single_qty")
		self.assertEqual(combined_doc.kot_items[0].quantity, 3)

	@patch("ury.ury.api.ury_waiter_print.frappe.get_all")
	@patch("ury.ury.api.ury_waiter_print.frappe.copy_doc")
	@patch("ury.ury.api.ury_waiter_print.frappe.get_doc")
	def test_existing_item_increase_shows_old_new(self, mock_get_doc, mock_copy_doc, mock_get_all):
		mock_get_doc.return_value = self._make_kot_doc(
			"KOT-1",
			"Order Modified",
			[{"item": "Pizza", "item_name": "Pizza", "quantity": "2", "comments": ""}],
		)
		combined, invoice_qty_map = self._build_combined(["KOT-1"], {("Pizza", ""): 5})
		mock_copy_doc.return_value = combined
		mock_get_all.side_effect = self._invoice_qty_side_effect(invoice_qty_map)

		combined_doc = build_combined_kot_doc(["KOT-1"])

		self.assertEqual(combined_doc.kot_items[0].display_mode, "old_new")
		self.assertEqual(combined_doc.kot_items[0].old_qty, 3)
		self.assertEqual(combined_doc.kot_items[0].new_qty, 5)

	@patch("ury.ury.api.ury_waiter_print.frappe.get_all")
	@patch("ury.ury.api.ury_waiter_print.frappe.copy_doc")
	@patch("ury.ury.api.ury_waiter_print.frappe.get_doc")
	def test_existing_item_partial_cancel_shows_old_new(
		self, mock_get_doc, mock_copy_doc, mock_get_all
	):
		mock_get_doc.return_value = self._make_kot_doc(
			"KOT-1",
			"Partially cancelled",
			[
				{
					"item": "Soup",
					"item_name": "Soup",
					"quantity": "10",
					"cancelled_qty": 3,
					"comments": "",
				}
			],
		)
		combined, invoice_qty_map = self._build_combined(["KOT-1"], {("Soup", ""): 7})
		mock_copy_doc.return_value = combined
		mock_get_all.side_effect = self._invoice_qty_side_effect(invoice_qty_map)

		combined_doc = build_combined_kot_doc(["KOT-1"])

		self.assertEqual(combined_doc.kot_items[0].display_mode, "old_new")
		self.assertEqual(combined_doc.kot_items[0].old_qty, 10)
		self.assertEqual(combined_doc.kot_items[0].new_qty, 7)

	@patch("ury.ury.api.ury_waiter_print.frappe.get_all")
	@patch("ury.ury.api.ury_waiter_print.frappe.copy_doc")
	@patch("ury.ury.api.ury_waiter_print.frappe.get_doc")
	def test_full_cancel_shows_old_to_zero(self, mock_get_doc, mock_copy_doc, mock_get_all):
		mock_get_doc.return_value = self._make_kot_doc(
			"KOT-1",
			"Partially cancelled",
			[
				{
					"item": "Soup",
					"item_name": "Soup",
					"quantity": "10",
					"cancelled_qty": 10,
					"comments": "",
				}
			],
		)
		combined, invoice_qty_map = self._build_combined(["KOT-1"], {})
		mock_copy_doc.return_value = combined
		mock_get_all.side_effect = self._invoice_qty_side_effect(invoice_qty_map)

		combined_doc = build_combined_kot_doc(["KOT-1"])

		self.assertEqual(combined_doc.kot_items[0].display_mode, "old_new")
		self.assertEqual(combined_doc.kot_items[0].old_qty, 10)
		self.assertEqual(combined_doc.kot_items[0].new_qty, 0)

	@patch("ury.ury.api.ury_waiter_print.print_by_server")
	@patch("ury.ury.api.ury_waiter_print.build_combined_kot_doc")
	@patch("ury.ury.api.ury_waiter_print.frappe.db.get_value")
	@patch("ury.ury.api.ury_waiter_print.frappe.get_all")
	@patch("ury.ury.api.ury_waiter_print.frappe.db.exists")
	def test_prints_combined_kot_for_dine_in(
		self,
		mock_exists,
		mock_get_all,
		mock_get_value,
		mock_build_combined,
		mock_print_by_server,
	):
		mock_exists.return_value = True
		mock_get_value.side_effect = lambda doctype, name, fieldname=None, **kwargs: {
			("URY Table", "T-01", "restaurant_room"): "Room-1",
			("URY Table", "T-01", "is_take_away"): 0,
			("Print Format", WAITER_PRINT_FORMAT, "doc_type"): "URY KOT",
		}.get((doctype, name, fieldname))
		mock_get_all.return_value = [self._waiter_printer()]

		combined_doc = MagicMock()
		combined_doc.kot_items = [frappe._dict({"item": "Pizza", "quantity": "1"})]
		mock_build_combined.return_value = combined_doc

		print_combined_waiter_order_slip("INV-001", ["KOT-1"], "T-01")

		mock_print_by_server.assert_called_once_with(
			"URY KOT",
			"KOT-1",
			"Waiter Printer",
			WAITER_PRINT_FORMAT,
			doc=combined_doc,
			no_letterhead=1,
		)

	@patch("ury.ury.api.ury_waiter_print.print_by_server")
	@patch("ury.ury.api.ury_waiter_print.build_combined_kot_doc")
	@patch("ury.ury.api.ury_waiter_print.frappe.db.get_value")
	@patch("ury.ury.api.ury_waiter_print.frappe.get_all")
	def test_skips_when_combined_items_empty(
		self, mock_get_all, mock_get_value, mock_build_combined, mock_print_by_server
	):
		mock_get_value.side_effect = lambda doctype, name, fieldname=None, **kwargs: {
			("URY Table", "T-01", "restaurant_room"): "Room-1",
			("URY Table", "T-01", "is_take_away"): 0,
		}.get((doctype, name, fieldname))
		mock_get_all.return_value = [self._waiter_printer()]
		combined_doc = MagicMock()
		combined_doc.kot_items = []
		mock_build_combined.return_value = combined_doc

		print_combined_waiter_order_slip("INV-001", ["KOT-1"], "T-01")
		mock_print_by_server.assert_not_called()

	@patch("ury.ury.api.ury_waiter_print.print_by_server")
	def test_skips_takeaway_tables(self, mock_print_by_server):
		with patch(
			"ury.ury.api.ury_waiter_print._is_takeaway_table",
			return_value=True,
		):
			print_combined_waiter_order_slip("INV-001", ["KOT-1"], "T-01")
		mock_print_by_server.assert_not_called()

	@patch("ury.ury.api.ury_waiter_print.print_by_server")
	def test_skips_without_restaurant_table(self, mock_print_by_server):
		print_combined_waiter_order_slip("INV-001", ["KOT-1"], None)
		mock_print_by_server.assert_not_called()

	@patch("ury.ury.api.ury_waiter_print.print_by_server")
	@patch("ury.ury.api.ury_waiter_print.build_combined_kot_doc")
	@patch("ury.ury.api.ury_waiter_print.frappe.db.get_value")
	@patch("ury.ury.api.ury_waiter_print.frappe.get_all")
	def test_skips_when_no_waiter_printers(
		self, mock_get_all, mock_get_value, mock_build_combined, mock_print_by_server
	):
		mock_get_value.side_effect = lambda doctype, name, fieldname=None, **kwargs: {
			("URY Table", "T-01", "restaurant_room"): "Room-1",
			("URY Table", "T-01", "is_take_away"): 0,
		}.get((doctype, name, fieldname))
		mock_get_all.return_value = []
		mock_build_combined.return_value = MagicMock(kot_items=[1])

		print_combined_waiter_order_slip("INV-001", ["KOT-1"], "T-01")
		mock_print_by_server.assert_not_called()

	@patch("ury.ury.api.ury_waiter_print.frappe.log_error")
	@patch("ury.ury.api.ury_waiter_print.print_by_server")
	@patch("ury.ury.api.ury_waiter_print.build_combined_kot_doc")
	@patch("ury.ury.api.ury_waiter_print.frappe.db.get_value")
	@patch("ury.ury.api.ury_waiter_print.frappe.get_all")
	def test_skips_when_printer_format_not_set(
		self, mock_get_all, mock_get_value, mock_build_combined, mock_print_by_server, mock_log_error
	):
		mock_get_value.side_effect = lambda doctype, name, fieldname=None, **kwargs: {
			("URY Table", "T-01", "restaurant_room"): "Room-1",
			("URY Table", "T-01", "is_take_away"): 0,
		}.get((doctype, name, fieldname))
		mock_get_all.return_value = [self._waiter_printer(custom_waiter_print_format=None)]
		mock_build_combined.return_value = MagicMock(kot_items=[1])

		print_combined_waiter_order_slip("INV-001", ["KOT-1"], "T-01")
		mock_print_by_server.assert_not_called()
		mock_log_error.assert_called_once()

	@patch("ury.ury.api.ury_waiter_print.frappe.log_error")
	@patch("ury.ury.api.ury_waiter_print.print_by_server")
	@patch("ury.ury.api.ury_waiter_print.build_combined_kot_doc")
	@patch("ury.ury.api.ury_waiter_print.frappe.db.get_value")
	@patch("ury.ury.api.ury_waiter_print.frappe.get_all")
	@patch("ury.ury.api.ury_waiter_print.frappe.db.exists")
	def test_skips_when_format_missing(
		self,
		mock_exists,
		mock_get_all,
		mock_get_value,
		mock_build_combined,
		mock_print_by_server,
		mock_log_error,
	):
		mock_exists.return_value = False
		mock_get_value.side_effect = lambda doctype, name, fieldname=None, **kwargs: {
			("URY Table", "T-01", "restaurant_room"): "Room-1",
			("URY Table", "T-01", "is_take_away"): 0,
		}.get((doctype, name, fieldname))
		mock_get_all.return_value = [self._waiter_printer()]
		mock_build_combined.return_value = MagicMock(kot_items=[1])

		print_combined_waiter_order_slip("INV-001", ["KOT-1"], "T-01")
		mock_print_by_server.assert_not_called()
		mock_log_error.assert_called_once()

	@patch("ury.ury.api.ury_waiter_print.frappe.log_error")
	@patch("ury.ury.api.ury_waiter_print.print_by_server")
	@patch("ury.ury.api.ury_waiter_print.build_combined_kot_doc")
	@patch("ury.ury.api.ury_waiter_print.frappe.db.get_value")
	@patch("ury.ury.api.ury_waiter_print.frappe.get_all")
	@patch("ury.ury.api.ury_waiter_print.frappe.db.exists")
	def test_skips_when_format_wrong_doctype(
		self,
		mock_exists,
		mock_get_all,
		mock_get_value,
		mock_build_combined,
		mock_print_by_server,
		mock_log_error,
	):
		mock_exists.return_value = True
		mock_get_value.side_effect = lambda doctype, name, fieldname=None, **kwargs: {
			("URY Table", "T-01", "restaurant_room"): "Room-1",
			("URY Table", "T-01", "is_take_away"): 0,
			("Print Format", WAITER_PRINT_FORMAT, "doc_type"): "POS Invoice",
		}.get((doctype, name, fieldname))
		mock_get_all.return_value = [self._waiter_printer()]
		mock_build_combined.return_value = MagicMock(kot_items=[1])

		print_combined_waiter_order_slip("INV-001", ["KOT-1"], "T-01")
		mock_print_by_server.assert_not_called()
		mock_log_error.assert_called_once()

	@patch("ury.ury.api.ury_waiter_print.print_combined_waiter_order_slip")
	@patch("ury.ury.api.ury_kot_generate.process_items_for_cancel_kot")
	@patch("ury.ury.api.ury_kot_generate.process_items_for_kot")
	@patch("ury.ury.api.ury_kot_generate.frappe.get_doc")
	def test_kot_execute_prints_once_with_all_created_kots(
		self,
		mock_get_doc,
		mock_process_kot,
		mock_process_cancel,
		mock_print_combined,
	):
		from ury.ury.api.ury_kot_generate import kot_execute

		pos_profile = MagicMock()
		pos_profile.custom_kot_naming_series = "KOT-"
		pos_profile.name = "POS-1"

		pos_invoice = MagicMock()
		pos_invoice.pos_profile = "POS-1"

		mock_get_doc.side_effect = [pos_invoice, pos_profile]
		mock_process_kot.return_value = ["KOT-1", "KOT-2"]
		mock_process_cancel.return_value = ["CNCL-1"]

		kot_execute(
			"INV-001",
			"Customer",
			"T-01",
			current_items=[
				{"item": "Pizza", "qty": 2, "item_name": "Pizza"},
				{"item": "Soup", "qty": 0, "item_name": "Soup"},
			],
			previous_items=[
				{"item": "Pizza", "qty": 1, "item_name": "Pizza"},
				{"item": "Soup", "qty": 1, "item_name": "Soup"},
			],
		)

		mock_print_combined.assert_called_once_with(
			"INV-001",
			["KOT-1", "KOT-2", "CNCL-1"],
			"T-01",
		)

	@patch("ury.ury.api.ury_kot_reprint.print_by_server")
	def test_kot_reprint_does_not_call_waiter_print(self, mock_print_by_server):
		from ury.ury.api.ury_kot_reprint import print_kot

		print_kot("Reprint Printer", "INV-001", "Reprint Format")
		mock_print_by_server.assert_called_once_with(
			"POS Invoice",
			"INV-001",
			"Reprint Printer",
			"Reprint Format",
		)

	def test_waiter_format_excludes_pricing_sections(self):
		if not frappe.db.exists("Print Format", WAITER_PRINT_FORMAT):
			self.skipTest(f"Print Format '{WAITER_PRINT_FORMAT}' not found on site")

		print_format = frappe.get_doc("Print Format", WAITER_PRINT_FORMAT)
		if print_format.doc_type != "URY KOT":
			self.skipTest(
				f"Print Format '{WAITER_PRINT_FORMAT}' is not configured for URY KOT on site"
			)

		html = print_format.html.lower()
		for keyword in ("rate", "amount", "tax", "total", "payment", "grand"):
			self.assertNotIn(keyword, html)


class TestKotBrowserPrint(FrappeTestCase):
	"""The browser KOT slip must follow Desk, never a copy baked into the app.

	Resolution and rendering both happen per request: the Print Format record
	is read from the database and its HTML compiled fresh, so an edit or a new
	"Set as Default" in Desk is used by the very next send.
	"""

	def test_resolver_prefers_the_doctype_default(self):
		with patch(
			"ury.ury.api.ury_waiter_print.frappe.get_meta"
		) as mock_get_meta, patch(
			"ury.ury.api.ury_waiter_print._is_usable_kot_format",
			return_value=True,
		) as mock_usable:
			mock_get_meta.return_value = frappe._dict(
				default_print_format="House KOT Slip"
			)

			self.assertEqual(resolve_kot_print_format(), "House KOT Slip")
			mock_usable.assert_called_once_with("House KOT Slip")

	def test_resolver_falls_back_to_the_shipped_slip(self):
		def usable(name):
			return name == WAITER_PRINT_FORMAT

		with patch(
			"ury.ury.api.ury_waiter_print.frappe.get_meta"
		) as mock_get_meta, patch(
			"ury.ury.api.ury_waiter_print._is_usable_kot_format",
			side_effect=usable,
		):
			mock_get_meta.return_value = frappe._dict(default_print_format=None)

			self.assertEqual(resolve_kot_print_format(), WAITER_PRINT_FORMAT)

	def test_resolver_skips_an_unusable_default(self):
		def usable(name):
			return name == WAITER_PRINT_FORMAT

		with patch(
			"ury.ury.api.ury_waiter_print.frappe.get_meta"
		) as mock_get_meta, patch(
			"ury.ury.api.ury_waiter_print._is_usable_kot_format",
			side_effect=usable,
		):
			mock_get_meta.return_value = frappe._dict(
				default_print_format="Deleted Slip"
			)

			self.assertEqual(resolve_kot_print_format(), WAITER_PRINT_FORMAT)

	def test_resolver_returns_none_when_nothing_is_usable(self):
		with patch(
			"ury.ury.api.ury_waiter_print.frappe.get_meta"
		) as mock_get_meta, patch(
			"ury.ury.api.ury_waiter_print._is_usable_kot_format",
			return_value=False,
		):
			mock_get_meta.return_value = frappe._dict(default_print_format=None)

			self.assertIsNone(resolve_kot_print_format())

	def _payload_mocks(self):
		"""Shared mocks for the endpoint: invoice, permission, branch, KOT rows."""
		invoice = MagicMock()
		invoice.branch = "Havenflow"
		return invoice

	@patch("ury.ury.api.ury_waiter_print.frappe.get_print", return_value="<html>slip</html>")
	@patch(
		"ury.ury.api.ury_waiter_print.resolve_kot_print_format",
		return_value=WAITER_PRINT_FORMAT,
	)
	@patch("ury.ury.api.ury_waiter_print.build_combined_kot_doc")
	@patch("ury.ury.api.ury_waiter_print.frappe.get_all", return_value=["KOT-1"])
	@patch("ury.ury.api.ury_waiter_print.frappe.db.set_value")
	@patch("ury.ury.api.ury_waiter_print.frappe.has_permission", return_value=True)
	@patch("ury.ury.api.ury_waiter_print.frappe.get_doc")
	@patch("ury.ury_pos.api.getBranch", return_value="Havenflow")
	def test_endpoint_renders_the_resolved_format_and_writes_nothing(
		self,
		_mock_branch,
		mock_get_doc,
		_mock_permission,
		mock_set_value,
		_mock_get_all,
		mock_build,
		_mock_resolve,
		mock_get_print,
	):
		mock_get_doc.return_value = self._payload_mocks()

		combined = MagicMock()
		combined.kot_items = [object()]
		mock_build.return_value = combined

		result = get_combined_kot_print_html("INV-1", '["KOT-1"]')

		self.assertEqual(result["html"], "<html>slip</html>")
		self.assertEqual(result["kot_names"], ["KOT-1"])
		self.assertEqual(result["print_format"], WAITER_PRINT_FORMAT)

		# The copy mirrors the submitted source KOT, so rendering does not
		# depend on the site-wide "allow print for draft" setting.
		self.assertEqual(combined.name, "KOT-1")
		self.assertEqual(combined.docstatus, 1)

		mock_get_print.assert_called_once_with(
			"URY KOT",
			"KOT-1",
			WAITER_PRINT_FORMAT,
			doc=combined,
			no_letterhead=1,
		)

		# The critical guarantee: a KOT slip never advances the bill state.
		mock_set_value.assert_not_called()

	@patch("ury.ury.api.ury_waiter_print.frappe.get_print")
	@patch("ury.ury.api.ury_waiter_print.build_combined_kot_doc")
	@patch("ury.ury.api.ury_waiter_print.frappe.get_all", return_value=[])
	@patch("ury.ury.api.ury_waiter_print.frappe.has_permission", return_value=True)
	@patch("ury.ury.api.ury_waiter_print.frappe.get_doc")
	@patch("ury.ury_pos.api.getBranch", return_value="Havenflow")
	def test_endpoint_rejects_kots_from_another_invoice(
		self,
		_mock_branch,
		mock_get_doc,
		_mock_permission,
		_mock_get_all,
		mock_build,
		mock_get_print,
	):
		mock_get_doc.return_value = self._payload_mocks()

		with self.assertRaises(frappe.ValidationError):
			get_combined_kot_print_html("INV-1", '["KOT-FROM-OTHER-INVOICE"]')

		mock_build.assert_not_called()
		mock_get_print.assert_not_called()

	@patch("ury.ury.api.ury_waiter_print.frappe.get_all")
	@patch("ury.ury.api.ury_waiter_print.frappe.has_permission", return_value=False)
	@patch("ury.ury.api.ury_waiter_print.frappe.get_doc")
	def test_endpoint_requires_invoice_read_permission(
		self,
		mock_get_doc,
		_mock_permission,
		_mock_get_all,
	):
		mock_get_doc.return_value = self._payload_mocks()

		with self.assertRaises(frappe.PermissionError):
			get_combined_kot_print_html("INV-1", '["KOT-1"]')

		_mock_get_all.assert_not_called()
