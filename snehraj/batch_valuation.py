# -*- coding: utf-8 -*-

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.utils import flt, cint, cstr
from frappe.desk.reportview import get_match_cond
import datetime


def batch_wise_cost():
	return cint(frappe.db.get_single_value("Stock Settings", 'exact_cost_valuation_for_batch_wise_items'))

@frappe.whitelist()
def pr_validate(self, method):
	if batch_wise_cost():
		make_batches(self, 'warehouse')

@frappe.whitelist()
def pr_on_cancel(self, method):
	if batch_wise_cost():
		delete_batches(self, 'warehouse')

@frappe.whitelist()
def pi_validate(self, method):
	if self.update_stock and batch_wise_cost():
		make_batches(self, 'warehouse')

@frappe.whitelist()
def pi_on_cancel(self, method):
	if self.update_stock and batch_wise_cost():
		delete_batches(self, 'warehouse')

@frappe.whitelist()
def stock_entry_validate(self, method):
	if batch_wise_cost():
		if self.purpose not in ["Manufacture", "Subcontract", "Material Receipt"]:
			set_basic_rate_for_t_warehouse(self)

		if self.purpose not in ['Material Transfer', 'Material Transfer for Manufacture']:
			make_batches(self, 't_warehouse')
		
@frappe.whitelist()
def stock_entry_on_submit(self, method):
	if batch_wise_cost():
		if self.purpose in ['Material Transfer', 'Material Transfer for Manufacture']:
			make_transfer_batchs(self)
			update_stock_ledger_batch(self)

def make_transfer_batchs(self):
	for row in self.items:
		if not row.get('t_warehouse'):
			continue

		has_batch_no = frappe.db.get_value('Item', row.item_code, 'has_batch_no')
		if has_batch_no:
			if row.batch_no:
				if frappe.db.get_value("Batch", row.batch_no, 'valuation_rate') == row.valuation_rate:
					continue

			batch = frappe.new_doc("Batch")
			batch.item = row.item_code
			batch.roll_no = cstr(row.roll_no)
			batch.valuation_rate = round(row.valuation_rate, 4)
			batch.posting_date = datetime.datetime.strptime(self.posting_date, "%Y-%m-%d").strftime("%y%m%d")
			batch.actual_quantity = flt(row.qty * row.conversion_factor)
			batch.reference_doctype = self.doctype
			batch.reference_name = self.name
			batch.insert()

			row.db_set('old_batch_no', row.batch_no)
			row.db_set('batch_no', batch.name)

@frappe.whitelist()
def stock_entry_on_cancel(self, method):
	if batch_wise_cost():
		if self.purpose in ['Material Transfer', 'Material Transfer for Manufacture']:
			delete_transfer_batches(self)
		else:
			delete_batches(self, 't_warehouse')

def delete_transfer_batches(self):
	from frappe.model.delete_doc import check_if_doc_is_linked
	
	for row in self.items:
		if row.batch_no and row.get('t_warehouse'):
			batch_no = frappe.get_doc("Batch", row.batch_no)
			if batch_no.valuation_rate == row.valuation_rate and not row.get('old_batch_no'):
				continue

			# row.batch_no = row.old_batch_no
			# check_if_doc_is_linked(batch_no)
			# frappe.delete_doc("Batch", batch_no.name)
			row.db_set('batch_no', row.old_batch_no)
			row.db_set('old_batch_no', '')
			batch_no.db_set('reference_doctype','')
			batch_no.db_set('reference_name','')
	# else:
	# 	frappe.db.commit()

def update_stock_ledger_batch(self):
	for row in self.get('items'):
		sle = frappe.get_doc("Stock Ledger Entry", {
			'voucher_no': self.name,
			'voucher_detail_no': row.name,
			'warehouse': row.t_warehouse,
			'is_cancelled':0,
		})

		if sle:
			sle.db_set('batch_no', row.batch_no)

def set_basic_rate_for_t_warehouse(self):
	s_warehouse_rates = [d.valuation_rate * d.qty for d in self.get('items') if d.s_warehouse and not d.t_warehouse]

	for d in self.get('items'):
		if d.t_warehouse:
			d.basic_rate = (sum(s_warehouse_rates) / flt(d.qty))

	self.run_method('calculate_rate_and_amount')

def make_batches(self, warehouse_field):
	if self._action == "submit":
		for row in self.items:
			if not row.get(warehouse_field):
				continue

			has_batch_no = frappe.db.get_value('Item', row.item_code, 'has_batch_no')
			if has_batch_no:
				batch = frappe.new_doc("Batch")
				batch.item = row.item_code
				batch.supplier = getattr(self, 'supplier', None)
				batch.roll_no = cstr(row.roll_no)
				batch.valuation_rate = round(row.valuation_rate, 4)
				batch.posting_date = datetime.datetime.strptime(self.posting_date, "%Y-%m-%d").strftime("%y%m%d")
				batch.actual_quantity = flt(row.qty * row.conversion_factor)
				batch.reference_doctype = self.doctype
				batch.reference_name = self.name
				batch.insert()

				if row.batch_no and self.doctype == "Stock Entry":
					row.db_set('old_batch_no', row.batch_no)
				
				row.batch_no = batch.name

def delete_batches(self, warehouse):
	from frappe.model.delete_doc import check_if_doc_is_linked
	
	for row in self.items:
		if row.batch_no and row.get(warehouse):
			batch_no = frappe.get_doc("Batch", row.batch_no)
			
			row.db_set('batch_no', None)
			batch_no.db_set('reference_doctype','')
			batch_no.db_set('reference_name','')
			# row.batch_no = ''
			# check_if_doc_is_linked(batch_no)
			# frappe.delete_doc("Batch", batch_no.name)
			# row.db_set('batch_no', '')
	# else:
	# 	frappe.db.commit()


@frappe.whitelist()
def override_batch_autoname(self, method):
	from erpnext.stock.doctype.batch.batch import Batch
	Batch.autoname = batch_autoname

def batch_autoname(self):
	import barcode
	from frappe.model.naming import make_autoname

	def generate_barcode(code):
		image=barcode.get_barcode('code39')
		image_bar=image(code)
		image_bar.writer.dpi=30
		image_bar.default_writer_options['module_height']=10.583333333
		image_bar.default_writer_options['module_width']=0.5291666667
		image_bar.code = code
		bar = image_bar.render({}).decode("utf-8").replace('\n', '')

		return bar
	
	batch_series, batch_wise_cost = frappe.db.get_value("Stock Settings", None, ['batch_series', 'exact_cost_valuation_for_batch_wise_items'])
	series = 'BTH-.YY.MM.DD.-.###'

	if batch_wise_cost and batch_series:
		series = batch_series

	name = None
	while not name:
		name = make_autoname(series, "Batch", self)
		if frappe.db.exists('Batch', name):
			name = None

	self.batch_id = name
	self.db_set('barcode_show', generate_barcode(name))
	# self.barcode_show = name
	self.name = name

@frappe.whitelist()
def get_batch_no(doctype, txt, searchfield, start, page_len, filters):
	cond = ""

	# meta = frappe.get_meta("Batch")
	# searchfield = meta.get_search_fields()
	searchfield = ['roll_no'] # searchfields for Batch

	searchfields = " or ".join(["batch." + field + " like %(txt)s" for field in searchfield])

	if filters.get("posting_date"):
		cond = "and (batch.expiry_date is null or batch.expiry_date >= %(posting_date)s)"

	batch_nos = None
	args = {
		'item_code': filters.get("item_code"),
		'warehouse': filters.get("warehouse"),
		'posting_date': filters.get('posting_date'),
		'txt': "%{0}%".format(txt),
		"start": start,
		"page_len": page_len
	}

	if args.get('warehouse'):
		batch_nos = frappe.db.sql("""select sle.batch_no, batch.roll_no, round(sum(sle.actual_qty),2), sle.stock_uom
				from `tabStock Ledger Entry` sle
				    INNER JOIN `tabBatch` batch on sle.batch_no = batch.name
				where
					sle.item_code = %(item_code)s
					and sle.warehouse = %(warehouse)s
					and sle.is_cancelled = 0
					and batch.docstatus < 2
					{0}
					{match_conditions}
				group by batch_no 
				having 
					sum(sle.actual_qty) > 0 and 
						(sle.batch_no like %(txt)s or 
						round(sum(sle.actual_qty),2) like %(txt)s or
						{searchfields})
				order by batch.expiry_date, sle.batch_no desc
				limit %(start)s, %(page_len)s""".format(cond, match_conditions=get_match_cond(doctype), searchfields=searchfields), args)

	if batch_nos:
		return batch_nos
	else:
		return frappe.db.sql("""select name, roll_no, expiry_date from `tabBatch` batch
			where item = %(item_code)s
			and name like %(txt)s
			and reference_doctype = ''
			and reference_name = ''
			and docstatus < 2
			{0}
			{match_conditions}
			order by expiry_date, name desc
			limit %(start)s, %(page_len)s""".format(cond, match_conditions=get_match_cond(doctype)), args)

@frappe.whitelist()
def lcv_validate(self, method):
	if self._action == "submit" and batch_wise_cost():
		validate_batch_actual_qty(self)

@frappe.whitelist()
def lcv_on_submit(self, method):
	if batch_wise_cost():
		update_batch_valuation(self)

@frappe.whitelist()
def lcv_on_cancel(self, method):
	if batch_wise_cost():
		update_batch_valuation(self)

# Update Valuation rate of Purchase Receipt / Purchase Invoice in Batch
def update_batch_valuation(self):
	for d in self.get("purchase_receipts"):
		doc = frappe.get_doc(d.receipt_document_type, d.receipt_document)

		for row in doc.items:
			if row.batch_no:
				batch_doc = frappe.get_doc("Batch", row.batch_no)
				batch_doc.valuation_rate = row.valuation_rate
				batch_doc.save()


def validate_batch_actual_qty(self):
	from erpnext.stock.doctype.batch.batch import get_batch_qty

	for d in self.get("purchase_receipts"):
		doc = frappe.get_doc(d.receipt_document_type, d.receipt_document)

		for row in doc.items:
			if row.batch_no:
				batch_qty = get_batch_qty(row.batch_no, row.warehouse)

				if batch_qty < row.stock_qty:
					frappe.throw(_("The batch <b>{0}</b> does not have sufficient quantity for item <b>{1}</b> in row {2}.".format(row.batch_no, row.item_code, d.idx)))


def delete_auto_created_batches(self):
	pass