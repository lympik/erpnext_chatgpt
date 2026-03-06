import frappe
import logging
from frappe import _
import json
from typing import List, Dict, Any
from erpnext_chatgpt.erpnext_chatgpt.tools import (
    get_tools, available_functions, is_write_operation,
    get_write_tool_metadata, get_tool_by_name, json_serial
)

# Initialize module-level logger with aiassistant namespace
logger = frappe.logger("aiassistant", allow_site=True)
logger.setLevel(logging.DEBUG)

import re

# Default system prompt for agentic tool-only workflow
# Note: Tool definitions are passed separately via the tools parameter.
# This prompt focuses on workflow guidance, decision boundaries, and behavior.
DEFAULT_SYSTEM_PROMPT = """You are an AI agent for {company}, helping {user_full_name} with ERP queries.

Context:
- Date/Time: {current_datetime}
- User: {user_full_name} ({current_user})

## CRITICAL: Tool-Only Mode

You MUST use tools for everything. You cannot respond directly.
Call `final_answer` to deliver your response to the user.

## Workflow

### Step 1: Entity Resolution (REQUIRED for informal names)
When users mention customers, suppliers, items, or other entities by informal/partial names:
- ALWAYS call `lookup_entity(entity_type, search_term)` first
- Use `best_match.id` in subsequent queries
- Example: "swissski" → lookup_entity("customer", "swissski") → "Swiss-Ski"

### Step 2: Query Data
Use resolved entity names in document queries.

### Step 3: Drill Down (if needed)
For details like serial numbers or line items, fetch the specific document.

### Step 4: Respond
Call `final_answer(message="...")` with formatted markdown.

## Tool Selection Guidelines

**Customer insights:** Use `get_customer_summary` for a full 360° view (sales, invoices, contacts, history) rather than multiple separate queries.

**Analytics:** Use `aggregate_data` for totals, comparisons, and groupings instead of fetching raw data and calculating manually.

**Lists vs Details:** Start with list tools (e.g., `list_delivery_notes`), then drill into specific documents only when needed.

**Multi-source queries:** For questions spanning multiple data types (e.g., "customers with overdue invoices AND recent deliveries"), query each source separately, then correlate in your response.

## Error Handling

- **No entity match:** Try search variations, or ask for clarification via `final_answer`
- **Empty results:** Explain filters used, suggest alternatives (broader date range, different status)
- **Too many results:** Add filters or summarize, offer to drill down

## Efficiency

You have limited iterations. Be strategic:
- Don't re-query data you already have
- Use summary tools over multiple granular queries
- Plan before calling - avoid unnecessary tool calls

## Response Formatting (for final_answer)

**Links:** `[MAT-DN-2025-00123](/app/delivery-note/MAT-DN-2025-00123)`
- Doctype URL: lowercase, hyphens for spaces
- URL-encode special characters

**Data:** Use markdown tables. Show summaries first, then details.

**Currency:** €1,234.56 or CHF 1'234.56

**Confirmation:** Always confirm matched entities: "Found customer 'Swiss-Ski' for 'swissski'"

## Rules

- NEVER skip entity lookup for informal names
- NEVER respond without calling `final_answer`
- If ambiguous, ask clarifying questions via `final_answer`
"""


def auto_link_document_ids(text):
    """
    Automatically convert ERPNext document IDs to clickable markdown links.
    Detects patterns like MAT-DN-2026-00006, SI-2024-00001, etc.
    """
    # Map document prefixes to their URL doctypes
    doctype_mappings = {
        # Delivery Note patterns
        'MAT-DN': 'delivery-note',
        'DN': 'delivery-note',
        # Sales Invoice patterns
        'SI': 'sales-invoice',
        'SINV': 'sales-invoice',
        'ACC-SINV': 'sales-invoice',
        # Sales Order patterns
        'SO': 'sales-order',
        'SAL-ORD': 'sales-order',
        # Purchase Order patterns
        'PO': 'purchase-order',
        'PUR-ORD': 'purchase-order',
        # Purchase Invoice patterns
        'PI': 'purchase-invoice',
        'PINV': 'purchase-invoice',
        'ACC-PINV': 'purchase-invoice',
        # Quotation patterns
        'QTN': 'quotation',
        'SAL-QTN': 'quotation',
        # Customer patterns (usually just names, handled separately)
        # Supplier patterns
        'SUP': 'supplier',
        # Item patterns
        'ITEM': 'item',
        # Employee patterns
        'HR-EMP': 'employee',
        'EMP': 'employee',
        # Lead patterns
        'CRM-LEAD': 'lead',
        'LEAD': 'lead',
        # Service Protocol (custom)
        'SVP': 'service-protocol',
        # Stock Entry
        'MAT-STE': 'stock-entry',
        'STE': 'stock-entry',
        # Material Request
        'MAT-MR': 'material-request',
        # Payment Entry
        'ACC-PAY': 'payment-entry',
        'PE': 'payment-entry',
        # Journal Entry
        'ACC-JV': 'journal-entry',
        'JV': 'journal-entry',
    }

    # Build regex pattern for all prefixes
    # Sort by length (longest first) to match longer prefixes before shorter ones
    sorted_prefixes = sorted(doctype_mappings.keys(), key=len, reverse=True)
    prefix_pattern = '|'.join(re.escape(p) for p in sorted_prefixes)

    # Pattern matches: PREFIX-YEAR-NUMBER or PREFIX-NUMBER
    # Examples: MAT-DN-2026-00006, SI-2024-00001, SVP-2025-0001
    pattern = rf'\b(({prefix_pattern})-(\d{{4}})-(\d{{4,6}})|({prefix_pattern})-(\d{{4,6}}))\b'

    def replace_match(match):
        doc_id = match.group(0)

        # Check if already inside a markdown link [...](...)
        # by looking at surrounding context
        start = match.start()
        prefix_text = text[max(0, start-2):start]
        if prefix_text.endswith('](') or prefix_text.endswith('['):
            return doc_id  # Already in a link, don't modify

        # Find which prefix matches
        for prefix, doctype_url in doctype_mappings.items():
            if doc_id.startswith(prefix + '-'):
                return f'[{doc_id}](/app/{doctype_url}/{doc_id})'

        return doc_id  # No match found, return as-is

    # Apply regex replacement
    result = re.sub(pattern, replace_match, text)

    return result


def get_system_instructions():
    """Get system instructions with current date and user context."""
    current_user = frappe.session.user
    user_full_name = frappe.get_value("User", current_user, "full_name") or current_user
    user_roles = frappe.get_roles(current_user)
    company = frappe.defaults.get_user_default("company") or frappe.defaults.get_global_default("company")
    current_datetime = frappe.utils.now()

    # Get custom system instructions from settings
    custom_instructions = frappe.db.get_single_value("OpenAI Settings", "system_instructions")

    # If no custom instructions are set, use the default agentic prompt
    if not custom_instructions or custom_instructions.strip() == "":
        custom_instructions = DEFAULT_SYSTEM_PROMPT

    # Build placeholder values - support multiple naming conventions
    placeholder_values = {
        # User info - multiple naming conventions
        'user_name': user_full_name,
        'user_full_name': user_full_name,
        'user_email': current_user,
        'current_user': current_user,
        'user_roles': ', '.join(user_roles) if user_roles else 'No roles assigned',

        # Company
        'company': company if company else 'ERPNext',

        # Date/time - multiple naming conventions
        'current_datetime': current_datetime,
        'current_date': frappe.utils.today(),
        'current_time': frappe.utils.nowtime(),
        'now': current_datetime,
        'today': frappe.utils.today(),
    }

    # Replace placeholders with actual values
    try:
        system_instructions = custom_instructions.format(**placeholder_values)
    except KeyError as e:
        # Handle case where placeholder is used incorrectly
        logger.warning(f"Invalid placeholder in system instructions: {e}")
        # Return instructions without replacement if there's an error
        system_instructions = custom_instructions

    return system_instructions

def get_model_settings():
    """Get model and max_tokens from settings."""
    model = frappe.db.get_single_value("OpenAI Settings", "model")
    max_tokens = frappe.db.get_single_value("OpenAI Settings", "max_tokens")

    # Use defaults if not set
    if not model:
        model = "gpt-4o-mini"
    if not max_tokens:
        max_tokens = 8000

    return model, max_tokens

def get_openai_client():
    """Get the OpenAI client with the API key from settings."""
    api_key = frappe.db.get_single_value("OpenAI Settings", "api_key")
    if not api_key:
        frappe.throw(_("OpenAI API key is not set in OpenAI Settings."))

    # Import OpenAI
    from openai import OpenAI

    # Simple initialization - OpenAI SDK v1.x only needs api_key
    # Don't pass any proxy-related parameters
    return OpenAI(api_key=api_key)

def extract_fetched_entities(function_name, response_data):
    """
    Extract document/entity references from tool results for quick access chips.
    Returns a list of {id, doctype, label} objects.
    """
    entities = []

    if not response_data or not isinstance(response_data, dict):
        return entities

    # Map function names to their result keys and doctypes
    function_mappings = {
        'lookup_entity': {
            'key': 'best_match',
            'doctype_field': 'doctype',
            'id_field': 'id',
            'label_field': 'name'
        },
        'list_delivery_notes': {
            'key': 'delivery_notes',
            'doctype': 'Delivery Note',
            'id_field': 'name',
            'label_field': 'name'
        },
        'get_delivery_note': {
            'key': None,  # Root level
            'doctype': 'Delivery Note',
            'id_field': 'name',
            'label_field': 'name'
        },
        'list_invoices': {
            'key': 'invoices',
            'doctype': 'Sales Invoice',
            'id_field': 'name',
            'label_field': 'name'
        },
        'get_sales_invoice': {
            'key': None,
            'doctype': 'Sales Invoice',
            'id_field': 'name',
            'label_field': 'name'
        },
        'get_sales_invoices': {
            'key': None,  # Returns list at root
            'doctype': 'Sales Invoice',
            'id_field': 'name',
            'label_field': 'name',
            'is_list': True
        },
        'list_sales_orders': {
            'key': 'sales_orders',
            'doctype': 'Sales Order',
            'id_field': 'name',
            'label_field': 'name'
        },
        'list_quotations': {
            'key': 'quotations',
            'doctype': 'Quotation',
            'id_field': 'name',
            'label_field': 'name'
        },
        'list_customers': {
            'key': 'customers',
            'doctype': 'Customer',
            'id_field': 'name',
            'label_field': 'customer_name'
        },
        'get_customers': {
            'key': None,
            'doctype': 'Customer',
            'id_field': 'name',
            'label_field': 'customer_name',
            'is_list': True
        },
        'get_purchase_orders': {
            'key': None,
            'doctype': 'Purchase Order',
            'id_field': 'name',
            'label_field': 'name',
            'is_list': True
        },
        'get_purchase_invoices': {
            'key': None,
            'doctype': 'Purchase Invoice',
            'id_field': 'name',
            'label_field': 'name',
            'is_list': True
        },
        'list_service_protocols': {
            'key': 'service_protocols',
            'doctype': 'Service Protocol',
            'id_field': 'name',
            'label_field': 'name'
        },
        'get_service_protocol': {
            'key': None,
            'doctype': 'Service Protocol',
            'id_field': 'name',
            'label_field': 'name'
        },
        'get_employees': {
            'key': None,
            'doctype': 'Employee',
            'id_field': 'name',
            'label_field': 'employee_name',
            'is_list': True
        },
        'get_outstanding_invoices': {
            'key': None,
            'doctype': 'Sales Invoice',
            'id_field': 'name',
            'label_field': 'name',
            'is_list': True
        },
    }

    mapping = function_mappings.get(function_name)
    if not mapping:
        return entities

    try:
        # Handle lookup_entity specially - it has dynamic doctype
        if function_name == 'lookup_entity':
            best_match = response_data.get('best_match')
            doctype = response_data.get('doctype', 'Unknown')
            if best_match and best_match.get('id'):
                entities.append({
                    'id': best_match.get('id'),
                    'doctype': doctype,
                    'label': best_match.get('name') or best_match.get('id')
                })
            return entities

        # Get the data to process
        data_key = mapping.get('key')
        if data_key:
            data = response_data.get(data_key, [])
        else:
            data = response_data

        # Ensure data is a list
        if not isinstance(data, list):
            data = [data] if data else []

        # Extract entities (limit to first 10 for UI)
        doctype = mapping.get('doctype', 'Unknown')
        id_field = mapping.get('id_field', 'name')
        label_field = mapping.get('label_field', 'name')

        for item in data[:10]:
            if isinstance(item, dict) and item.get(id_field):
                entities.append({
                    'id': item.get(id_field),
                    'doctype': doctype,
                    'label': item.get(label_field) or item.get(id_field)
                })

    except Exception as e:
        logger.warning(f"Error extracting entities from {function_name}: {e}")

    return entities


def handle_tool_calls(tool_calls: List[Any], conversation: List[Dict[str, Any]], tool_usage_log: List[Dict[str, Any]], session_doc=None) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Handle the tool calls by executing the corresponding functions and appending the results to the conversation.
    Also track tool usage for transparency.
    For write operations, returns a pending_confirmation response for user approval.

    :param tool_calls: List of tool calls from OpenAI
    :param conversation: Current conversation history
    :param tool_usage_log: List to track tool usage
    :param session_doc: Optional session document for storing pending confirmations
    :return: Tuple of (updated conversation, tool usage log, pending_confirmation or None)
    """
    for tool_call in tool_calls:
        function_name = tool_call.function.name
        function_to_call = available_functions.get(function_name)
        if not function_to_call:
            frappe.log_error(f"Function {function_name} not found.", "OpenAI Tool Error")
            raise ValueError(f"Function {function_name} not found.")

        function_args = json.loads(tool_call.function.arguments)

        # Check if this is a write operation that requires user confirmation
        if is_write_operation(function_name):
            write_metadata = get_write_tool_metadata(function_name)
            logger.debug(f"Write operation detected: {function_name}, requiring confirmation")

            # Build pending confirmation data
            pending_confirmation = {
                'tool_call_id': tool_call.id,
                'tool_name': function_name,
                'parameters': function_args,
                'confirmation_message': write_metadata.get('confirmation_message', f'Execute {function_name}'),
                'conversation_state': conversation.copy(),
                'tool_usage_log': tool_usage_log.copy(),
                'created_at': frappe.utils.now()
            }

            # Save pending confirmation to session document if provided
            if session_doc:
                session_doc.pending_confirmation = json.dumps(pending_confirmation, default=json_serial)
                session_doc.save(ignore_permissions=False)
                frappe.db.commit()
                logger.debug(f"Saved pending confirmation to session {session_doc.name}")

            # Return early with pending confirmation
            return conversation, tool_usage_log, pending_confirmation

        # Log the tool usage
        tool_usage_entry = {
            "tool_name": function_name,
            "parameters": function_args,
            "timestamp": frappe.utils.now()
        }

        try:
            function_response = function_to_call(**function_args)

            # Initialize response_data for entity extraction
            response_data = {}

            # Parse response to get summary info if it's JSON
            try:
                response_data = json.loads(function_response)
                if isinstance(response_data, dict):
                    # Add summary info for better display
                    # Check for paginated results with limit
                    limit = response_data.get('limit')
                    total_count = response_data.get('total_count')

                    # Handle different response types
                    if 'delivery_notes' in response_data:
                        actual_count = len(response_data['delivery_notes'])
                        if limit and total_count and total_count > actual_count:
                            tool_usage_entry['result_summary'] = f"Retrieved {actual_count} of {total_count} delivery notes (limited)"
                        else:
                            tool_usage_entry['result_summary'] = f"Retrieved {actual_count} delivery notes"
                    elif 'invoices' in response_data:
                        actual_count = len(response_data['invoices'])
                        if limit and total_count and total_count > actual_count:
                            tool_usage_entry['result_summary'] = f"Retrieved {actual_count} of {total_count} invoices (limited)"
                        else:
                            tool_usage_entry['result_summary'] = f"Retrieved {actual_count} invoices"
                    elif 'sales_orders' in response_data:
                        actual_count = len(response_data['sales_orders'])
                        if limit and total_count and total_count > actual_count:
                            tool_usage_entry['result_summary'] = f"Retrieved {actual_count} of {total_count} sales orders (limited)"
                        else:
                            tool_usage_entry['result_summary'] = f"Retrieved {actual_count} sales orders"
                    elif 'quotations' in response_data:
                        actual_count = len(response_data['quotations'])
                        if limit and total_count and total_count > actual_count:
                            tool_usage_entry['result_summary'] = f"Retrieved {actual_count} of {total_count} quotations (limited)"
                        else:
                            tool_usage_entry['result_summary'] = f"Retrieved {actual_count} quotations"
                    elif 'customers' in response_data:
                        actual_count = len(response_data['customers'])
                        if limit and total_count and total_count > actual_count:
                            tool_usage_entry['result_summary'] = f"Retrieved {actual_count} of {total_count} customers (limited)"
                        else:
                            tool_usage_entry['result_summary'] = f"Retrieved {actual_count} customers"
                    elif 'total_count' in response_data:
                        # Generic fallback for other paginated responses
                        tool_usage_entry['result_summary'] = f"Found {total_count} records"
                    elif isinstance(response_data, list):
                        tool_usage_entry['result_summary'] = f"Retrieved {len(response_data)} items"
                    else:
                        tool_usage_entry['result_summary'] = "Data retrieved successfully"
                else:
                    tool_usage_entry['result_summary'] = "Data retrieved"
            except:
                tool_usage_entry['result_summary'] = "Query executed"

            tool_usage_entry['status'] = 'success'

            # Extract fetched entities for quick access chips
            tool_usage_entry['fetched_entities'] = extract_fetched_entities(function_name, response_data if isinstance(response_data, dict) else {})

        except Exception as e:
            # Keep title short (max 140 chars) to avoid secondary CharacterLengthExceededError
            error_title = f"Tool Error: {function_name}"[:140]
            error_message = f"Function: {function_name}\nArgs: {json.dumps(function_args)}\nError: {str(e)}"
            frappe.log_error(message=error_message, title=error_title)
            tool_usage_entry['status'] = 'error'
            tool_usage_entry['error'] = str(e)
            raise

        tool_usage_log.append(tool_usage_entry)

        conversation.append({
            "tool_call_id": tool_call.id,
            "role": "tool",
            "name": function_name,
            "content": str(function_response),
        })
    return conversation, tool_usage_log, None  # No pending confirmation for read operations

def estimate_token_count(messages: List[Dict[str, Any]]) -> int:
    """
    Estimate the token count for a list of messages.
    This is a rough estimation; OpenAI provides more accurate token counting in their own libraries.
    """
    tokens_per_message = 4  # Average tokens per message (considering metadata)
    tokens_per_word = 1.5   # Average tokens per word (this may vary)

    return sum(tokens_per_message + int(len(str(message.get("content", "")).split()) * tokens_per_word)
               for message in messages if message.get("content") is not None)

def extract_messages_for_storage(conversation: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extract only user messages and assistant final responses for storage.
    Skips system messages, tool calls, and tool responses to save space.
    """
    messages_to_save = []
    for m in conversation:
        role = m.get("role")
        if role == "user":
            messages_to_save.append({"role": "user", "content": m.get("content", "")})
        elif role == "assistant" and m.get("content") and not m.get("tool_calls"):
            # Only save assistant messages that have content (final answers)
            # Skip assistant messages that are just tool_calls
            messages_to_save.append({
                "role": "assistant",
                "content": m.get("content", ""),
                "content_display": m.get("content_display"),
                "tool_usage": m.get("tool_usage")
            })
    return messages_to_save


def trim_conversation_to_token_limit(conversation: List[Dict[str, Any]], token_limit: int = None) -> List[Dict[str, Any]]:
    """
    Trim the conversation so that its total token count does not exceed the specified limit.
    Keeps the most recent messages and trims older ones.
    """
    if token_limit is None:
        _, token_limit = get_model_settings()
    while estimate_token_count(conversation) > token_limit and len(conversation) > 1:
        # Remove the oldest non-system message
        for i, message in enumerate(conversation):
            if message.get("role") != "system":
                del conversation[i]
                break
    return conversation

@frappe.whitelist()
def ask_openai_question(session_id: str, message: str) -> Dict[str, Any]:
    """
    Ask a question to the OpenAI model and handle the response.
    Track all tool usage for transparency.

    :param session_id: The conversation session ID
    :param message: The user's new message
    :return: The response from OpenAI with tool usage information.
    """
    try:
        if not session_id or not message:
            return {"error": "session_id and message are required", "tool_usage": []}

        client = get_openai_client()
        tool_usage_log = []

        # Load conversation from database
        try:
            session_doc = frappe.get_doc("AI Conversation", session_id)

            # Check permission using owner field
            if session_doc.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
                frappe.throw("You don't have permission to access this conversation")

            # Load existing messages
            conversation = json.loads(session_doc.messages) if session_doc.messages else []

            # Add the new user message
            conversation.append({"role": "user", "content": message})

            # Auto-generate title from first user message if title is still default
            if session_doc.title == "New Conversation" and message:
                session_doc.title = message[:50] + "..." if len(message) > 50 else message

        except frappe.DoesNotExistError:
            return {"error": "Conversation session not found", "tool_usage": []}

        # Add system instructions as the initial message if not present
        if not conversation or conversation[0].get("role") != "system":
            conversation.insert(0, {"role": "system", "content": get_system_instructions()})

        # Get model settings
        model, max_tokens = get_model_settings()

        # Trim conversation to stay within the token limit
        conversation = trim_conversation_to_token_limit(conversation, max_tokens)

        logger.debug(f"Conversation: {json.dumps(conversation)}")

        tools = get_tools()

        # Agentic tool-only loop
        # Force the AI to use tools until it calls final_answer
        max_iterations = 15  # Safety limit to prevent infinite loops
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # Use tool_choice="required" to force tool usage
            # The AI MUST call a tool - it cannot respond with just text
            response = client.chat.completions.create(
                model=model,
                messages=conversation,
                tools=tools,
                tool_choice="required"
            )

            response_message = response.choices[0].message
            logger.debug(f"OpenAI Response (iteration {iteration}): {response_message}")

            tool_calls = response_message.tool_calls
            if not tool_calls:
                # This shouldn't happen with tool_choice="required", but handle it
                logger.warning("No tool calls returned despite tool_choice=required")
                response_data = response_message.model_dump()
                response_data['tool_usage'] = tool_usage_log
                return response_data

            # Check if any tool call is final_answer
            for tool_call in tool_calls:
                if tool_call.function.name == "final_answer":
                    # Extract the final answer and return it
                    try:
                        final_args = json.loads(tool_call.function.arguments)
                        logger.debug(f"Final answer received after {iteration} iterations")

                        # Auto-link document IDs in the response
                        message = final_args.get("message", "")
                        message = auto_link_document_ids(message)

                        # Build context summary for conversation continuity
                        # This gets embedded in the message so the model remembers what was searched
                        context_parts = []
                        for tool_entry in tool_usage_log:
                            tool_name = tool_entry.get("tool_name", "")
                            params = tool_entry.get("parameters", {})
                            if params and tool_name != "final_answer":
                                param_str = ", ".join(f"{k}={v}" for k, v in params.items() if v is not None)
                                context_parts.append(f"{tool_name}({param_str})")

                        # Append context as hidden metadata for future turns
                        if context_parts:
                            context_note = "\n\n<!-- CONTEXT: " + " | ".join(context_parts) + " -->"
                            message_with_context = message + context_note
                        else:
                            message_with_context = message

                        # Add assistant response to conversation
                        assistant_message = {
                            "role": "assistant",
                            "content": message_with_context,
                            "content_display": message,
                            "tool_usage": tool_usage_log
                        }
                        conversation.append(assistant_message)

                        # Save conversation to database if in session mode
                        if session_doc:
                            # Only save user messages and assistant final responses
                            # Skip system messages, tool calls, and tool responses to save space
                            messages_to_save = extract_messages_for_storage(conversation)
                            session_doc.messages = json.dumps(messages_to_save)
                            session_doc.model_used = model
                            session_doc.save(ignore_permissions=False)
                            frappe.db.commit()

                        # Return the final answer in the expected format
                        return {
                            "role": "assistant",
                            "content": message_with_context,
                            "content_display": message,  # Clean version for UI
                            "tool_usage": tool_usage_log,
                            "summary": final_args.get("summary"),
                            "iterations": iteration,
                            "session_id": session_doc.name if session_doc else None
                        }
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse final_answer arguments: {e}")
                        return {
                            "role": "assistant",
                            "content": "I encountered an error formatting my response.",
                            "tool_usage": tool_usage_log,
                            "error": str(e),
                            "session_id": session_doc.name if session_doc else None
                        }

            # No final_answer yet - handle the tool calls and continue
            conversation.append(response_message.model_dump())
            conversation, tool_usage_log, pending_confirmation = handle_tool_calls(
                tool_calls, conversation, tool_usage_log, session_doc
            )

            # Check if there's a pending write operation confirmation
            if pending_confirmation:
                logger.debug(f"Returning pending confirmation for {pending_confirmation['tool_name']}")
                return {
                    "status": "pending_confirmation",
                    "pending_confirmation": pending_confirmation,
                    "tool_usage": tool_usage_log,
                    "session_id": session_doc.name if session_doc else None
                }

            # Trim conversation if needed
            conversation = trim_conversation_to_token_limit(conversation, max_tokens)

            logger.debug(f"Handled {len(tool_calls)} tool calls, continuing to iteration {iteration + 1}")

        # If we hit max iterations, force a response
        logger.warning(f"Hit max iterations ({max_iterations}) without final_answer")

        # Save conversation state even on max iterations
        error_message = "I was unable to complete the request within the allowed number of steps. Please try a simpler query."
        conversation.append({
            "role": "assistant",
            "content": error_message,
            "tool_usage": tool_usage_log
        })

        if session_doc:
            messages_to_save = extract_messages_for_storage(conversation)
            session_doc.messages = json.dumps(messages_to_save)
            session_doc.model_used = model
            session_doc.save(ignore_permissions=False)
            frappe.db.commit()

        return {
            "role": "assistant",
            "content": error_message,
            "tool_usage": tool_usage_log,
            "error": "max_iterations_reached",
            "session_id": session_doc.name if session_doc else None
        }
    except Exception as e:
        frappe.log_error(message=str(e), title="OpenAI API Error")
        return {"error": str(e), "tool_usage": [], "session_id": session_id if session_id else None}

@frappe.whitelist()
def test_openai_api_key(api_key: str) -> bool:
    """
    Test if the provided OpenAI API key is valid.

    :param api_key: The OpenAI API key to test.
    :return: True if the API key is valid, False otherwise.
    """
    try:
        # Import OpenAI
        from openai import OpenAI

        # Simple client creation with just the API key
        # httpx==0.27.2 handles proxies correctly
        client = OpenAI(api_key=api_key)
        # Test the key by listing models
        list(client.models.list())
        return True
    except Exception as e:
        frappe.log_error(str(e), "OpenAI API Key Test Failed")
        return False

@frappe.whitelist()
def get_available_models() -> List[str]:
    """
    Get list of available OpenAI models for the current API key.

    :return: List of model IDs that can be used for chat completions
    """
    try:
        client = get_openai_client()
        models = list(client.models.list())

        # Filter for chat models
        chat_models = []
        for model in models:
            if any(prefix in model.id for prefix in ["gpt-3.5", "gpt-4", "gpt-5"]):
                chat_models.append(model.id)

        # Sort models for better display
        chat_models.sort()
        return chat_models
    except Exception as e:
        frappe.log_error(str(e), "Failed to fetch available models")
        # Return default models if API call fails
        return ["gpt-4o-mini", "gpt-4o", "gpt-4.1", "gpt-4.1-mini", "gpt-5-mini", "gpt-5.1", "gpt-5.2", "gpt-3.5-turbo", "gpt-4", "gpt-4-turbo"]

@frappe.whitelist()
def test_connection() -> Dict[str, Any]:
    """
    Test the OpenAI connection by initializing the client and making a simple API call.

    :return: Dictionary with success status and message.
    """
    try:
        # Get the API key from settings
        api_key = frappe.db.get_single_value("OpenAI Settings", "api_key")
        if not api_key:
            return {"success": False, "message": _("OpenAI API key is not set. Please enter an API key first.")}

        # Import OpenAI
        from openai import OpenAI

        # Simple initialization with just API key
        # httpx==0.27.2 handles proxies correctly
        client = OpenAI(api_key=api_key)

        # Test the connection by listing models
        models = list(client.models.list())

        if models:
            return {"success": True, "message": _("Connection successful! OpenAI API is working correctly.")}
        else:
            return {"success": False, "message": _("Connection established but no models available.")}

    except Exception as e:
        frappe.log_error(str(e), "OpenAI Connection Test Failed")

        # Provide specific error messages
        if "api" in str(e).lower() and "key" in str(e).lower():
            return {"success": False, "message": _("Invalid API key. Please check your OpenAI API key.")}
        else:
            return {"success": False, "message": _("Connection failed: {0}").format(str(e))}

@frappe.whitelist()
def check_openai_key_and_role() -> Dict[str, Any]:
    """
    Always show the chat button for all users.

    :return: Dictionary indicating to always show the button.
    """
    return {"show_button": True}


# =============================================================================
# Conversation Management API Endpoints
# =============================================================================

@frappe.whitelist()
def create_conversation(title: str = None) -> Dict[str, Any]:
    """
    Create a new AI conversation session.

    :param title: Optional title for the conversation
    :return: Dictionary with session_id and conversation details
    """
    try:
        model, _ = get_model_settings()

        doc = frappe.get_doc({
            "doctype": "AI Conversation",
            "title": title or "New Conversation",
            "status": "Active",
            "messages": json.dumps([]),
            "message_count": 0,
            "model_used": model
        })
        doc.insert(ignore_permissions=False)
        frappe.db.commit()

        return {
            "success": True,
            "session_id": doc.name,
            "title": doc.title,
            "created_at": str(doc.creation),
            "model_used": doc.model_used
        }
    except Exception as e:
        frappe.log_error(message=str(e), title="Create Conversation Error")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def list_conversations(status: str = "Active", limit: int = 20, offset: int = 0) -> Dict[str, Any]:
    """
    List user's AI conversations.

    :param status: Filter by status (Active, Archived, or None for all)
    :param limit: Number of conversations to return
    :param offset: Number of conversations to skip
    :return: Dictionary with conversations list and pagination info
    """
    try:
        # Ensure limit and offset are integers
        limit = int(limit) if limit else 20
        offset = int(offset) if offset else 0

        filters = {"owner": frappe.session.user}
        if status:
            filters["status"] = status

        # Order by modified (always set) instead of last_message_at (can be NULL)
        conversations = frappe.db.get_all(
            "AI Conversation",
            filters=filters,
            fields=["name", "title", "status", "message_count", "last_message_at", "model_used", "creation", "modified"],
            order_by="modified desc",
            limit_page_length=limit,
            limit_start=offset
        )

        total_count = frappe.db.count("AI Conversation", filters=filters)

        return {
            "success": True,
            "conversations": conversations,
            "total_count": total_count,
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        frappe.log_error(message=str(e), title="List Conversations Error")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_conversation(session_id: str) -> Dict[str, Any]:
    """
    Get full conversation history by session ID.

    :param session_id: The conversation session ID
    :return: Dictionary with conversation details and messages
    """
    try:
        doc = frappe.get_doc("AI Conversation", session_id)

        # Check permission using owner field (set automatically by Frappe)
        if doc.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
            frappe.throw("You don't have permission to access this conversation")

        raw_messages = json.loads(doc.messages) if doc.messages else []

        # Filter to only return user and assistant messages (no tool responses)
        messages = extract_messages_for_storage(raw_messages)

        return {
            "success": True,
            "session_id": doc.name,
            "title": doc.title,
            "status": doc.status,
            "messages": messages,
            "message_count": doc.message_count,
            "last_message_at": str(doc.last_message_at) if doc.last_message_at else None,
            "model_used": doc.model_used,
            "created_at": str(doc.creation)
        }
    except frappe.DoesNotExistError:
        return {"success": False, "error": "Conversation not found"}
    except Exception as e:
        frappe.log_error(message=str(e), title="Get Conversation Error")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def update_conversation_title(session_id: str, title: str) -> Dict[str, Any]:
    """
    Update the title of a conversation.

    :param session_id: The conversation session ID
    :param title: New title for the conversation
    :return: Dictionary with success status
    """
    try:
        doc = frappe.get_doc("AI Conversation", session_id)

        # Check permission using owner field
        if doc.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
            frappe.throw("You don't have permission to modify this conversation")

        doc.title = title
        doc.save(ignore_permissions=False)
        frappe.db.commit()

        return {"success": True, "session_id": session_id, "title": title}
    except frappe.DoesNotExistError:
        return {"success": False, "error": "Conversation not found"}
    except Exception as e:
        frappe.log_error(message=str(e), title="Update Conversation Title Error")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def archive_conversation(session_id: str) -> Dict[str, Any]:
    """
    Archive a conversation.

    :param session_id: The conversation session ID
    :return: Dictionary with success status
    """
    try:
        doc = frappe.get_doc("AI Conversation", session_id)

        # Check permission using owner field
        if doc.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
            frappe.throw("You don't have permission to modify this conversation")

        doc.status = "Archived"
        doc.save(ignore_permissions=False)
        frappe.db.commit()

        return {"success": True, "session_id": session_id, "status": "Archived"}
    except frappe.DoesNotExistError:
        return {"success": False, "error": "Conversation not found"}
    except Exception as e:
        frappe.log_error(message=str(e), title="Archive Conversation Error")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def delete_conversation(session_id: str) -> Dict[str, Any]:
    """
    Delete a conversation (System Manager only, or own conversation).

    :param session_id: The conversation session ID
    :return: Dictionary with success status
    """
    try:
        doc = frappe.get_doc("AI Conversation", session_id)

        # Check permission using owner field - only System Manager can delete others' conversations
        if doc.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
            frappe.throw("You don't have permission to delete this conversation")

        doc.delete(ignore_permissions=False)
        frappe.db.commit()

        return {"success": True, "session_id": session_id, "deleted": True}
    except frappe.DoesNotExistError:
        return {"success": False, "error": "Conversation not found"}
    except Exception as e:
        frappe.log_error(message=str(e), title="Delete Conversation Error")
        return {"success": False, "error": str(e)}


# =============================================================================
# Write Operation Confirmation API
# =============================================================================

@frappe.whitelist()
def confirm_write_operation(session_id: str, action: str, user_message: str = None) -> Dict[str, Any]:
    """
    Handle user's confirmation choice for a pending write operation.

    :param session_id: The conversation session ID
    :param action: One of "accept", "change", or "deny"
    :param user_message: If action is "change", the user's feedback for what to change
    :return: Dictionary with result or continued conversation response
    """
    try:
        if not session_id:
            return {"error": "session_id is required", "tool_usage": []}

        if action not in ["accept", "change", "deny"]:
            return {"error": f"Invalid action: {action}. Must be 'accept', 'change', or 'deny'", "tool_usage": []}

        # Load session
        session_doc = frappe.get_doc("AI Conversation", session_id)

        # Check permission
        if session_doc.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
            frappe.throw("You don't have permission to access this conversation")

        # Get pending confirmation
        if not session_doc.pending_confirmation:
            return {"error": "No pending confirmation found for this session", "tool_usage": []}

        pending = json.loads(session_doc.pending_confirmation)
        tool_name = pending.get('tool_name')
        tool_args = pending.get('parameters', {})
        conversation = pending.get('conversation_state', [])
        tool_usage_log = pending.get('tool_usage_log', [])
        tool_call_id = pending.get('tool_call_id')

        logger.debug(f"Processing confirmation action '{action}' for tool '{tool_name}'")

        # Clear pending confirmation
        session_doc.pending_confirmation = None

        if action == "accept":
            # Execute the write operation
            function_to_call = available_functions.get(tool_name)
            if not function_to_call:
                return {"error": f"Function {tool_name} not found", "tool_usage": tool_usage_log}

            try:
                function_response = function_to_call(**tool_args)

                # Parse response
                try:
                    response_data = json.loads(function_response)
                except:
                    response_data = {}

                # Extract created entity info for frontend display
                created_entity = _extract_created_entity(tool_name, response_data)

                # Log the tool usage
                tool_usage_entry = {
                    "tool_name": tool_name,
                    "parameters": tool_args,
                    "timestamp": frappe.utils.now(),
                    "status": "success",
                    "result_summary": f"Executed {tool_name} successfully",
                    "user_confirmed": True
                }
                tool_usage_log.append(tool_usage_entry)

                # Add tool response to conversation
                conversation.append({
                    "tool_call_id": tool_call_id,
                    "role": "tool",
                    "name": tool_name,
                    "content": str(function_response),
                })

                # Save session and continue agentic loop
                session_doc.save(ignore_permissions=False)
                frappe.db.commit()

                # Continue the agentic loop from where we left off
                result = _continue_agentic_loop(session_doc, conversation, tool_usage_log)

                # Add created entity info to the response for frontend display
                if created_entity:
                    result['created_entity'] = created_entity

                return result

            except Exception as e:
                logger.error(f"Error executing {tool_name}: {str(e)}")
                frappe.log_error(f"Error executing {tool_name}: {str(e)}", "Write Operation Error")
                return {
                    "error": f"Failed to execute {tool_name}: {str(e)}",
                    "tool_usage": tool_usage_log,
                    "session_id": session_id
                }

        elif action == "change":
            # User wants to modify the parameters
            if not user_message:
                return {"error": "user_message is required for 'change' action", "tool_usage": tool_usage_log}

            # Add a user message with the change request to the conversation
            change_message = f"Please change the following before proceeding: {user_message}"
            conversation.append({"role": "user", "content": change_message})

            # Add a note to the tool response indicating it was rejected for changes
            conversation.append({
                "tool_call_id": tool_call_id,
                "role": "tool",
                "name": tool_name,
                "content": json.dumps({
                    "status": "rejected_for_changes",
                    "user_feedback": user_message,
                    "message": f"User requested changes before executing {tool_name}. Please revise the parameters based on their feedback and try again."
                }),
            })

            # Save session state
            session_doc.save(ignore_permissions=False)
            frappe.db.commit()

            # Continue the agentic loop - AI will re-plan
            return _continue_agentic_loop(session_doc, conversation, tool_usage_log)

        elif action == "deny":
            # User denied the operation
            # Add a tool response indicating denial
            conversation.append({
                "tool_call_id": tool_call_id,
                "role": "tool",
                "name": tool_name,
                "content": json.dumps({
                    "status": "denied",
                    "message": f"User denied the {tool_name} operation. Do not attempt this action again unless explicitly asked."
                }),
            })

            # Log the denial
            tool_usage_entry = {
                "tool_name": tool_name,
                "parameters": tool_args,
                "timestamp": frappe.utils.now(),
                "status": "denied",
                "result_summary": f"User denied {tool_name}",
                "user_confirmed": False
            }
            tool_usage_log.append(tool_usage_entry)

            # Save session state
            session_doc.save(ignore_permissions=False)
            frappe.db.commit()

            # Continue the agentic loop - AI should acknowledge the denial
            return _continue_agentic_loop(session_doc, conversation, tool_usage_log)

    except frappe.DoesNotExistError:
        return {"error": "Conversation session not found", "tool_usage": []}
    except Exception as e:
        frappe.log_error(message=str(e), title="Confirm Write Operation Error")
        return {"error": str(e), "tool_usage": [], "session_id": session_id}


def _extract_created_entity(tool_name: str, response_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract created entity information from a write operation response.
    Returns entity info for frontend to display a quick link.
    """
    if not response_data or not response_data.get('success'):
        return None

    # Map tool names to their entity info extraction
    entity_extractors = {
        'create_lead': lambda data: {
            'id': data.get('lead_id'),
            'doctype': 'Lead',
            'label': data.get('lead_name') or data.get('lead_id'),
            'url': f"/app/lead/{data.get('lead_id')}"
        } if data.get('lead_id') else None,
        # Add more extractors here as new write operations are added
        # 'create_customer': lambda data: {...},
        # 'create_opportunity': lambda data: {...},
    }

    extractor = entity_extractors.get(tool_name)
    if extractor:
        try:
            return extractor(response_data)
        except Exception as e:
            logger.warning(f"Error extracting entity from {tool_name} response: {e}")
            return None

    return None


def _continue_agentic_loop(session_doc, conversation: List[Dict[str, Any]], tool_usage_log: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Continue the agentic loop from a given conversation state.
    Used after handling write operation confirmations.
    """
    try:
        client = get_openai_client()
        model, max_tokens = get_model_settings()
        tools = get_tools()

        # Add system instructions if not present
        if not conversation or conversation[0].get("role") != "system":
            conversation.insert(0, {"role": "system", "content": get_system_instructions()})

        # Trim conversation
        conversation = trim_conversation_to_token_limit(conversation, max_tokens)

        max_iterations = 15
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            response = client.chat.completions.create(
                model=model,
                messages=conversation,
                tools=tools,
                tool_choice="required"
            )

            response_message = response.choices[0].message
            logger.debug(f"_continue_agentic_loop response (iteration {iteration}): {response_message}")

            tool_calls = response_message.tool_calls
            if not tool_calls:
                logger.warning("No tool calls returned despite tool_choice=required in continuation")
                response_data = response_message.model_dump()
                response_data['tool_usage'] = tool_usage_log
                return response_data

            # Check for final_answer
            for tool_call in tool_calls:
                if tool_call.function.name == "final_answer":
                    try:
                        final_args = json.loads(tool_call.function.arguments)
                        logger.debug(f"Final answer received after {iteration} continuation iterations")

                        # Auto-link document IDs
                        message = final_args.get("message", "")
                        message = auto_link_document_ids(message)

                        # Build context summary
                        context_parts = []
                        for tool_entry in tool_usage_log:
                            tool_name = tool_entry.get("tool_name", "")
                            params = tool_entry.get("parameters", {})
                            if params and tool_name != "final_answer":
                                param_str = ", ".join(f"{k}={v}" for k, v in params.items() if v is not None)
                                context_parts.append(f"{tool_name}({param_str})")

                        if context_parts:
                            context_note = "\n\n<!-- CONTEXT: " + " | ".join(context_parts) + " -->"
                            message_with_context = message + context_note
                        else:
                            message_with_context = message

                        # Add assistant response
                        assistant_message = {
                            "role": "assistant",
                            "content": message_with_context,
                            "content_display": message,
                            "tool_usage": tool_usage_log
                        }
                        conversation.append(assistant_message)

                        # Save conversation
                        messages_to_save = extract_messages_for_storage(conversation)
                        session_doc.messages = json.dumps(messages_to_save)
                        session_doc.model_used = model
                        session_doc.save(ignore_permissions=False)
                        frappe.db.commit()

                        return {
                            "role": "assistant",
                            "content": message_with_context,
                            "content_display": message,
                            "tool_usage": tool_usage_log,
                            "summary": final_args.get("summary"),
                            "iterations": iteration,
                            "session_id": session_doc.name
                        }
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse final_answer arguments: {e}")
                        return {
                            "role": "assistant",
                            "content": "I encountered an error formatting my response.",
                            "tool_usage": tool_usage_log,
                            "error": str(e),
                            "session_id": session_doc.name
                        }

            # Handle tool calls (may return pending confirmation)
            conversation.append(response_message.model_dump())
            conversation, tool_usage_log, pending_confirmation = handle_tool_calls(
                tool_calls, conversation, tool_usage_log, session_doc
            )

            if pending_confirmation:
                logger.debug(f"Returning pending confirmation for {pending_confirmation['tool_name']} in continuation")
                return {
                    "status": "pending_confirmation",
                    "pending_confirmation": pending_confirmation,
                    "tool_usage": tool_usage_log,
                    "session_id": session_doc.name
                }

            conversation = trim_conversation_to_token_limit(conversation, max_tokens)
            logger.debug(f"Handled {len(tool_calls)} tool calls in continuation, iteration {iteration}")

        # Hit max iterations
        logger.warning(f"Hit max iterations ({max_iterations}) in continuation without final_answer")
        error_message = "I was unable to complete the request within the allowed number of steps."
        conversation.append({
            "role": "assistant",
            "content": error_message,
            "tool_usage": tool_usage_log
        })

        messages_to_save = extract_messages_for_storage(conversation)
        session_doc.messages = json.dumps(messages_to_save)
        session_doc.model_used = model
        session_doc.save(ignore_permissions=False)
        frappe.db.commit()

        return {
            "role": "assistant",
            "content": error_message,
            "tool_usage": tool_usage_log,
            "error": "max_iterations_reached",
            "session_id": session_doc.name
        }

    except Exception as e:
        frappe.log_error(message=str(e), title="Continue Agentic Loop Error")
        return {"error": str(e), "tool_usage": tool_usage_log, "session_id": session_doc.name if session_doc else None}


@frappe.whitelist()
def get_pending_confirmation(session_id: str) -> Dict[str, Any]:
    """
    Check if there's a pending write confirmation for a session.
    Used when reopening a chat dialog to restore pending state.

    :param session_id: The conversation session ID
    :return: Dictionary with pending confirmation data or None
    """
    try:
        if not session_id:
            return {"pending_confirmation": None}

        session_doc = frappe.get_doc("AI Conversation", session_id)

        # Check permission
        if session_doc.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
            frappe.throw("You don't have permission to access this conversation")

        if session_doc.pending_confirmation:
            pending = json.loads(session_doc.pending_confirmation)
            return {
                "pending_confirmation": {
                    "tool_name": pending.get('tool_name'),
                    "parameters": pending.get('parameters'),
                    "confirmation_message": pending.get('confirmation_message'),
                    "created_at": pending.get('created_at')
                },
                "session_id": session_id
            }

        return {"pending_confirmation": None, "session_id": session_id}

    except frappe.DoesNotExistError:
        return {"error": "Conversation session not found", "pending_confirmation": None}
    except Exception as e:
        frappe.log_error(message=str(e), title="Get Pending Confirmation Error")
        return {"error": str(e), "pending_confirmation": None}