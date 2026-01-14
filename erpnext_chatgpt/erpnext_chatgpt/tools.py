import frappe
import logging
import json
from datetime import datetime, date, timedelta
from decimal import Decimal

# Initialize module-level logger with aiassistant namespace
logger = frappe.logger("aiassistant", allow_site=True)
logger.setLevel(logging.DEBUG)

def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, timedelta):
        return str(obj)
    frappe.log_error(
        title="Not serializable", message=f"Type {type(obj)} not serializable"
    )
    try:
        return str(obj)
    except Exception:
        return ""


def lookup_entity(entity_type, search_term, limit=20, fuzzy_rerank=True):
    """
    Look up an entity (customer, supplier, item, etc.) using Frappe's built-in
    search_link functionality. This is fast, permission-aware, and searches
    across configured search fields.

    Use this tool FIRST when a user mentions an entity by an informal or
    partial name to resolve it to the exact database name before querying
    documents.

    Example: User says "swissski" -> lookup finds "Swiss Ski Verband"
    """
    from frappe.desk.search import search_link
    from difflib import SequenceMatcher

    # Map user-friendly entity types to DocTypes and their display fields
    # Only master data entities - not documents
    entity_config = {
        'customer': {
            'doctype': 'Customer',
            'display_field': 'customer_name',
            'filters': {'disabled': 0}
        },
        'supplier': {
            'doctype': 'Supplier',
            'display_field': 'supplier_name',
            'filters': {'disabled': 0}
        },
        'item': {
            'doctype': 'Item',
            'display_field': 'item_name',
            'filters': {'disabled': 0}
        },
        'employee': {
            'doctype': 'Employee',
            'display_field': 'employee_name',
            'filters': {'status': 'Active'}
        },
        'lead': {
            'doctype': 'Lead',
            'display_field': 'lead_name',
            'filters': {}
        },
        'contact': {
            'doctype': 'Contact',
            'display_field': 'name',
            'filters': {}
        }
    }

    # Normalize entity type
    entity_type_lower = entity_type.lower().replace(' ', '_').replace('-', '_')

    if entity_type_lower not in entity_config:
        # Try to find a close match
        available_types = list(entity_config.keys())
        return json.dumps({
            'error': f"Unknown entity type: '{entity_type}'",
            'available_types': available_types,
            'hint': 'Use one of the available entity types'
        }, default=json_serial)

    config = entity_config[entity_type_lower]
    doctype = config['doctype']
    display_field = config['display_field']
    filters = config['filters']

    try:
        # Stage 1: Use Frappe's search_link for fast, permission-aware candidate generation
        # search_link returns a list of tuples: [(value, label, description), ...]
        candidates = search_link(
            doctype=doctype,
            txt=search_term,
            page_length=limit * 2 if fuzzy_rerank else limit,  # Get more if we'll re-rank
            filters=filters
        )

        logger.debug(f"lookup_entity: search_link returned {len(candidates)} candidates for '{search_term}' in {doctype}")

        if not candidates:
            # No results from search_link, try a broader search
            # Sometimes search_link is too strict, so fall back to LIKE query
            fallback_results = frappe.db.get_all(
                doctype,
                filters={
                    **filters,
                    display_field: ['like', f'%{search_term}%']
                } if display_field != 'name' else filters,
                fields=['name', display_field] if display_field != 'name' else ['name'],
                limit=limit
            )

            if not fallback_results and display_field != 'name':
                # Try searching in name field too
                fallback_results = frappe.db.get_all(
                    doctype,
                    filters={
                        **filters,
                        'name': ['like', f'%{search_term}%']
                    },
                    fields=['name', display_field],
                    limit=limit
                )

            if fallback_results:
                candidates = [
                    (r['name'], r.get(display_field, r['name']), '')
                    for r in fallback_results
                ]

        if not candidates:
            return json.dumps({
                'entity_type': entity_type,
                'doctype': doctype,
                'search_term': search_term,
                'matches': [],
                'best_match': None,
                'message': f"No {entity_type} found matching '{search_term}'"
            }, default=json_serial)

        # Convert candidates to structured format
        results = []
        for candidate in candidates:
            # search_link returns tuples: (value, label, description)
            if isinstance(candidate, (list, tuple)):
                value = candidate[0] if len(candidate) > 0 else ''
                label = candidate[1] if len(candidate) > 1 else value
                description = candidate[2] if len(candidate) > 2 else ''
            else:
                value = str(candidate)
                label = value
                description = ''

            results.append({
                'id': value,
                'name': label or value,
                'description': description,
                'match_score': 100  # Will be recalculated if fuzzy_rerank
            })

        # Stage 2: Optional fuzzy re-ranking using SequenceMatcher
        if fuzzy_rerank and results:
            search_lower = search_term.lower().replace(' ', '').replace('-', '')

            for result in results:
                name_value = (result['name'] or result['id'] or '').lower()
                name_compact = name_value.replace(' ', '').replace('-', '')

                # Multiple scoring strategies
                scores = []

                # 1. Exact match
                if search_term.lower() == name_value:
                    scores.append(100)

                # 2. Exact containment (search in name or name in search)
                if search_lower in name_compact:
                    scores.append(95)
                elif name_compact in search_lower:
                    scores.append(90)

                # 3. Word boundary matching
                # "swissski" should match "Swiss Ski" well
                if search_lower in name_compact or name_compact.startswith(search_lower):
                    scores.append(88)

                # 4. Sequence matching (handles typos and partial matches)
                seq_score = int(SequenceMatcher(None, search_lower, name_compact).ratio() * 100)
                scores.append(seq_score)

                # 5. Also compare against the ID
                id_lower = (result['id'] or '').lower().replace(' ', '').replace('-', '')
                if search_lower in id_lower or id_lower in search_lower:
                    scores.append(85)

                # Take the best score
                result['match_score'] = max(scores) if scores else 0

            # Sort by score descending
            results.sort(key=lambda x: x['match_score'], reverse=True)

        # Limit results
        results = results[:limit]

        return json.dumps({
            'entity_type': entity_type,
            'doctype': doctype,
            'search_term': search_term,
            'matches': results,
            'best_match': results[0] if results else None,
            'total_found': len(results)
        }, default=json_serial)

    except Exception as e:
        logger.error(f"Error in lookup_entity: {str(e)}")
        frappe.log_error(f"lookup_entity error for {entity_type}/{search_term}: {str(e)}", "Entity Lookup Error")
        return json.dumps({
            'error': str(e),
            'entity_type': entity_type,
            'search_term': search_term
        }, default=json_serial)


lookup_entity_tool = {
    "type": "function",
    "function": {
        "name": "lookup_entity",
        "description": """Look up a master data entity by name to find the exact database identifier.
IMPORTANT: Use this tool FIRST when a user mentions a customer, supplier, item, contact, employee, or lead
by an informal, abbreviated, or partial name. This resolves names like 'swissski' to 'Swiss Ski Verband'.

Workflow:
1. User says 'Find delivery notes for swissski'
2. FIRST call lookup_entity(entity_type='customer', search_term='swissski')
3. Get exact name like 'Swiss Ski Verband' from best_match.id
4. THEN call list_delivery_notes(customer='Swiss Ski Verband')

This ensures accurate results by resolving informal names to exact database entries.""",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_type": {
                    "type": "string",
                    "enum": ["customer", "supplier", "item", "employee", "lead", "contact"],
                    "description": "Type of master data entity to search for"
                },
                "search_term": {
                    "type": "string",
                    "description": "The name or partial name to search for (can be informal, abbreviated, or misspelled)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 20)",
                    "default": 20
                }
            },
            "required": ["entity_type", "search_term"]
        }
    }
}


def get_sales_invoices(start_date=None, end_date=None):
    try:
        filters = {}
        if start_date and end_date:
            filters['posting_date'] = ['between', [start_date, end_date]]

        # Instead of fetching all fields, only get essential ones for summary
        # This prevents memory issues with large datasets
        invoices = frappe.db.get_all(
            'Sales Invoice',
            filters=filters,
            fields=[
                'name', 'customer', 'customer_name', 'posting_date',
                'grand_total', 'outstanding_amount', 'status', 'currency'
            ],
            limit=1000  # Add a reasonable limit to prevent huge responses
        )

        # Calculate total sales for the period
        total_sales = sum(inv.get('grand_total', 0) for inv in invoices)
        total_outstanding = sum(inv.get('outstanding_amount', 0) for inv in invoices)

        # Log for debugging
        logger.debug(f"get_sales_invoices: Found {len(invoices)} invoices for period {start_date} to {end_date}, total: {total_sales}")

        return json.dumps({
            'invoices': invoices[:100],  # Return max 100 detailed records
            'total_count': len(invoices),
            'total_sales': total_sales,
            'total_outstanding': total_outstanding,
            'period': {'start': start_date, 'end': end_date},
            'truncated': len(invoices) > 100,
            'message': f"Found {len(invoices)} invoices with total sales of {total_sales}"
        }, default=json_serial)
    except Exception as e:
        frappe.log_error(f"Error in get_sales_invoices: {str(e)}", "OpenAI Tool Error")
        return json.dumps({
            'error': str(e),
            'invoices': [],
            'total_count': 0,
            'total_sales': 0
        }, default=json_serial)

get_sales_invoices_tool = {
    "type": "function",
    "function": {
        "name": "get_sales_invoices",
        "description": "Retrieve sales invoices within a date range. Returns invoice details including customer, amounts, payment status, and items. Use when asked about sales, revenue, or customer invoices.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format",
                },
            },
            "required": ["start_date", "end_date"],
        },
    },
}


def list_invoices(
    invoice_type="Sales Invoice",
    customer=None,
    supplier=None,
    status=None,
    start_date=None,
    end_date=None,
    min_amount=None,
    max_amount=None,
    is_paid=None,
    sort_by="posting_date",
    sort_order="desc",
    limit=100,
    offset=0
):
    """
    List invoices (Sales or Purchase) with advanced filtering and sorting options
    """
    # Determine the doctype based on invoice_type
    if invoice_type not in ["Sales Invoice", "Purchase Invoice"]:
        return json.dumps({
            "error": "Invalid invoice_type. Must be 'Sales Invoice' or 'Purchase Invoice'"
        }, default=json_serial)

    filters = {}

    # Apply filters based on invoice type
    if invoice_type == "Sales Invoice":
        if customer:
            filters['customer'] = ['like', f'%{customer}%']
    else:  # Purchase Invoice
        if supplier:
            filters['supplier'] = ['like', f'%{supplier}%']

    # Common filters
    if status:
        filters['status'] = status
    if start_date and end_date:
        filters['posting_date'] = ['between', [start_date, end_date]]
    elif start_date:
        filters['posting_date'] = ['>=', start_date]
    elif end_date:
        filters['posting_date'] = ['<=', end_date]

    if min_amount and max_amount:
        filters['grand_total'] = ['between', [min_amount, max_amount]]
    elif min_amount:
        filters['grand_total'] = ['>=', min_amount]
    elif max_amount:
        filters['grand_total'] = ['<=', max_amount]

    if is_paid is not None:
        if is_paid:
            filters['outstanding_amount'] = 0
        else:
            filters['outstanding_amount'] = ['>', 0]

    # Validate sort_by field
    valid_sort_fields = ['name', 'posting_date', 'due_date', 'grand_total',
                        'outstanding_amount', 'status', 'creation', 'modified']
    if sort_by not in valid_sort_fields:
        sort_by = 'posting_date'

    # Build order_by clause
    order_by = f'{sort_by} {sort_order}'

    # Select appropriate fields based on invoice type
    if invoice_type == "Sales Invoice":
        fields = ['name', 'customer', 'customer_name', 'posting_date', 'due_date',
                 'grand_total', 'outstanding_amount', 'status', 'currency',
                 'is_return', 'creation', 'modified']
    else:
        fields = ['name', 'supplier', 'supplier_name', 'posting_date', 'due_date',
                 'grand_total', 'outstanding_amount', 'status', 'currency',
                 'is_return', 'creation', 'modified']

    invoices = frappe.db.get_all(
        invoice_type,
        filters=filters,
        fields=fields,
        order_by=order_by,
        limit_start=offset,
        limit_page_length=limit
    )

    # Get count for pagination
    total_count = frappe.db.count(invoice_type, filters=filters)

    # Calculate summary statistics - simplified approach
    if invoices:
        total_amount = sum(inv.get('grand_total', 0) for inv in invoices)
        total_outstanding = sum(inv.get('outstanding_amount', 0) for inv in invoices)
        average_amount = total_amount / len(invoices) if invoices else 0
        summary = {
            'total_invoices': len(invoices),
            'total_amount': total_amount,
            'total_outstanding': total_outstanding,
            'average_amount': average_amount
        }
    else:
        summary = {
            'total_invoices': 0,
            'total_amount': 0,
            'total_outstanding': 0,
            'average_amount': 0
        }

    return json.dumps({
        'invoice_type': invoice_type,
        'invoices': invoices,
        'total_count': total_count,
        'limit': limit,
        'offset': offset,
        'summary': summary
    }, default=json_serial)


list_invoices_tool = {
    "type": "function",
    "function": {
        "name": "list_invoices",
        "description": "List and search invoices (sales or purchase) with filters for status, date, amount, customer/supplier. Returns paginated results with summaries. Use for invoice queries requiring multiple results or complex filters.",
        "parameters": {
            "type": "object",
            "properties": {
                "invoice_type": {
                    "type": "string",
                    "description": "Type of invoice ('Sales Invoice' or 'Purchase Invoice')",
                    "default": "Sales Invoice"
                },
                "customer": {
                    "type": "string",
                    "description": "Filter by customer name (for Sales Invoice, partial match)",
                },
                "supplier": {
                    "type": "string",
                    "description": "Filter by supplier name (for Purchase Invoice, partial match)",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status (Draft, Submitted, Paid, Unpaid, Overdue, Cancelled)",
                },
                "start_date": {
                    "type": "string",
                    "description": "Filter invoices from this date (YYYY-MM-DD)",
                },
                "end_date": {
                    "type": "string",
                    "description": "Filter invoices until this date (YYYY-MM-DD)",
                },
                "min_amount": {
                    "type": "number",
                    "description": "Minimum invoice amount",
                },
                "max_amount": {
                    "type": "number",
                    "description": "Maximum invoice amount",
                },
                "is_paid": {
                    "type": "boolean",
                    "description": "Filter by payment status (true for fully paid, false for outstanding)",
                },
                "sort_by": {
                    "type": "string",
                    "description": "Field to sort by (name, posting_date, due_date, grand_total, outstanding_amount, status)",
                    "default": "posting_date"
                },
                "sort_order": {
                    "type": "string",
                    "description": "Sort order (asc/desc)",
                    "default": "desc"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of records to return",
                    "default": 100
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of records to skip",
                    "default": 0
                }
            },
            "required": [],
        },
    },
}


def get_sales_invoice(invoice_number):
    invoice = frappe.db.get_value(
        'Sales Invoice',
        invoice_number,
        '*',
        as_dict=True
    )
    return json.dumps([invoice] if invoice else [], default=json_serial)


get_sales_invoice_tool = {
    "type": "function",
    "function": {
        "name": "get_sales_invoice",
        "description": "Get complete details of a specific sales invoice including all line items, taxes, customer info, and payment status. Use when asked about a specific invoice by name/number.",
        "parameters": {
            "type": "object",
            "properties": {
                "invoice_number": {
                    "type": "string",
                    "description": "Invoice number",
                },
            },
            "required": ["invoice_number"],
        },
    },
}


def get_employees(department=None, designation=None):
    filters = {}
    if department:
        filters['department'] = department
    if designation:
        filters['designation'] = designation

    employees = frappe.db.get_all(
        'Employee',
        filters=filters,
        fields=['*']
    )
    return json.dumps(employees, default=json_serial)


get_employees_tool = {
    "type": "function",
    "function": {
        "name": "get_employees",
        "description": "List employees filtered by department or designation. Returns employee names, departments, designations, and employment status. Use for HR queries or workforce analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "department": {
                    "type": "string",
                    "description": "Department",
                },
                "designation": {
                    "type": "string",
                    "description": "Designation",
                },
            },
            "required": [],
        },
    },
}


def get_purchase_orders(start_date=None, end_date=None, supplier=None):
    filters = {}
    if start_date and end_date:
        filters['transaction_date'] = ['between', [start_date, end_date]]
    if supplier:
        filters['supplier'] = supplier

    purchase_orders = frappe.db.get_all(
        'Purchase Order',
        filters=filters,
        fields=['*']
    )
    return json.dumps(purchase_orders, default=json_serial)


get_purchase_orders_tool = {
    "type": "function",
    "function": {
        "name": "get_purchase_orders",
        "description": "Retrieve purchase orders within a date range, optionally filtered by supplier. Returns order details, amounts, and supplier information. Use for procurement and supplier analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format",
                },
                "supplier": {
                    "type": "string",
                    "description": "Supplier name",
                },
            },
            "required": ["start_date", "end_date"],
        },
    },
}


def get_customers(customer_name=None):
    filters = {}
    if customer_name:
        # Use partial match for customer name search
        filters['customer_name'] = ['like', f'%{customer_name}%']

    customers = frappe.db.get_all(
        'Customer',
        filters=filters,
        fields=['*']
    )
    return json.dumps(customers, default=json_serial)


get_customers_tool = {
    "type": "function",
    "function": {
        "name": "get_customers",
        "description": "Search for customers by name (partial match supported). Returns customer details including group, type, and territory. Use when searching for specific customers.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_name": {
                    "type": "string",
                    "description": "Customer name to search for (partial match supported)",
                },
            },
            "required": [],
        },
    },
}


def list_customers(
    customer_name=None,
    customer_group=None,
    territory=None,
    customer_type=None,
    disabled=None,
    sort_by="creation",
    sort_order="desc",
    limit=100,
    offset=0
):
    """
    List customers with advanced filtering and sorting options
    """
    filters = {}

    # Apply filters
    if customer_name:
        filters['customer_name'] = ['like', f'%{customer_name}%']
    if customer_group:
        filters['customer_group'] = customer_group
    if territory:
        filters['territory'] = territory
    if customer_type:
        filters['customer_type'] = customer_type
    if disabled is not None:
        filters['disabled'] = disabled

    # Validate sort_by field
    valid_sort_fields = ['customer_name', 'customer_group', 'territory', 'creation', 'modified']
    if sort_by not in valid_sort_fields:
        sort_by = 'creation'

    # Build order_by clause
    order_by = f'{sort_by} {sort_order}'

    customers = frappe.db.get_all(
        'Customer',
        filters=filters,
        fields=['name', 'customer_name', 'customer_group', 'territory',
                'customer_type', 'disabled', 'creation', 'modified',
                'credit_limit', 'customer_primary_contact', 'customer_primary_address'],
        order_by=order_by,
        limit_start=offset,
        limit_page_length=limit
    )

    # Get count for pagination
    total_count = frappe.db.count('Customer', filters=filters)

    return json.dumps({
        'customers': customers,
        'total_count': total_count,
        'limit': limit,
        'offset': offset
    }, default=json_serial)


list_customers_tool = {
    "type": "function",
    "function": {
        "name": "list_customers",
        "description": "List and search customers with filters for name, group, territory, type. Returns customer details with contact info and credit limits. Use for customer database queries and segmentation.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_name": {
                    "type": "string",
                    "description": "Filter by customer name (partial match)",
                },
                "customer_group": {
                    "type": "string",
                    "description": "Filter by customer group",
                },
                "territory": {
                    "type": "string",
                    "description": "Filter by territory",
                },
                "customer_type": {
                    "type": "string",
                    "description": "Filter by customer type (Company/Individual)",
                },
                "disabled": {
                    "type": "boolean",
                    "description": "Filter by enabled/disabled status",
                },
                "sort_by": {
                    "type": "string",
                    "description": "Field to sort by (customer_name, customer_group, territory, creation, modified)",
                    "default": "creation"
                },
                "sort_order": {
                    "type": "string",
                    "description": "Sort order (asc/desc)",
                    "default": "desc"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of records to return",
                    "default": 100
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of records to skip",
                    "default": 0
                }
            },
            "required": [],
        },
    },
}


def get_stock_levels(item_code=None):
    filters = {}
    if item_code:
        filters['item_code'] = item_code

    stock_levels = frappe.db.get_all(
        'Bin',
        filters=filters,
        fields=['item_code', 'warehouse', 'actual_qty']
    )
    return json.dumps(stock_levels, default=json_serial)


get_stock_levels_tool = {
    "type": "function",
    "function": {
        "name": "get_stock_levels",
        "description": "Get current stock quantities for items across all warehouses. Returns available quantity, reserved quantity, and warehouse-wise breakdown. Use for inventory queries.",
        "parameters": {
            "type": "object",
            "properties": {
                "item_code": {
                    "type": "string",
                    "description": "Item code",
                },
            },
            "required": [],
        },
    },
}


def get_general_ledger_entries(start_date=None, end_date=None, account=None):
    filters = {}
    if start_date and end_date:
        filters['posting_date'] = ['between', [start_date, end_date]]
    if account:
        filters['account'] = account

    gl_entries = frappe.db.get_all(
        'GL Entry',
        filters=filters,
        fields=['*']
    )
    return json.dumps(gl_entries, default=json_serial)


get_general_ledger_entries_tool = {
    "type": "function",
    "function": {
        "name": "get_general_ledger_entries",
        "description": "Retrieve general ledger entries for accounting analysis. Returns debit/credit entries with account details, voucher references, and balances. Use for financial transaction queries.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format",
                },
                "account": {
                    "type": "string",
                    "description": "Account name",
                },
            },
            "required": ["start_date", "end_date"],
        },
    },
}


def get_profit_and_loss_statement(
    period_start_date=None, period_end_date=None, periodicity=None
):
    if not period_start_date or not period_end_date or not periodicity:
        return json.dumps(
            {
                "error": "period_start_date, periodicity and period_end_date are required"
            },
            default=json_serial,
        )

    report = frappe.get_doc("Report", "Profit and Loss Statement")
    filters = {
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
        "periodicity": periodicity,
        "company": frappe.defaults.get_user_default("company"),
    }


get_profit_and_loss_statement_tool = {
    "type": "function",
    "function": {
        "name": "get_profit_and_loss_statement",
        "description": "Generate profit and loss statement showing income, expenses, and net profit/loss for a period. Returns hierarchical account breakdown with totals. Use for financial performance analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "period_start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format",
                },
                "period_end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format",
                },
                "periodicity": {
                    "type": "string",
                    "description": "Periodicity of the report (e.g., Monthly, Quarterly, Yearly, Half-Yearly)",
                },
            },
            "required": ["period_start_date", "period_end_date", "periodicity"],
        },
    },
}


def get_outstanding_invoices(customer=None):
    filters = {'outstanding_amount': ['>', 0]}
    if customer:
        filters['customer'] = customer

    invoices = frappe.db.get_all(
        'Sales Invoice',
        filters=filters,
        fields=['*']
    )
    return json.dumps(invoices, default=json_serial)


get_outstanding_invoices_tool = {
    "type": "function",
    "function": {
        "name": "get_outstanding_invoices",
        "description": "List unpaid or partially paid invoices. Returns invoice details with outstanding amounts, due dates, and aging. Use for accounts receivable analysis or collection follow-ups.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer": {
                    "type": "string",
                    "description": "Customer name",
                },
            },
            "required": [],
        },
    },
}

def get_sales_orders(start_date=None, end_date=None, customer=None):
    filters = {}
    if start_date and end_date:
        filters['transaction_date'] = ['between', [start_date, end_date]]
    if customer:
        filters['customer'] = customer

    sales_orders = frappe.db.get_all(
        'Sales Order',
        filters=filters,
        fields=['*']
    )
    return json.dumps(sales_orders, default=json_serial)


get_sales_orders_tool = {
    "type": "function",
    "function": {
        "name": "get_sales_orders",
        "description": "Retrieve sales orders within a date range, optionally filtered by customer. Returns order details, delivery status, and billing status. Use for sales pipeline and order tracking.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format",
                },
                "customer": {
                    "type": "string",
                    "description": "Customer name",
                },
            },
            "required": ["start_date", "end_date"],
        },
    },
}


def list_quotations(
    customer=None,
    quotation_to=None,
    status=None,
    start_date=None,
    end_date=None,
    valid_till_start=None,
    valid_till_end=None,
    min_amount=None,
    max_amount=None,
    sort_by="transaction_date",
    sort_order="desc",
    limit=100,
    offset=0
):
    """
    List quotations with advanced filtering and sorting options
    """
    filters = {}

    # Apply filters
    if customer:
        filters['party_name'] = ['like', f'%{customer}%']
    if quotation_to:
        filters['quotation_to'] = quotation_to  # 'Customer' or 'Lead'
    if status:
        filters['status'] = status  # Draft, Submitted, Ordered, Lost, Cancelled, Expired

    # Transaction date filters
    if start_date and end_date:
        filters['transaction_date'] = ['between', [start_date, end_date]]
    elif start_date:
        filters['transaction_date'] = ['>=', start_date]
    elif end_date:
        filters['transaction_date'] = ['<=', end_date]

    # Valid till date filters
    if valid_till_start and valid_till_end:
        filters['valid_till'] = ['between', [valid_till_start, valid_till_end]]
    elif valid_till_start:
        filters['valid_till'] = ['>=', valid_till_start]
    elif valid_till_end:
        filters['valid_till'] = ['<=', valid_till_end]

    # Amount filters
    if min_amount and max_amount:
        filters['grand_total'] = ['between', [min_amount, max_amount]]
    elif min_amount:
        filters['grand_total'] = ['>=', min_amount]
    elif max_amount:
        filters['grand_total'] = ['<=', max_amount]

    # Validate sort_by field
    valid_sort_fields = ['name', 'transaction_date', 'valid_till', 'grand_total',
                        'status', 'party_name', 'creation', 'modified']
    if sort_by not in valid_sort_fields:
        sort_by = 'transaction_date'

    # Build order_by clause
    order_by = f'{sort_by} {sort_order}'

    quotations = frappe.db.get_all(
        'Quotation',
        filters=filters,
        fields=['name', 'quotation_to', 'party_name', 'customer_name',
                'transaction_date', 'valid_till', 'grand_total', 'status',
                'currency', 'order_type', 'creation', 'modified'],
        order_by=order_by,
        limit_start=offset,
        limit_page_length=limit
    )

    # Get count for pagination
    total_count = frappe.db.count('Quotation', filters=filters)

    # Calculate summary statistics
    if quotations:
        total_amount = sum(q.get('grand_total', 0) for q in quotations)
        average_amount = total_amount / len(quotations) if quotations else 0
        summary = {
            'total_quotations': len(quotations),
            'total_amount': total_amount,
            'average_amount': average_amount
        }
    else:
        summary = {
            'total_quotations': 0,
            'total_amount': 0,
            'average_amount': 0
        }

    return json.dumps({
        'quotations': quotations,
        'total_count': total_count,
        'limit': limit,
        'offset': offset,
        'summary': summary
    }, default=json_serial)


list_quotations_tool = {
    "type": "function",
    "function": {
        "name": "list_quotations",
        "description": "List and search quotations/proposals with filters for customer, status, date, amount. Returns quotation details with validity and conversion status. Use for sales pipeline and quote tracking.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer": {
                    "type": "string",
                    "description": "Filter by customer/lead name (partial match)",
                },
                "quotation_to": {
                    "type": "string",
                    "description": "Filter by quotation type ('Customer' or 'Lead')",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status (Draft, Submitted, Ordered, Lost, Cancelled, Expired)",
                },
                "start_date": {
                    "type": "string",
                    "description": "Filter quotations from this transaction date (YYYY-MM-DD)",
                },
                "end_date": {
                    "type": "string",
                    "description": "Filter quotations until this transaction date (YYYY-MM-DD)",
                },
                "valid_till_start": {
                    "type": "string",
                    "description": "Filter by minimum validity date (YYYY-MM-DD)",
                },
                "valid_till_end": {
                    "type": "string",
                    "description": "Filter by maximum validity date (YYYY-MM-DD)",
                },
                "min_amount": {
                    "type": "number",
                    "description": "Minimum quotation amount",
                },
                "max_amount": {
                    "type": "number",
                    "description": "Maximum quotation amount",
                },
                "sort_by": {
                    "type": "string",
                    "description": "Field to sort by (name, transaction_date, valid_till, grand_total, status, party_name)",
                    "default": "transaction_date"
                },
                "sort_order": {
                    "type": "string",
                    "description": "Sort order (asc/desc)",
                    "default": "desc"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of records to return",
                    "default": 100
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of records to skip",
                    "default": 0
                }
            },
            "required": [],
        },
    },
}


def list_sales_orders(
    customer=None,
    status=None,
    delivery_status=None,
    billing_status=None,
    start_date=None,
    end_date=None,
    delivery_date_start=None,
    delivery_date_end=None,
    min_amount=None,
    max_amount=None,
    sort_by="transaction_date",
    sort_order="desc",
    limit=100,
    offset=0
):
    """
    List sales orders with advanced filtering and sorting options
    """
    filters = {}

    # Apply filters
    if customer:
        filters['customer'] = ['like', f'%{customer}%']
    if status:
        filters['status'] = status  # Draft, To Deliver and Bill, To Bill, To Deliver, Completed, Cancelled, Closed
    if delivery_status:
        filters['delivery_status'] = delivery_status  # Not Delivered, Fully Delivered, Partly Delivered, Closed, Not Applicable
    if billing_status:
        filters['billing_status'] = billing_status  # Not Billed, Fully Billed, Partly Billed, Closed

    # Transaction date filters
    if start_date and end_date:
        filters['transaction_date'] = ['between', [start_date, end_date]]
    elif start_date:
        filters['transaction_date'] = ['>=', start_date]
    elif end_date:
        filters['transaction_date'] = ['<=', end_date]

    # Delivery date filters
    if delivery_date_start and delivery_date_end:
        filters['delivery_date'] = ['between', [delivery_date_start, delivery_date_end]]
    elif delivery_date_start:
        filters['delivery_date'] = ['>=', delivery_date_start]
    elif delivery_date_end:
        filters['delivery_date'] = ['<=', delivery_date_end]

    # Amount filters
    if min_amount and max_amount:
        filters['grand_total'] = ['between', [min_amount, max_amount]]
    elif min_amount:
        filters['grand_total'] = ['>=', min_amount]
    elif max_amount:
        filters['grand_total'] = ['<=', max_amount]

    # Validate sort_by field
    valid_sort_fields = ['name', 'transaction_date', 'delivery_date', 'grand_total',
                        'status', 'customer', 'per_delivered', 'per_billed', 'creation', 'modified']
    if sort_by not in valid_sort_fields:
        sort_by = 'transaction_date'

    # Build order_by clause
    order_by = f'{sort_by} {sort_order}'

    sales_orders = frappe.db.get_all(
        'Sales Order',
        filters=filters,
        fields=['name', 'customer', 'customer_name', 'transaction_date', 'delivery_date',
                'grand_total', 'status', 'delivery_status', 'billing_status',
                'per_delivered', 'per_billed', 'currency', 'order_type',
                'creation', 'modified'],
        order_by=order_by,
        limit_start=offset,
        limit_page_length=limit
    )

    # Get count for pagination
    total_count = frappe.db.count('Sales Order', filters=filters)

    # Calculate summary statistics
    if sales_orders:
        total_amount = sum(so.get('grand_total', 0) for so in sales_orders)
        average_amount = total_amount / len(sales_orders) if sales_orders else 0
        avg_delivery = sum(so.get('per_delivered', 0) for so in sales_orders) / len(sales_orders)
        avg_billed = sum(so.get('per_billed', 0) for so in sales_orders) / len(sales_orders)
        summary = {
            'total_orders': len(sales_orders),
            'total_amount': total_amount,
            'average_amount': average_amount,
            'average_delivery_percentage': avg_delivery,
            'average_billing_percentage': avg_billed
        }
    else:
        summary = {
            'total_orders': 0,
            'total_amount': 0,
            'average_amount': 0,
            'average_delivery_percentage': 0,
            'average_billing_percentage': 0
        }

    return json.dumps({
        'sales_orders': sales_orders,
        'total_count': total_count,
        'limit': limit,
        'offset': offset,
        'summary': summary
    }, default=json_serial)


list_sales_orders_tool = {
    "type": "function",
    "function": {
        "name": "list_sales_orders",
        "description": "List and search sales orders with filters for customer, delivery/billing status, dates, amounts. Returns order details with fulfillment percentages. Use for order management and fulfillment tracking.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer": {
                    "type": "string",
                    "description": "Filter by customer name (partial match)",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by order status",
                },
                "delivery_status": {
                    "type": "string",
                    "description": "Filter by delivery status (Not Delivered, Fully Delivered, Partly Delivered, etc.)",
                },
                "billing_status": {
                    "type": "string",
                    "description": "Filter by billing status (Not Billed, Fully Billed, Partly Billed, Closed)",
                },
                "start_date": {
                    "type": "string",
                    "description": "Filter orders from this transaction date (YYYY-MM-DD)",
                },
                "end_date": {
                    "type": "string",
                    "description": "Filter orders until this transaction date (YYYY-MM-DD)",
                },
                "delivery_date_start": {
                    "type": "string",
                    "description": "Filter by minimum delivery date (YYYY-MM-DD)",
                },
                "delivery_date_end": {
                    "type": "string",
                    "description": "Filter by maximum delivery date (YYYY-MM-DD)",
                },
                "min_amount": {
                    "type": "number",
                    "description": "Minimum order amount",
                },
                "max_amount": {
                    "type": "number",
                    "description": "Maximum order amount",
                },
                "sort_by": {
                    "type": "string",
                    "description": "Field to sort by (name, transaction_date, delivery_date, grand_total, status, customer, per_delivered, per_billed)",
                    "default": "transaction_date"
                },
                "sort_order": {
                    "type": "string",
                    "description": "Sort order (asc/desc)",
                    "default": "desc"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of records to return",
                    "default": 100
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of records to skip",
                    "default": 0
                }
            },
            "required": [],
        },
    },
}


def get_delivery_note(delivery_note_number):
    """
    Get complete details of a specific delivery note including all line items and serial numbers
    """
    # Get main delivery note document
    delivery_note = frappe.db.get_value(
        'Delivery Note',
        delivery_note_number,
        ['*'],
        as_dict=True
    )

    if not delivery_note:
        return json.dumps({'error': f'Delivery Note {delivery_note_number} not found'}, default=json_serial)

    # Get all line items
    items = frappe.db.get_all(
        'Delivery Note Item',
        filters={'parent': delivery_note_number},
        fields=['*']
    )

    # Collect all serial numbers
    serial_numbers_by_item = {}

    # First, check serial_and_batch_bundle from Delivery Note Items
    for item in items:
        if item.get('serial_and_batch_bundle'):
            # Get serial numbers from the bundle
            serials = frappe.db.get_all(
                'Serial and Batch Entry',
                filters={'parent': item['serial_and_batch_bundle']},
                fields=['serial_no', 'qty']
            )

            if serials:
                if item['item_code'] not in serial_numbers_by_item:
                    serial_numbers_by_item[item['item_code']] = []

                for serial in serials:
                    serial_numbers_by_item[item['item_code']].append({
                        'serial_no': serial.serial_no,
                        'qty': abs(serial.qty),  # Use absolute value since qty might be negative
                        'warehouse': item.get('warehouse', '')
                    })

    # Also check Stock Ledger Entry as fallback
    stock_entries = frappe.db.get_all(
        'Stock Ledger Entry',
        filters={
            'voucher_no': delivery_note_number,
            'voucher_type': 'Delivery Note'
        },
        fields=['item_code', 'serial_and_batch_bundle', 'actual_qty', 'warehouse']
    )

    for entry in stock_entries:
        if entry.serial_and_batch_bundle and entry.item_code not in serial_numbers_by_item:
            # Get serial numbers from the bundle
            serials = frappe.db.get_all(
                'Serial and Batch Entry',
                filters={'parent': entry.serial_and_batch_bundle},
                fields=['serial_no', 'qty']
            )

            if entry.item_code not in serial_numbers_by_item:
                serial_numbers_by_item[entry.item_code] = []

            for serial in serials:
                serial_numbers_by_item[entry.item_code].append({
                    'serial_no': serial.serial_no,
                    'qty': abs(serial.qty),  # Use absolute value since qty might be negative
                    'warehouse': entry.warehouse
                })

    # Add serial numbers to items
    for item in items:
        if item['item_code'] in serial_numbers_by_item:
            item['serial_numbers'] = serial_numbers_by_item[item['item_code']]

    # Combine all data
    delivery_note['items'] = items
    delivery_note['total_serialized_items'] = len(serial_numbers_by_item)

    # Get all unique serial numbers for summary
    all_serials = []
    for item_serials in serial_numbers_by_item.values():
        all_serials.extend([s['serial_no'] for s in item_serials])
    delivery_note['all_serial_numbers'] = list(set(all_serials))

    return json.dumps(delivery_note, default=json_serial)


get_delivery_note_tool = {
    "type": "function",
    "function": {
        "name": "get_delivery_note",
        "description": "Get complete details of a specific delivery note including all line items, serial numbers, customer info, and delivery status. Use when asked about a specific delivery note by name/number.",
        "parameters": {
            "type": "object",
            "properties": {
                "delivery_note_number": {
                    "type": "string",
                    "description": "Delivery note number (e.g., MAT-DN-2025-00201)",
                },
            },
            "required": ["delivery_note_number"],
        },
    },
}


def list_delivery_notes(
    customer=None,
    status=None,
    serial_number=None,
    item_code=None,
    start_date=None,
    end_date=None,
    lr_no=None,  # Lorry Receipt Number / Tracking Number
    transporter=None,
    sort_by="posting_date",
    sort_order="desc",
    limit=100,
    offset=0
):
    """
    List delivery notes with advanced filtering, sorting options, and serial number search
    """
    filters = {}

    # Log query parameters for debugging
    logger.debug(f"list_delivery_notes called with: serial_number={serial_number}, start_date={start_date}, end_date={end_date}, limit={limit}")

    # Handle serial number search - first find Serial and Batch Bundle, then filter
    serial_number_note_names = None  # Track delivery notes found via serial number
    if serial_number:
        # Step 1: Find Serial and Batch Bundle containing the serial number
        serial_bundles = frappe.db.get_all(
            'Serial and Batch Entry',
            filters={
                'serial_no': ['like', f'%{serial_number}%']
            },
            fields=['parent'],
            distinct=True
        )

        logger.debug(f"Found {len(serial_bundles) if serial_bundles else 0} serial bundles for serial {serial_number}")

        if serial_bundles:
            # Extract bundle names
            bundle_names = [bundle.parent for bundle in serial_bundles]

            # Step 2: Find delivery notes containing these bundles
            # Use Stock Ledger Entry as the authoritative source for serial tracking
            stock_ledger_entries = frappe.db.get_all(
                'Stock Ledger Entry',
                filters={
                    'serial_and_batch_bundle': ['in', bundle_names],
                    'voucher_type': 'Delivery Note'
                },
                fields=['voucher_no'],
                distinct=True
            )

            # Extract delivery note names from stock ledger entries
            note_names = [entry.voucher_no for entry in stock_ledger_entries] if stock_ledger_entries else []

            logger.debug(f"Found {len(note_names)} delivery notes with serial {serial_number} via Stock Ledger Entry")

            if note_names:
                serial_number_note_names = note_names  # Store for later use
                filters['name'] = ['in', note_names]
                logger.debug(f"Delivery notes with serial {serial_number}: {note_names}")
            else:
                # No delivery notes found with this serial number
                return json.dumps({
                    'delivery_notes': [],
                    'total_count': 0,
                    'limit': limit,
                    'offset': offset,
                    'summary': {
                        'total_notes': 0,
                        'total_amount': 0,
                        'average_amount': 0
                    }
                }, default=json_serial)
        else:
            # No serial bundles found with this serial number
            return json.dumps({
                'delivery_notes': [],
                'total_count': 0,
                'limit': limit,
                'offset': offset,
                'summary': {
                    'total_notes': 0,
                    'total_amount': 0,
                    'average_amount': 0
                }
            }, default=json_serial)

    # Apply other filters
    if customer:
        filters['customer'] = ['like', f'%{customer}%']
    if status:
        filters['status'] = status  # Draft, To Bill, Completed, Cancelled, Closed
    if lr_no:
        filters['lr_no'] = ['like', f'%{lr_no}%']
    if transporter:
        filters['transporter'] = ['like', f'%{transporter}%']

    # Date filters - only apply if no serial number search OR if explicitly requested
    # When searching by serial number, we want ALL matching delivery notes regardless of date
    # unless the user explicitly provides date filters
    if not serial_number:
        # Apply date filters normally when not searching by serial number
        if start_date and end_date:
            filters['posting_date'] = ['between', [start_date, end_date]]
        elif start_date:
            filters['posting_date'] = ['>=', start_date]
        elif end_date:
            filters['posting_date'] = ['<=', end_date]
    else:
        # For serial number searches, only apply date filters if explicitly provided by user
        # This prevents implicit date filtering that might exclude recent delivery notes
        logger.debug(f"Serial number search - date filters ignored to ensure all matching notes are found")

    # Item code filter - using Frappe database API
    if item_code and not serial_number:  # If serial_number is already filtered, skip item_code
        item_filter_notes = frappe.db.get_all(
            'Delivery Note Item',
            filters={'item_code': item_code},
            fields=['parent'],
            distinct=True
        )

        if item_filter_notes:
            item_note_names = [note.parent for note in item_filter_notes]
            if 'name' in filters:
                # Intersect with existing name filter
                existing_names = filters['name'][1]
                filters['name'] = ['in', list(set(existing_names) & set(item_note_names))]
            else:
                filters['name'] = ['in', item_note_names]
        else:
            # No delivery notes found with this item
            return json.dumps({
                'delivery_notes': [],
                'total_count': 0,
                'limit': limit,
                'offset': offset,
                'summary': {
                    'total_notes': 0,
                    'total_amount': 0,
                    'average_amount': 0
                }
            }, default=json_serial)

    # Validate sort_by field
    valid_sort_fields = ['name', 'posting_date', 'customer', 'grand_total',
                        'status', 'per_billed', 'creation', 'modified']
    if sort_by not in valid_sort_fields:
        sort_by = 'posting_date'

    # Build order_by clause
    order_by = f'{sort_by} {sort_order}'

    # Log the final filters being applied
    logger.debug(f"Final filters for delivery notes query: {filters}")
    logger.debug(f"Sort: {order_by}, Limit: {limit}, Offset: {offset}")

    # When searching by serial number with limit=1, we need to ensure proper ordering
    # The issue is that frappe.db.get_all with 'name IN [...]' filter may not respect order_by correctly
    # So we need to fetch all matching records first, then sort and limit in Python
    if serial_number and limit == 1 and serial_number_note_names:
        # Fetch all delivery notes matching the serial number without limit
        all_matching_notes = frappe.db.get_all(
            'Delivery Note',
            filters=filters,
            fields=['name', 'customer', 'customer_name', 'posting_date',
                    'grand_total', 'status', 'per_billed', 'currency',
                    'lr_no', 'lr_date', 'transporter', 'vehicle_no',
                    'is_return', 'creation', 'modified'],
            order_by=order_by
        )

        logger.debug(f"Found {len(all_matching_notes)} total delivery notes for serial {serial_number}")
        for note in all_matching_notes[:3]:  # Log first 3 for debugging
            logger.debug(f"  - {note['name']}: {note['posting_date']}")

        # Apply offset and limit manually
        delivery_notes = all_matching_notes[offset:offset + limit]
    else:
        delivery_notes = frappe.db.get_all(
            'Delivery Note',
            filters=filters,
            fields=['name', 'customer', 'customer_name', 'posting_date',
                    'grand_total', 'status', 'per_billed', 'currency',
                    'lr_no', 'lr_date', 'transporter', 'vehicle_no',
                    'is_return', 'creation', 'modified'],
            order_by=order_by,
            limit_start=offset,
            limit_page_length=limit
        )

    logger.debug(f"Query returned {len(delivery_notes) if delivery_notes else 0} delivery notes")
    if delivery_notes and serial_number:
        logger.debug(f"Top result: {delivery_notes[0]['name']} dated {delivery_notes[0]['posting_date']}")

    # If serial number was searched, add serial number info to results
    if serial_number and delivery_notes:
        for note in delivery_notes:
            # Get items with the matching serial and batch bundle using Frappe Query Builder
            from frappe.query_builder import DocType

            DeliveryNoteItem = DocType('Delivery Note Item')
            SerialBatchEntry = DocType('Serial and Batch Entry')

            # Get delivery note items with their bundles
            items = frappe.db.get_all(
                'Delivery Note Item',
                filters={'parent': note['name']},
                fields=['item_code', 'item_name', 'serial_and_batch_bundle', 'qty']
            )

            matched_items = []
            for item in items:
                if item.serial_and_batch_bundle:
                    # Get serial numbers from the bundle
                    serials = frappe.db.get_all(
                        'Serial and Batch Entry',
                        filters={
                            'parent': item.serial_and_batch_bundle,
                            'serial_no': ['like', f'%{serial_number}%']
                        },
                        fields=['serial_no']
                    )
                    if serials:
                        item['serial_numbers'] = ', '.join([s.serial_no for s in serials])
                        matched_items.append(item)

            note['matched_serial_items'] = matched_items

    # Get count for pagination
    total_count = frappe.db.count('Delivery Note', filters=filters)

    # Calculate summary statistics
    if delivery_notes:
        total_amount = sum(dn.get('grand_total', 0) for dn in delivery_notes)
        average_amount = total_amount / len(delivery_notes) if delivery_notes else 0
        avg_billed = sum(dn.get('per_billed', 0) for dn in delivery_notes) / len(delivery_notes)
        summary = {
            'total_notes': len(delivery_notes),
            'total_amount': total_amount,
            'average_amount': average_amount,
            'average_billing_percentage': avg_billed
        }
    else:
        summary = {
            'total_notes': 0,
            'total_amount': 0,
            'average_amount': 0,
            'average_billing_percentage': 0
        }

    return json.dumps({
        'delivery_notes': delivery_notes,
        'total_count': total_count,
        'limit': limit,
        'offset': offset,
        'summary': summary
    }, default=json_serial)


list_delivery_notes_tool = {
    "type": "function",
    "function": {
        "name": "list_delivery_notes",
        "description": "Search and list delivery notes (shipment documents). Returns shipment details with items and billing status. Use for logistics, delivery tracking, and serial number searches.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer": {
                    "type": "string",
                    "description": "Filter by customer name (partial match)",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status (Draft, To Bill, Completed, Cancelled, Closed)",
                },
                "serial_number": {
                    "type": "string",
                    "description": "Search for delivery notes containing this serial number (partial match)",
                },
                "item_code": {
                    "type": "string",
                    "description": "Filter by item code in delivery note items",
                },
                "start_date": {
                    "type": "string",
                    "description": "Filter notes from this posting date (YYYY-MM-DD)",
                },
                "end_date": {
                    "type": "string",
                    "description": "Filter notes until this posting date (YYYY-MM-DD)",
                },
                "lr_no": {
                    "type": "string",
                    "description": "Filter by Lorry Receipt Number / Tracking Number (partial match)",
                },
                "transporter": {
                    "type": "string",
                    "description": "Filter by transporter name (partial match)",
                },
                "sort_by": {
                    "type": "string",
                    "description": "Field to sort by (name, posting_date, customer, grand_total, status, per_billed)",
                    "default": "posting_date"
                },
                "sort_order": {
                    "type": "string",
                    "description": "Sort order (asc/desc)",
                    "default": "desc"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of records to return",
                    "default": 100
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of records to skip",
                    "default": 0
                }
            },
            "required": [],
        },
    },
}


def get_purchase_invoices(start_date=None, end_date=None, supplier=None):
    filters = {}
    if start_date and end_date:
        filters['posting_date'] = ['between', [start_date, end_date]]
    if supplier:
        filters['supplier'] = supplier

    purchase_invoices = frappe.db.get_all(
        'Purchase Invoice',
        filters=filters,
        fields=['*']
    )
    return json.dumps(purchase_invoices, default=json_serial)



get_purchase_invoices_tool = {
    "type": "function",
    "function": {
        "name": "get_purchase_invoices",
        "description": "Retrieve purchase invoices within a date range, optionally filtered by supplier. Returns invoice details, amounts, and payment status. Use for accounts payable and supplier billing queries.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format",
                },
                "supplier": {
                    "type": "string",
                    "description": "Supplier name",
                },
            },
            "required": ["start_date", "end_date"],
        },
    },
}


def get_journal_entries(start_date=None, end_date=None):
    filters = {}
    if start_date and end_date:
        filters['posting_date'] = ['between', [start_date, end_date]]

    journal_entries = frappe.db.get_all(
        'Journal Entry',
        filters=filters,
        fields=['*']
    )
    return json.dumps(journal_entries, default=json_serial)


get_journal_entries_tool = {
    "type": "function",
    "function": {
        "name": "get_journal_entries",
        "description": "Retrieve journal entries (manual accounting entries) within a date range. Returns entry details with account postings and remarks. Use for accounting adjustments and manual entry queries.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format",
                },
            },
            "required": ["start_date", "end_date"],
        },
    },
}


def get_payments(start_date=None, end_date=None, payment_type=None):
    filters = {}
    if start_date and end_date:
        filters['posting_date'] = ['between', [start_date, end_date]]
    if payment_type:
        filters['payment_type'] = payment_type

    payment_entries = frappe.db.get_all(
        'Payment Entry',
        filters=filters,
        fields=['*']
    )
    return json.dumps(payment_entries, default=json_serial)


get_payments_tool = {
    "type": "function",
    "function": {
        "name": "get_payments",
        "description": "Retrieve payment entries showing money received or paid. Returns payment details, references, and bank/cash accounts used. Use for cash flow and payment tracking.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format",
                },
                "payment_type": {
                    "type": "string",
                    "description": "Payment type (e.g., Receive, Pay)",
                },
            },
            "required": ["start_date", "end_date"],
        },
    },
}


def list_service_protocols(
    customer=None,
    status=None,
    date_from=None,
    date_to=None,
    serial_number=None,
    sort_by='date_of_service',
    sort_order='desc',
    limit=10,
    offset=0
):
    """
    List Service Protocols with filtering, sorting, and pagination.
    Can filter by customer, status, date range, or serial number in devices.
    """
    import frappe
    import json
    from datetime import datetime

    filters = {}

    # Add basic filters
    if customer:
        filters['customer'] = customer

    if status:
        filters['docstatus'] = {
            'Draft': 0,
            'Submitted': 1,
            'Cancelled': 2
        }.get(status, 0)

    # Date range filter
    if date_from and date_to:
        filters['date_of_service'] = ['between', [date_from, date_to]]
    elif date_from:
        filters['date_of_service'] = ['>=', date_from]
    elif date_to:
        filters['date_of_service'] = ['<=', date_to]

    # Handle serial number search in child table
    if serial_number:
        # Find service protocols containing this serial number
        protocol_items = frappe.db.get_all(
            'Service Protocol Item',
            filters={'serial_number': serial_number},
            fields=['parent'],
            distinct=True
        )

        if protocol_items:
            protocol_names = [item.parent for item in protocol_items]
            filters['name'] = ['in', protocol_names]
        else:
            # No protocols found with this serial number
            return json.dumps({
                'service_protocols': [],
                'total_count': 0,
                'limit': limit,
                'offset': offset,
                'summary': {}
            }, default=json_serial)

    # Validate sort_by field
    valid_sort_fields = ['name', 'customer', 'date_of_service', 'creation', 'modified']
    if sort_by not in valid_sort_fields:
        sort_by = 'date_of_service'

    # Build order by clause
    order_by = f'{sort_by} {sort_order}'

    # Get service protocols
    service_protocols = frappe.db.get_all(
        'Service Protocol',
        filters=filters,
        fields=['name', 'customer', 'date_of_service', 'notes', 'docstatus',
                'creation', 'modified', 'owner'],
        order_by=order_by,
        limit=limit,
        start=offset
    )

    # Add customer name and status for each protocol
    for protocol in service_protocols:
        # Get customer name
        if protocol.get('customer'):
            customer_name = frappe.db.get_value('Customer', protocol['customer'], 'customer_name')
            protocol['customer_name'] = customer_name

        # Add human-readable status
        protocol['status'] = {
            0: 'Draft',
            1: 'Submitted',
            2: 'Cancelled'
        }.get(protocol.get('docstatus', 0), 'Draft')

        # Get device count
        device_count = frappe.db.count('Service Protocol Item', {'parent': protocol['name']})
        protocol['device_count'] = device_count

    # Get total count for pagination
    total_count = frappe.db.count('Service Protocol', filters=filters)

    # Calculate summary statistics
    summary = {}
    if service_protocols:
        summary = {
            'total_protocols': len(service_protocols),
            'total_devices_serviced': sum(p.get('device_count', 0) for p in service_protocols),
            'date_range': {
                'earliest': min(p['date_of_service'] for p in service_protocols if p.get('date_of_service')),
                'latest': max(p['date_of_service'] for p in service_protocols if p.get('date_of_service'))
            } if any(p.get('date_of_service') for p in service_protocols) else None
        }

    return json.dumps({
        'service_protocols': service_protocols,
        'total_count': total_count,
        'limit': limit,
        'offset': offset,
        'summary': summary
    }, default=json_serial)


def create_lead(
    organization_name=None,
    first_name=None,
    last_name=None,
    email=None,
    phone=None,
    country=None
):
    """
    Create a new Lead in ERPNext with validation.
    Requires either organization_name OR (first_name AND last_name).
    """
    try:
        # Validate required fields
        if not organization_name and not (first_name and last_name):
            return json.dumps({
                'error': 'Either organization_name OR (first_name AND last_name) is required'
            }, default=json_serial)

        # Prepare lead data
        lead_data = {
            'doctype': 'Lead'
        }

        # Set lead name based on what's provided
        if organization_name:
            lead_data['company_name'] = organization_name
            lead_data['organization_lead'] = 1
            lead_data['lead_name'] = organization_name
        else:
            lead_data['lead_name'] = f"{first_name} {last_name}"
            lead_data['first_name'] = first_name
            lead_data['last_name'] = last_name

        # Add optional fields
        if email:
            lead_data['email_id'] = email
        if phone:
            lead_data['mobile_no'] = phone

        # Handle country with validation and correction
        if country:
            # Common country name corrections
            country_corrections = {
                'usa': 'United States',
                'us': 'United States',
                'united states of america': 'United States',
                'uk': 'United Kingdom',
                'england': 'United Kingdom',
                'britain': 'United Kingdom',
                'great britain': 'United Kingdom',
                'uae': 'United Arab Emirates',
                'emirates': 'United Arab Emirates',
                'deutschland': 'Germany',
                'oesterreich': 'Austria',
                'österreich': 'Austria',
                'schweiz': 'Switzerland',
                'suisse': 'Switzerland',
                'svizzera': 'Switzerland',
                'holland': 'Netherlands',
                'the netherlands': 'Netherlands',
                'česko': 'Czech Republic',
                'czechia': 'Czech Republic',
                'slovensko': 'Slovakia',
                'belgië': 'Belgium',
                'belgique': 'Belgium',
                'sverige': 'Sweden',
                'norge': 'Norway',
                'danmark': 'Denmark',
                'suomi': 'Finland',
                'polska': 'Poland',
                'magyarország': 'Hungary',
                'hrvatska': 'Croatia',
                'slovenija': 'Slovenia',
                'srbija': 'Serbia',
                'italia': 'Italy',
                'españa': 'Spain',
                'france': 'France',
                'portugal': 'Portugal',
                'rossiya': 'Russia',
                'russia': 'Russian Federation',
                'china': 'China',
                'prc': 'China',
                'nippon': 'Japan',
                'nihon': 'Japan',
                'south korea': 'Korea, Republic of',
                'korea': 'Korea, Republic of',
                'brasil': 'Brazil',
                'méxico': 'Mexico',
                'argentina': 'Argentina',
                'chile': 'Chile',
                'colombia': 'Colombia',
                'perú': 'Peru',
                'venezuela': 'Venezuela',
                'australia': 'Australia',
                'new zealand': 'New Zealand',
                'nz': 'New Zealand',
                'india': 'India',
                'pakistan': 'Pakistan',
                'bangladesh': 'Bangladesh',
                'south africa': 'South Africa',
                'egypt': 'Egypt',
                'turkey': 'Turkey',
                'türkiye': 'Turkey',
                'saudi arabia': 'Saudi Arabia',
                'ksa': 'Saudi Arabia',
                'israel': 'Israel',
                'singapore': 'Singapore',
                'malaysia': 'Malaysia',
                'thailand': 'Thailand',
                'vietnam': 'Vietnam',
                'philippines': 'Philippines',
                'indonesia': 'Indonesia',
                'canada': 'Canada'
            }

            # Normalize country input
            country_lower = country.lower().strip()

            # Check for common corrections first
            if country_lower in country_corrections:
                country = country_corrections[country_lower]
            else:
                # Try to match with existing countries in the system
                # Capitalize first letter of each word for standard format
                country = ' '.join(word.capitalize() for word in country.split())

                # Check if the country exists in the system
                country_exists = frappe.db.exists('Country', country)
                if not country_exists:
                    # Try to find a similar country name
                    all_countries = frappe.db.get_all('Country', fields=['name'])
                    country_names = [c['name'] for c in all_countries]

                    # Check for partial matches
                    for existing_country in country_names:
                        if country.lower() in existing_country.lower() or existing_country.lower() in country.lower():
                            country = existing_country
                            break

            lead_data['country'] = country

        # Set default status
        lead_data['status'] = 'Open'

        # Create the lead document
        lead_doc = frappe.get_doc(lead_data)

        # Insert the document
        lead_doc.insert(ignore_permissions=False)

        # Commit the transaction to ensure the lead is saved
        frappe.db.commit()

        # Log the creation
        logger.debug(f"Created lead: {lead_doc.name} for {lead_data['lead_name']}")

        # Return the created lead details
        return json.dumps({
            'success': True,
            'lead_id': lead_doc.name,
            'lead_name': lead_doc.lead_name,
            'company_name': lead_doc.company_name if hasattr(lead_doc, 'company_name') else None,
            'email': lead_doc.email_id if hasattr(lead_doc, 'email_id') else None,
            'phone': lead_doc.mobile_no if hasattr(lead_doc, 'mobile_no') else None,
            'country': lead_doc.country if hasattr(lead_doc, 'country') else None,
            'status': lead_doc.status,
            'message': f"Lead {lead_doc.name} created successfully"
        }, default=json_serial)

    except frappe.exceptions.ValidationError as e:
        logger.error(f"Validation error creating lead: {str(e)}")
        return json.dumps({
            'error': f"Validation error: {str(e)}",
            'success': False
        }, default=json_serial)
    except Exception as e:
        frappe.log_error(f"Error creating lead: {str(e)}", "Lead Creation Error")
        return json.dumps({
            'error': str(e),
            'success': False
        }, default=json_serial)


create_lead_tool = {
    "type": "function",
    "function": {
        "name": "create_lead",
        "description": "Create a new lead (potential customer) in ERPNext. Use this when someone wants to add a new business prospect or potential customer. Requires either organization name OR individual's first and last name.",
        "parameters": {
            "type": "object",
            "properties": {
                "organization_name": {
                    "type": "string",
                    "description": "Name of the organization/company (use this for business leads)"
                },
                "first_name": {
                    "type": "string",
                    "description": "First name of the contact person (required if organization_name is not provided)"
                },
                "last_name": {
                    "type": "string",
                    "description": "Last name of the contact person (required if organization_name is not provided)"
                },
                "email": {
                    "type": "string",
                    "description": "Email address of the lead"
                },
                "phone": {
                    "type": "string",
                    "description": "Phone/mobile number of the lead"
                },
                "country": {
                    "type": "string",
                    "description": "Country name in English (e.g., 'United States', 'Germany', 'Austria'). Common misspellings and variations will be automatically corrected."
                }
            },
            "required": []
        }
    }
}


def get_service_protocol(protocol_name):
    """
    Get detailed information about a specific Service Protocol including all devices.
    """
    import frappe
    import json

    # Get main protocol document
    protocol = frappe.db.get_value(
        'Service Protocol',
        protocol_name,
        ['name', 'customer', 'date_of_service', 'notes', 'docstatus',
         'creation', 'modified', 'owner', 'amended_from'],
        as_dict=True
    )

    if not protocol:
        return json.dumps({'error': f'Service Protocol {protocol_name} not found'})

    # Get customer details
    if protocol.get('customer'):
        customer_details = frappe.db.get_value(
            'Customer',
            protocol['customer'],
            ['customer_name', 'customer_group', 'territory'],
            as_dict=True
        )
        protocol['customer_details'] = customer_details

    # Add human-readable status
    protocol['status'] = {
        0: 'Draft',
        1: 'Submitted',
        2: 'Cancelled'
    }.get(protocol.get('docstatus', 0), 'Draft')

    # Get all devices (Service Protocol Items)
    devices = frappe.db.get_all(
        'Service Protocol Item',
        filters={'parent': protocol_name},
        fields=['serial_number', 'note'],
        order_by='idx'
    )

    # Enrich device information with serial number details
    for device in devices:
        if device.get('serial_number'):
            serial_info = frappe.db.get_value(
                'Serial No',
                device['serial_number'],
                ['item_code', 'item_name', 'warehouse', 'status'],
                as_dict=True
            )
            if serial_info:
                device['serial_info'] = serial_info

    protocol['devices'] = devices
    protocol['total_devices'] = len(devices)

    # Get amendment history if this is an amended document
    if protocol.get('amended_from'):
        protocol['amendment_history'] = []
        current = protocol.get('amended_from')
        while current:
            amendment = frappe.db.get_value(
                'Service Protocol',
                current,
                ['name', 'date_of_service', 'modified'],
                as_dict=True
            )
            if amendment:
                protocol['amendment_history'].append(amendment)
                current = frappe.db.get_value('Service Protocol', current, 'amended_from')
            else:
                break

    return json.dumps(protocol, default=json_serial)


# Tool definitions for Service Protocol
list_service_protocols_tool = {
    "type": "function",
    "function": {
        "name": "list_service_protocols",
        "description": "List or find Service Protocols. Can search by serial number to find which service protocol contains a specific device. Service Protocols track maintenance and service activities performed on devices. Use this to find service protocols for specific serial numbers like 'Find service protocol for serial number OCU-00001'.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer": {
                    "type": "string",
                    "description": "Filter by customer name or ID"
                },
                "status": {
                    "type": "string",
                    "enum": ["Draft", "Submitted", "Cancelled"],
                    "description": "Document status"
                },
                "date_from": {
                    "type": "string",
                    "description": "Start date for service date range (YYYY-MM-DD)"
                },
                "date_to": {
                    "type": "string",
                    "description": "End date for service date range (YYYY-MM-DD)"
                },
                "serial_number": {
                    "type": "string",
                    "description": "Find service protocols containing this serial number (e.g., 'OCU-00001'). Use this when asked to find service protocol for a specific serial number"
                },
                "sort_by": {
                    "type": "string",
                    "enum": ["name", "customer", "date_of_service", "creation", "modified"],
                    "description": "Field to sort by (default: date_of_service)"
                },
                "sort_order": {
                    "type": "string",
                    "enum": ["asc", "desc"],
                    "description": "Sort order (default: desc)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of records to return (default: 10, max: 100)"
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of records to skip for pagination"
                }
            },
            "required": []
        }
    }
}

get_service_protocol_tool = {
    "type": "function",
    "function": {
        "name": "get_service_protocol",
        "description": "Get detailed information about a specific Service Protocol including all serviced devices, customer details, and amendment history",
        "parameters": {
            "type": "object",
            "properties": {
                "protocol_name": {
                    "type": "string",
                    "description": "The Service Protocol document name (e.g., SVP-2025-0001)"
                }
            },
            "required": ["protocol_name"]
        }
    }
}


def get_tools():
    return [
        # Entity lookup tool - should be used first to resolve informal names
        lookup_entity_tool,
        # Document query tools
        get_sales_invoices_tool,
        get_sales_invoice_tool,
        list_invoices_tool,
        get_employees_tool,
        get_purchase_orders_tool,
        get_customers_tool,
        list_customers_tool,
        get_stock_levels_tool,
        get_general_ledger_entries_tool,
        get_profit_and_loss_statement_tool,
        get_outstanding_invoices_tool,
        get_sales_orders_tool,
        list_quotations_tool,
        list_sales_orders_tool,
        list_delivery_notes_tool,
        get_delivery_note_tool,
        get_purchase_invoices_tool,
        get_journal_entries_tool,
        get_payments_tool,
        list_service_protocols_tool,
        get_service_protocol_tool,
        create_lead_tool,
    ]


available_functions = {
    "lookup_entity": lookup_entity,
    "get_sales_invoices": get_sales_invoices,
    "get_sales_invoice": get_sales_invoice,
    "list_invoices": list_invoices,
    "get_employees": get_employees,
    "get_purchase_orders": get_purchase_orders,
    "get_customers": get_customers,
    "list_customers": list_customers,
    "get_stock_levels": get_stock_levels,
    "get_general_ledger_entries": get_general_ledger_entries,
    "get_profit_and_loss_statement": get_profit_and_loss_statement,
    "get_outstanding_invoices": get_outstanding_invoices,
    "get_sales_orders": get_sales_orders,
    "list_quotations": list_quotations,
    "list_sales_orders": list_sales_orders,
    "list_delivery_notes": list_delivery_notes,
    "get_delivery_note": get_delivery_note,
    "get_purchase_invoices": get_purchase_invoices,
    "get_journal_entries": get_journal_entries,
    "get_payments": get_payments,
    "list_service_protocols": list_service_protocols,
    "get_service_protocol": get_service_protocol,
    "create_lead": create_lead,
}
