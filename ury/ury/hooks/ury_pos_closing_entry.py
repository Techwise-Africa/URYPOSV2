import frappe
from frappe import _

def before_save(doc, method):
    sub_pos_close_check(doc, method)

def validate(doc, method):
    populate_pos_transactions(doc, method)
    calculate_closing_amount(doc, method)
    validate_cashier(doc, method)
    validate_no_open_orders(doc, method)


def populate_pos_transactions(doc, method=None):
    """Fill `pos_transactions` from the shift's submitted invoices.

    The POS frontend creates the closing without them (and ERPNext's Desk JS
    is the only other writer), so without this the closing carries no invoice
    list and nothing gets consolidated on submit. In the single-shift model
    every invoice is owned by the opener, so selecting by `owner` collects
    everything the captains took during the shift.
    """
    if doc.pos_transactions:
        return

    if frappe.db.get_value("POS Profile", doc.pos_profile, "custom_enable_multiple_cashier"):
        return

    if not (doc.pos_profile and doc.user and doc.period_start_date):
        return

    invoices = frappe.get_all(
        "POS Invoice",
        filters={
            "docstatus": 1,
            "pos_profile": doc.pos_profile,
            "owner": doc.user,
            "posting_date": [
                "between",
                [doc.period_start_date, doc.period_end_date or frappe.utils.now()],
            ],
        },
        fields=[
            "name",
            "posting_date",
            "customer",
            "grand_total",
            "is_return",
            "return_against",
            "consolidated_invoice",
        ],
    )

    for invoice in invoices:
        if invoice.consolidated_invoice:
            continue
        doc.append(
            "pos_transactions",
            {
                "pos_invoice": invoice.name,
                "posting_date": invoice.posting_date,
                "customer": invoice.customer,
                "grand_total": invoice.grand_total,
                "is_return": invoice.is_return,
                "return_against": invoice.return_against,
            },
        )

    # Server-computed totals, so the closing is correct even when the client
    # didn't compute them (e.g. a manager closing someone else's shift).
    if doc.pos_transactions and not doc.grand_total:
        doc.total_quantity = sum(
            frappe.db.get_value("POS Invoice", row.pos_invoice, "total_qty") or 0
            for row in doc.pos_transactions
        )
        doc.grand_total = sum(row.grand_total or 0 for row in doc.pos_transactions)
        doc.net_total = sum(
            frappe.db.get_value("POS Invoice", row.pos_invoice, "net_total") or 0
            for row in doc.pos_transactions
        )


def validate_no_open_orders(doc, method=None):
    """Refuse to close while the branch still has unbilled orders.

    In the single-shift model every POS Invoice belongs to the branch's open
    shift (owner = opener). A draft left behind when the shift closes would
    never appear in any closing, so its revenue would silently disappear.
    Multi-cashier closes keep their existing per-cashier behaviour.
    """
    if frappe.db.get_value("POS Profile", doc.pos_profile, "custom_enable_multiple_cashier"):
        return

    branch = frappe.db.get_value("POS Profile", doc.pos_profile, "branch")
    if not branch:
        return

    drafts = frappe.get_all(
        "POS Invoice",
        filters={"branch": branch, "docstatus": 0},
        fields=["restaurant_table"],
        limit=50,
    )
    if not drafts:
        return

    tables = sorted({(d.restaurant_table or _("No table")) for d in drafts})
    frappe.throw(
        _(
            "Cannot close: these tables still have unbilled orders — {0}. "
            "Bill or cancel them first."
        ).format(", ".join(tables)),
        title=_("Unbilled Orders"),
    )

def on_submit(doc, method=None):
    update_branch_avg_times(doc)

def on_cancel(doc, method=None):
    update_branch_avg_times(doc)

def update_branch_avg_times(doc):
    try:
        branch = None
        if doc.get("pos_opening_entry"):
            branch = frappe.db.get_value("POS Opening Entry", doc.pos_opening_entry, "branch")
        if not branch and doc.get("pos_profile"):
            branch = frappe.db.get_value("POS Profile", doc.pos_profile, "branch")
        if branch:
            from ury.ury.report.average_table_time.average_table_time import update_branch_avg_table_times
            update_branch_avg_table_times(branch)
    except Exception as e:
        frappe.log_error(f"Error updating branch average table times on POS Closing: {str(e)}", "POS Closing Avg Table Time")


def sub_pos_close_check(doc,method):
    cashier = None
    multiple_cashier = frappe.db.get_value("POS Profile",doc.pos_profile,"custom_enable_multiple_cashier")
    if multiple_cashier:
        get_cashier = frappe.get_doc("POS Profile", doc.pos_profile)
        for user_details in get_cashier.applicable_for_users:
            if not user_details.custom_main_cashier:
                cashier = user_details.user
        if frappe.session.user != cashier:
            branch=frappe.db.get_value("POS Profile",doc.pos_profile,"branch")
            pos_opening_list = frappe.get_all(
                "POS Opening Entry",
                fields=["name", "docstatus", "status", "posting_date"],
                filters={"branch": branch,"user":cashier},
            )
            flag = 0
            for pos_opening in pos_opening_list:
                if pos_opening.status == "Open" and pos_opening.docstatus == 1:
                    flag = 1
            if flag == 1:
                frappe.throw(("Sub Cashier POS  must be closed"), title=("Sub Cashier POS Closing Required"))
                
            return flag
    else:
        pass

def calculate_closing_amount(doc, method):
    multiple_cashier = frappe.db.get_value("POS Profile",doc.pos_profile,"custom_enable_multiple_cashier")
    if multiple_cashier:  
        sub_pos_closing = frappe.get_all(
            "Sub POS Closing",
            filters=[
                ["posting_date", "<=", doc.posting_date],
                ["period_start_date", ">=", doc.period_start_date],
                ["docstatus", "=", 1]
            ],
            fields=["name"] 
        )
        if sub_pos_closing:
            for closing_details in doc.payment_reconciliation:
                sub_closing_amount = frappe.db.get_value("Sub POS Closing Payment",{"parent":sub_pos_closing[0].name,"mode_of_payment":closing_details.mode_of_payment},"closing_amount") or 0
                main_closing_amount = closing_details.custom_closing_amount or 0
                total_closing_amount = sub_closing_amount + main_closing_amount
                closing_details.closing_amount = total_closing_amount
                closing_details.difference = total_closing_amount - closing_details.expected_amount
        else:
            frappe.throw("No Sub POS Closing entries found between the given dates")
            return None
    else:
        pass
def validate_cashier(doc, method):
    cashier = None
    multiple_cashier = frappe.db.get_value("POS Profile",doc.pos_profile,"custom_enable_multiple_cashier")
    if multiple_cashier:
        get_cashier = frappe.get_doc("POS Profile", doc.pos_profile)
        for user_details in get_cashier.applicable_for_users:
            if not user_details.custom_main_cashier:
                cashier = user_details.user
        if frappe.session.user == cashier:
            frappe.throw("Sub Cashiers are not allowed to make POS Closing Entries.")
    else:
        pass
    