# Copyright (c) 2024, Essdee and contributors
# For license information, please see license.txt
import frappe, json
from frappe.model.document import Document
from six import string_types
from production_api.production_api.doctype.item.item import create_variant, get_variant, get_attribute_details, get_or_create_variant
from itertools import groupby
from production_api.production_api.doctype.item_dependent_attribute_mapping.item_dependent_attribute_mapping import get_dependent_attribute_details

class ProductionOrder(Document):
	def before_submit(self):
		if len(self.bom_summary) == 0:
			frappe.throw("BOM is not calculated");

	def before_validate(self):
		if self.get('item_details'):
			items = save_item_details(self.item_details)
			self.set("items",items)
		qty = 0
		for item in self.items:
			qty = qty + item.qty
		self.total_quantity = qty
		item_attr = get_attribute_details(self.item)
		if item_attr['primary_attribute']:
			items = calculate_order_details(self.get('items'), self.production_detail)
			self.set('production_order_details',items )

	def onload(self):
		item_details = fetch_item_details(self.get('items'), self.production_detail)
		self.set_onload('item_details', item_details)
		order_item_details = fetch_order_item_details(self.get('production_order_details'), self.production_detail)
		self.set_onload('order_item_details',order_item_details)

def calculate_order_details(items, production_detail):
	item_detail = frappe.get_doc("Item Production Detail", production_detail)
	final_list = []
	import math
	uom = get_isfinal_uom(production_detail)
	doc = frappe.get_doc("Item", item_detail.item)
	uom_conv = 0.0
	for uom_conversion in doc.uom_conversion_details:
		if uom_conversion.uom == uom:
			uom_conv = uom_conversion.conversion_factor
			break

	for item in items:
		variant = frappe.get_doc("Item Variant", item.item_variant)
		is_not_pack_attr = True
		for attribute in variant.attributes:
			attribute = attribute.as_dict()
			if attribute.attribute == item_detail.packing_attribute:
				is_not_pack_attr = False
				break
		if is_not_pack_attr:		
			qty = item.qty * uom_conv
			if item_detail.auto_calculate:
				qty = qty / item_detail.packing_attribute_no
			else:
				qty = qty / item_detail.packing_combo
			
			for attr in item_detail.packing_item_details:
				# variant = frappe.get_doc("Item Variant", item.item_variant)
				# attrs = {}
				# for attribute in variant.attributes:
				# 	attribute = attribute.as_dict()
				# 	attrs[attribute.attribute] = attribute['attribute_value']
				# attrs[item_detail.packing_attribute] = attr.attribute_value
				# print(variant.item)
				# print(attrs)
				# new_variant = get_or_create_variant(variant.item, attrs)
				# new_variant = get_variant(variant.item, attrs)
				# new_variant = create_variant(variant.item,)
				
				item1 = {
					'attribute_value': attr.attribute_value,
					'item_variant': item.item_variant,
					'table_index': item.table_index,
					'row_index': item.row_index,
					'quantity': math.ceil(qty) if item_detail.auto_calculate else math.ceil(qty * attr.quantity)
				}
				final_list.append(item1)
			
	return final_list
def save_item_details(item_details):
	if isinstance(item_details, string_types):
		item_details = json.loads(item_details)
	item = item_details[0]
	items = []
	for id1, row in enumerate(item['items']):
		if row['primary_attribute']:
			attributes = row['attributes']
			if item['final_state']:
				attributes[item['dependent_attribute']] = item['final_state']
			for id2, val in enumerate(row['values'].keys()):
				attributes[row['primary_attribute']] = val
				item1 = {}
				variant_name = get_variant(item['item'], attributes)
				if not variant_name:
					variant1 = create_variant(item['item'], attributes)
					variant1.insert()
					variant_name = variant1.name
				item1['item_variant'] = variant_name
				item1['qty'] = row['values'][val]
				item1['table_index'] = id1
				item1['row_index'] = id2
				items.append(item1)
		else:
			item1 = {}
			attributes = row['attributes']
			variant_name = item['item']
			variant_name = get_variant(item['item'], attributes)
			if not variant_name:
				variant1 = create_variant(item['item'], attributes)
				variant1.insert()
				variant_name = variant1.name
			item1['item_variant'] = variant_name
			item1['qty'] = row['values']['qty']
			item1['table_index'] = id1
			items.append(item1)
	return items	

def fetch_item_details(items, production_detail):
	items = [item.as_dict() for item in items]
	items = sorted(items, key = lambda i: i['table_index'])
	item_structure = None
	for key, variants in groupby(items, lambda i: i['table_index']):
		variants = list(variants)
		item1 = {}
		grp_variant = frappe.get_doc("Item Variant", variants[0]['item_variant'])
		if not item_structure:
			uom = get_isfinal_uom(production_detail)
			item_structure = get_item_details(grp_variant.item, uom)
		values = {}	
		for variant in variants:
			current_variant = frappe.get_doc("Item Variant", variant['item_variant'])
			variant_attr_details = get_attribute_details(current_variant.item)
			item_attribute_details = get_item_attribute_details(current_variant, variant_attr_details)
			doc = frappe.get_doc("Item", current_variant.item)
			if doc.dependent_attribute and doc.dependent_attribute in item_attribute_details:
				del item_attribute_details[doc.dependent_attribute]
			if doc.primary_attribute:		
				for attr in current_variant.attributes:
					if attr.attribute == variant_attr_details['primary_attribute']:
						values[attr.attribute_value] = variant['qty']
			else:
				values['qty'] = variant['qty']
		item1['primary_attribute'] = variant_attr_details['primary_attribute']
		item1['attributes'] = item_attribute_details
		item1['values'] = values
		item_structure['items'].append(item1)
	return item_structure

def fetch_order_item_details(items, production_detail):
	items = [item.as_dict() for item in items]
	items = sorted(items, key = lambda i: i['table_index'])
	order_item_details = []
	for key, grp_by_table in groupby(items, lambda i: i['table_index']):
		all_variants = list(grp_by_table)
		item_structure = None
		for key, variants in groupby(all_variants, lambda i: i['row_index']):
			variants = list(variants)
			grp_variant = frappe.get_doc("Item Variant", variants[0]['item_variant'])
			if not item_structure:
				uom = get_isfinal_uom(production_detail)
				item_structure = get_item_details(grp_variant.item, uom, production_detail=production_detail)
			for variant in variants:
				item1 = {}
				values = {}
				current_variant = frappe.get_doc("Item Variant", variant['item_variant'])
				variant_attr_details = get_attribute_details(current_variant.item)
				item_attribute_details = get_item_attribute_details(current_variant, variant_attr_details)
				doc = frappe.get_doc("Item", current_variant.item)
				values['attribute_value'] = variant['attribute_value']
				if doc.dependent_attribute and doc.dependent_attribute in item_attribute_details:
					del item_attribute_details[doc.dependent_attribute]
				if doc.primary_attribute:		
					for attr in current_variant.attributes:
						if attr.attribute == variant_attr_details['primary_attribute']:
							values[attr.attribute_value] = variant['quantity']
				else:
					values['qty'] = variant['quantity']
				item1['primary_attribute'] = variant_attr_details['primary_attribute'] or None
				item1['attributes'] = item_attribute_details
				item1['values'] = values
				if key != 0:
					for x in item_structure['items']:
						if x['values']['attribute_value'] == values['attribute_value']:
							x['values'].update(values)
							break
				else:	
					item_structure['items'].append(item1)
		order_item_details.append(item_structure)
	return order_item_details


def get_item_attribute_details(variant, item_attributes):
	attribute_details = {}
	for attr in variant.attributes:
		if attr.attribute in item_attributes['attributes']:
			attribute_details[attr.attribute] = attr.attribute_value
	return attribute_details

@frappe.whitelist()
def get_item_details(item_name, uom=None, production_detail=None):
	item = get_attribute_details(item_name)
	if uom:
		item['default_uom'] = uom
	final_state = None
	final_state_attr = None
	item['items'] = []
	if item['dependent_attribute']:
		for attr in item['dependent_attribute_details']['attr_list']:
			if item['dependent_attribute_details']['attr_list'][attr]['is_final'] == 1:
				final_state = attr
				final_state_attr = item['dependent_attribute_details']['attr_list'][attr]['attributes']
		if not final_state:
			frappe.msgprint("There is no final state for this item")
			return []	
		item['final_state'] = final_state
		if item['primary_attribute'] in final_state_attr:
			final_state_attr.remove(item['primary_attribute'])
		item['final_state_attr'] = final_state_attr	
	elif not item['dependent_attribute'] and not item['primary_attribute']:
		doc = frappe.get_doc("Item", item['item'])
		final_state_attr = []
		for attr in doc.attributes:
			final_state_attr.append(attr.attribute)
		item['final_state_attr'] = final_state_attr
	if production_detail:
		doc = frappe.get_doc("Item Production Detail", production_detail)
		item['packing_attr'] = doc.packing_attribute
	return item

@frappe.whitelist()
def update_bom_summary(doc_name, bom):
	doc = frappe.get_doc("Production Order", doc_name)
	doc.set('bom_summary', json.loads(bom))
	doc.save()

@frappe.whitelist()
def get_isfinal_uom(item_production_detail):
	doc = frappe.get_doc("Item Production Detail", item_production_detail)
	if doc.dependent_attribute_mapping:
		attribute_details = get_dependent_attribute_details(doc.dependent_attribute_mapping)
		for attr in attribute_details['attr_list']:
			if attribute_details['attr_list'][attr]['is_final'] == 1:
				return attribute_details['attr_list'][attr]['uom']
	else:
		return None		