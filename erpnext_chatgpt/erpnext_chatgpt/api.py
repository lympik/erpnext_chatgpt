import frappe
from frappe import _
import json
from typing import List, Dict, Any
from erpnext_chatgpt.erpnext_chatgpt.tools import get_tools, available_functions

def get_system_instructions():
    """Get system instructions with current date and user context."""
    current_user = frappe.session.user
    user_full_name = frappe.get_value("User", current_user, "full_name") or current_user
    user_roles = frappe.get_roles(current_user)
    company = frappe.defaults.get_user_default("company") or frappe.defaults.get_global_default("company")

    return f"""You are an AI assistant integrated with ERPNext, helping {user_full_name} ({current_user}) with their ERP queries.

## Core Instructions:
- Provide accurate, concise, and actionable responses based on ERPNext data
- When querying ERPNext objects without specific property requests, return the 'name' property by default
- Ask clarifying questions when queries are ambiguous
- Format responses clearly using markdown for better readability
- When presenting data, summarize key insights before showing detailed records

## Current Context:
- Date/Time: {frappe.utils.now()}
- User: {user_full_name} ({current_user})
- Roles: {', '.join(user_roles) if user_roles else 'No roles assigned'}
- Company: {company if company else 'Not set'}

## Response Guidelines:
- When querying data with tools, ALWAYS analyze and present the results clearly
- For financial queries: Calculate and show totals, averages, and other relevant metrics
- When asked for totals or summaries, provide the specific numbers from the data retrieved
- For lists: Show summary statistics (count, totals, averages) before detailed records
- When referencing ERPNext documents, show ONLY the ID as a link:
  - [SI-2024-00001](/app/sales-invoice/SI-2024-00001) for sales invoices
  - [PO-2024-00123](/app/purchase-order/PO-2024-00123) for purchase orders
  - [ABC Company](/app/customer/ABC%20Company) for customers
- Convert doctype names to URL format: lowercase with hyphens replacing spaces (e.g., "Service Protocol" → "service-protocol")
- URL-encode document names with spaces or special characters
- For financial data: Include currency and format numbers appropriately
- For errors: Provide helpful suggestions to resolve the issue
- Keep responses focused and avoid unnecessary technical details unless specifically asked"""

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

        except Exception as e:
            frappe.log_error(f"Error calling function {function_name} with args {json.dumps(function_args)}: {str(e)}", "OpenAI Tool Error")
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

        frappe.logger("OpenAI").debug(f"Conversation: {json.dumps(conversation)}")

        tools = get_tools()
        response = client.chat.completions.create(
            model=model,
            messages=conversation,
            tools=tools,
            tool_choice="auto"
        )

        response_message = response.choices[0].message

        frappe.logger("OpenAI").debug(f"OpenAI Response: {response_message}")

        tool_calls = response_message.tool_calls
        if tool_calls:
            conversation.append(response_message.model_dump())
            conversation, tool_usage_log = handle_tool_calls(tool_calls, conversation, tool_usage_log)

            # Trim again if needed after tool calls
            conversation = trim_conversation_to_token_limit(conversation, max_tokens)

            second_response = client.chat.completions.create(
                model=model,
                messages=conversation
            )

            # Return response with tool usage information
            response_data = second_response.choices[0].message.model_dump()
            response_data['tool_usage'] = tool_usage_log
            return response_data

        # Return response with empty tool usage if no tools were called
        response_data = response_message.model_dump()
        response_data['tool_usage'] = tool_usage_log
        return response_data
    except Exception as e:
        frappe.log_error(str(e), "OpenAI API Error")
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