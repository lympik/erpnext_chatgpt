# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Important Environment Notes

**Bench is NOT installed locally** - All bench commands must be executed on the server, not on the local development machine. The local repository is synced with the server where ERPNext/Frappe is running.

## Commands (Execute on Server)

### Development
- **Install app on ERPNext site**: `bench --site [site-name] install-app erpnext_chatgpt`
- **Restart bench**: `bench restart`
- **Clear cache**: `bench clear-cache`
- **Console access**: `bench console` (for Python/ERPNext shell)
- **Migrate database**: `bench --site [site-name] migrate`

### Testing
- **Run doctests**: `bench --site [site-name] run-tests --app erpnext_chatgpt`
- **Test specific doctype**: `bench --site [site-name] run-tests --doctype "OpenAI Settings"`

### Debugging Commands for Server

#### Test Delivery Note Serial Numbers
```python
# In bench console
import frappe
from erpnext_chatgpt.erpnext_chatgpt.tools import get_delivery_note

# Test a specific delivery note
result = get_delivery_note("MAT-DN-2025-00200")
import json
data = json.loads(result)
print("Serial numbers found:", data.get('all_serial_numbers', []))
```

#### Check Serial Number Storage
```python
# In bench console
import frappe

# Check if delivery note has items with serial bundles
delivery_note = "MAT-DN-2025-00200"
items = frappe.db.get_all('Delivery Note Item',
    filters={'parent': delivery_note},
    fields=['item_code', 'item_name', 'serial_and_batch_bundle', 'qty'])
print("Items:", items)

# Check serial numbers in a bundle
if items and items[0].get('serial_and_batch_bundle'):
    bundle_id = items[0]['serial_and_batch_bundle']
    serials = frappe.db.get_all('Serial and Batch Entry',
        filters={'parent': bundle_id},
        fields=['serial_no', 'qty'])
    print("Serial numbers:", [s['serial_no'] for s in serials])
```

#### Test Tool Functions Directly
```python
# In bench console
import frappe
from erpnext_chatgpt.erpnext_chatgpt.tools import list_delivery_notes

# Test listing delivery notes with serial number search
result = list_delivery_notes(
    customer="Österreichischer Ski Verband",
    limit=3
)
import json
data = json.loads(result)
print(f"Found {data['total_count']} delivery notes")
```

#### Monitor API Logs
```bash
# On server, view real-time logs
tail -f /path/to/frappe-bench/logs/frappe.log | grep aiassistant

# View error logs
tail -f /path/to/frappe-bench/logs/error.log
```

#### After Code Changes
```bash
# Always run these commands on the server after modifying Python files:
bench restart
bench clear-cache

# If changes don't take effect, try:
bench build
bench migrate
```

## Architecture

This is an ERPNext app that integrates OpenAI capabilities into the ERPNext ERP system. Key architectural components:

### Core Structure
- **Frappe Framework Integration**: Built on top of Frappe/ERPNext framework, using its ORM, API patterns, and whitelisting mechanisms
- **OpenAI Client**: Uses OpenAI Python SDK v1.32.0 for GPT-4 model interactions
- **Tool System**: Implements function calling with 14+ ERPNext-specific tools for data retrieval (sales invoices, employees, stock levels, etc.)
- **Entity Resolution**: The `lookup_entity` tool resolves informal entity names to exact database identifiers before querying documents

### Entity Resolution Pattern

When users mention entities by informal names (e.g., "swissski" for "Swiss Ski Verband"), the AI should:

1. **First** call `lookup_entity(entity_type='customer', search_term='swissski')`
2. Get the exact name from `best_match.id` (e.g., "Swiss Ski Verband")
3. **Then** call the appropriate tool with the exact name (e.g., `list_delivery_notes(customer='Swiss Ski Verband')`)

The `lookup_entity` tool uses:
- **Stage 1**: Frappe's `search_link` for fast, permission-aware candidate generation
- **Stage 2**: Fuzzy re-ranking using `SequenceMatcher` for typo tolerance

Supported entity types: `customer`, `supplier`, `item`, `employee`, `lead`, `contact`

#### Testing Entity Lookup
```python
# In bench console
import frappe
from erpnext_chatgpt.erpnext_chatgpt.tools import lookup_entity
import json

# Test fuzzy customer lookup
result = lookup_entity("customer", "swissski")
data = json.loads(result)
print(f"Best match: {data.get('best_match')}")
print(f"All matches: {data.get('matches')}")
```

### Key Files
- `erpnext_chatgpt/api.py`: Main API endpoints for OpenAI integration
  - Handles conversation management with configurable token limiting
  - Model selection from settings (gpt-3.5-turbo, gpt-4, etc.)
  - Implements tool calling system for ERPNext data queries
  - Manages OpenAI client initialization and API key validation

- `erpnext_chatgpt/tools.py`: Defines available ERPNext functions
  - Each function queries ERPNext database directly via SQL
  - Includes JSON serialization for ERPNext data types
  - Functions mapped to OpenAI tool definitions

- `public/js/frontend.js`: Client-side JavaScript for chat interface
  - Integrates with ERPNext desk environment
  - Manages session creation and conversation state
  - Handles UI for chat dialog

### Frontend Integration
- JavaScript loaded via `hooks.py` configuration
- Chat button injected into ERPNext navbar for System Managers
- Session-based conversation management with localStorage

### Database Interaction
- Direct SQL queries to ERPNext tables (tabSales Invoice, tabEmployee, etc.)
- Uses Frappe's database abstraction layer (`frappe.db.sql`)
- Custom JSON serializer for Decimal, datetime, and timedelta types

### Security Model
- API endpoints whitelisted via `@frappe.whitelist()` decorator
- System Manager role required for access
- API key stored in OpenAI Settings DocType (single document)

## ERPNext App Conventions
- Module structure follows ERPNext patterns (doctype, config, hooks)
- Uses Frappe's logging system for error tracking
- Fixtures defined for OpenAI Settings DocType deployment
- Client-side code uses Frappe's dialog and notification systems

## Adding New Tools

To add new tools for OpenAI function calling, follow these steps:

### 1. Define the Function in `tools.py`

Create a new function that queries ERPNext data. For list commands, include these standard parameters:

```python
def list_your_doctype(
    # Filter parameters
    field1=None,
    field2=None,
    status=None,
    date_from=None,
    date_to=None,

    # Sorting parameters
    sort_by='creation',  # Default sort field
    sort_order='desc',   # 'asc' or 'desc'

    # Pagination
    limit=10,
    offset=0,

    # Special filters (if applicable)
    search_text=None,    # For text search across multiple fields
    item_code=None,      # For filtering by specific items
    serial_number=None   # For serial number tracking
):
    """
    List documents with filtering, sorting, and pagination support.
    """
    filters = {}

    # Build filters dynamically
    if field1:
        filters['field1'] = field1

    # Date range filters
    if date_from and date_to:
        filters['posting_date'] = ['between', [date_from, date_to]]

    # Get data using Frappe's database API
    results = frappe.db.get_all(
        'Your DocType',
        filters=filters,
        fields=['name', 'field1', 'field2', 'amount', 'status'],
        order_by=f'{sort_by} {sort_order}',
        limit=limit,
        start=offset
    )

    # Get total count for pagination
    total_count = frappe.db.count('Your DocType', filters=filters)

    # Calculate summary statistics (optional)
    summary = {}
    if results:
        total_amount = sum(r.get('amount', 0) for r in results)
        summary = {
            'total_records': len(results),
            'total_amount': total_amount,
            'average_amount': total_amount / len(results)
        }

    return json.dumps({
        'data': results,
        'total_count': total_count,
        'limit': limit,
        'offset': offset,
        'summary': summary
    }, default=custom_json_serializer)
```

### 2. Define the Tool Schema

Add a tool definition dictionary following OpenAI's function calling schema:

```python
list_your_doctype_tool = {
    "type": "function",
    "function": {
        "name": "list_your_doctype",
        "description": "List and search documents with advanced filtering, sorting, and pagination",
        "parameters": {
            "type": "object",
            "properties": {
                # Filter properties
                "field1": {
                    "type": "string",
                    "description": "Filter by field1"
                },
                "status": {
                    "type": "string",
                    "enum": ["Draft", "Submitted", "Cancelled"],
                    "description": "Document status"
                },
                "date_from": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)"
                },
                "date_to": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)"
                },

                # Sorting properties
                "sort_by": {
                    "type": "string",
                    "enum": ["creation", "modified", "name", "amount"],
                    "description": "Field to sort by"
                },
                "sort_order": {
                    "type": "string",
                    "enum": ["asc", "desc"],
                    "description": "Sort order"
                },

                # Pagination properties
                "limit": {
                    "type": "integer",
                    "description": "Number of records to return (default: 10, max: 100)"
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of records to skip"
                }
            },
            "required": []  # Usually empty, as all parameters are optional
        }
    }
}
```

### 3. Register the Tool

Add your tool to the exports at the bottom of `tools.py`:

```python
# In the tools list
def get_tools():
    tools = [
        # ... existing tools ...
        list_your_doctype_tool,
    ]
    return tools

# In the available_functions dictionary
available_functions = {
    # ... existing functions ...
    "list_your_doctype": list_your_doctype,
}
```

### Best Practices for Tool Implementation

1. **Consistent Parameters**: Always include standard filter, sort, and pagination parameters for list functions
2. **Error Handling**: Wrap database queries in try-except blocks
3. **Data Serialization**: Use the `custom_json_serializer` for handling ERPNext data types (Decimal, datetime, etc.)
4. **Summary Statistics**: Include helpful aggregations (totals, averages, counts) in list responses
5. **Special Filters**:
   - For serial number searches, query the Serial and Batch Entry table first
   - For text searches, use SQL LIKE queries across relevant fields
   - For item-based filters, join with item tables as needed
6. **Performance**:
   - Set reasonable default limits (10-20 records)
   - Use indexed fields for filtering and sorting
   - Consider using Frappe Query Builder for complex queries
7. **Documentation**: Provide clear descriptions in the tool schema for the AI to understand when and how to use the tool

### Example: Complex Query with Joins

For more complex scenarios involving multiple tables:

```python
def get_invoice_with_items(invoice_name):
    """Get invoice details including all line items."""

    # Get main document
    invoice = frappe.db.get_value(
        'Sales Invoice',
        invoice_name,
        ['*'],
        as_dict=True
    )

    if not invoice:
        return json.dumps({'error': 'Invoice not found'})

    # Get child table items
    items = frappe.db.get_all(
        'Sales Invoice Item',
        filters={'parent': invoice_name},
        fields=['item_code', 'item_name', 'qty', 'rate', 'amount']
    )

    invoice['items'] = items

    return json.dumps(invoice, default=custom_json_serializer)
```

## Creating Documents in ERPNext

When creating new documents (DocTypes) in ERPNext through tools, follow the Frappe API patterns:

### Basic Document Creation Pattern

```python
def create_document(field1, field2, field3=None):
    """Create a new document in ERPNext."""
    try:
        # Prepare document data
        doc_data = {
            'doctype': 'Your DocType Name',
            'field1': field1,
            'field2': field2
        }

        # Add optional fields
        if field3:
            doc_data['field3'] = field3

        # Create the document object
        doc = frappe.get_doc(doc_data)

        # Insert into database
        doc.insert(ignore_permissions=False)

        # Commit the transaction
        frappe.db.commit()

        # Return success with created document details
        return json.dumps({
            'success': True,
            'document_id': doc.name,
            'message': f"Document {doc.name} created successfully"
        }, default=json_serial)

    except frappe.exceptions.ValidationError as e:
        return json.dumps({
            'error': f"Validation error: {str(e)}",
            'success': False
        }, default=json_serial)
    except Exception as e:
        frappe.log_error(f"Error creating document: {str(e)}", "Document Creation Error")
        return json.dumps({
            'error': str(e),
            'success': False
        }, default=json_serial)
```

### Key Points for Document Creation

1. **Use frappe.get_doc()**: Create document instances with `frappe.get_doc(dict)`
2. **Insert Method**: Use `doc.insert()` to save the document to the database
3. **Commit Transaction**: Call `frappe.db.commit()` to ensure the document is persisted
4. **Permissions**: Use `ignore_permissions=False` to respect user permissions
5. **Error Handling**: Catch `frappe.exceptions.ValidationError` for field validation errors
6. **Return Format**: Always return JSON with success status and document details

### Document API Reference

For more details on the Frappe Document API, see: https://docs.frappe.io/framework/user/en/api/document

Key methods for document manipulation:
- `frappe.get_doc()` - Create or get a document
- `doc.insert()` - Insert a new document
- `doc.save()` - Save changes to existing document
- `doc.submit()` - Submit a submittable document
- `doc.cancel()` - Cancel a submitted document
- `doc.delete()` - Delete a document
- `frappe.db.commit()` - Commit database transaction

## Recommended System Instructions

The AI assistant's behavior is controlled by the system instructions configured in OpenAI Settings. To ensure proper entity resolution and accurate queries, include guidance about the `lookup_entity` tool:

### Example System Instructions Template

```
You are an AI assistant for {company}, helping users query and manage ERPNext data.

Current User: {user_name} ({user_email})
Roles: {user_roles}
Date/Time: {current_datetime}

## IMPORTANT: Entity Name Resolution

When users mention customers, suppliers, items, or other entities by informal, abbreviated, or partial names:

1. ALWAYS use lookup_entity() FIRST to find the exact database name
2. Use the `best_match.id` value from the result as the exact identifier
3. THEN use that exact name in subsequent queries

Example workflow:
- User: "Find delivery notes for swissski"
- Step 1: lookup_entity(entity_type="customer", search_term="swissski")
- Result: best_match.id = "Swiss Ski Verband"
- Step 2: list_delivery_notes(customer="Swiss Ski Verband")

This ensures accurate results even when users use nicknames, abbreviations, or misspellings.

## Available Entity Types for Lookup
- customer, supplier, item, employee, lead, contact

## Response Guidelines
- Be concise and professional
- Present data in easy-to-read formats
- Always confirm which entity was matched when using lookup_entity
```

### Placeholders Available
- `{user_name}` - Current user's full name
- `{user_email}` - Current user's email
- `{user_roles}` - Comma-separated list of user roles
- `{company}` - Default company
- `{current_datetime}` - Current date and time