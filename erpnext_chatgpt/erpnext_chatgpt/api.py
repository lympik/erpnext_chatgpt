import frappe
import logging
from frappe import _
import json
from typing import List, Dict, Any
from erpnext_chatgpt.erpnext_chatgpt.tools import get_tools, available_functions

# Initialize module-level logger with aiassistant namespace
logger = frappe.logger("aiassistant", allow_site=True)
logger.setLevel(logging.DEBUG)

import re

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

    # Get custom system instructions from settings
    custom_instructions = frappe.db.get_single_value("OpenAI Settings", "system_instructions")

    # If no custom instructions are set, tell the user to configure them
    if not custom_instructions or custom_instructions.strip() == "":
        return "No system instructions are currently configured. Please go to the OpenAI Settings page to set up custom system instructions for the AI assistant."

    # Replace placeholders with actual values
    try:
        system_instructions = custom_instructions.format(
            user_name=user_full_name,
            user_email=current_user,
            user_roles=', '.join(user_roles) if user_roles else 'No roles assigned',
            company=company if company else 'Not set',
            current_datetime=frappe.utils.now()
        )
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
        model = "gpt-3.5-turbo"
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


def handle_tool_calls(tool_calls: List[Any], conversation: List[Dict[str, Any]], tool_usage_log: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Handle the tool calls by executing the corresponding functions and appending the results to the conversation.
    Also track tool usage for transparency.

    :param tool_calls: List of tool calls from OpenAI
    :param conversation: Current conversation history
    :param tool_usage_log: List to track tool usage
    :return: Tuple of updated conversation and tool usage log
    """
    for tool_call in tool_calls:
        function_name = tool_call.function.name
        function_to_call = available_functions.get(function_name)
        if not function_to_call:
            frappe.log_error(f"Function {function_name} not found.", "OpenAI Tool Error")
            raise ValueError(f"Function {function_name} not found.")

        function_args = json.loads(tool_call.function.arguments)

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
    return conversation, tool_usage_log

def estimate_token_count(messages: List[Dict[str, Any]]) -> int:
    """
    Estimate the token count for a list of messages.
    This is a rough estimation; OpenAI provides more accurate token counting in their own libraries.
    """
    tokens_per_message = 4  # Average tokens per message (considering metadata)
    tokens_per_word = 1.5   # Average tokens per word (this may vary)

    return sum(tokens_per_message + int(len(str(message.get("content", "")).split()) * tokens_per_word)
               for message in messages if message.get("content") is not None)

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
def ask_openai_question(conversation: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Ask a question to the OpenAI model and handle the response.
    Track all tool usage for transparency.

    :param conversation: List of conversation messages.
    :return: The response from OpenAI with tool usage information.
    """
    try:
        client = get_openai_client()
        tool_usage_log = []

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

                        # Return the final answer in the expected format
                        return {
                            "role": "assistant",
                            "content": message,
                            "tool_usage": tool_usage_log,
                            "summary": final_args.get("summary"),
                            "iterations": iteration
                        }
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse final_answer arguments: {e}")
                        return {
                            "role": "assistant",
                            "content": "I encountered an error formatting my response.",
                            "tool_usage": tool_usage_log,
                            "error": str(e)
                        }

            # No final_answer yet - handle the tool calls and continue
            conversation.append(response_message.model_dump())
            conversation, tool_usage_log = handle_tool_calls(tool_calls, conversation, tool_usage_log)

            # Trim conversation if needed
            conversation = trim_conversation_to_token_limit(conversation, max_tokens)

            logger.debug(f"Handled {len(tool_calls)} tool calls, continuing to iteration {iteration + 1}")

        # If we hit max iterations, force a response
        logger.warning(f"Hit max iterations ({max_iterations}) without final_answer")
        return {
            "role": "assistant",
            "content": "I was unable to complete the request within the allowed number of steps. Please try a simpler query.",
            "tool_usage": tool_usage_log,
            "error": "max_iterations_reached"
        }
    except Exception as e:
        frappe.log_error(message=str(e), title="OpenAI API Error")
        return {"error": str(e), "tool_usage": []}

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
            if any(prefix in model.id for prefix in ["gpt-3.5", "gpt-4"]):
                chat_models.append(model.id)

        # Sort models for better display
        chat_models.sort()
        return chat_models
    except Exception as e:
        frappe.log_error(str(e), "Failed to fetch available models")
        # Return default models if API call fails
        return ["gpt-3.5-turbo", "gpt-3.5-turbo-16k", "gpt-4", "gpt-4-turbo", "gpt-4o", "gpt-4o-mini"]

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