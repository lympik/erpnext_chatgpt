# Copyright (c) 2025, William Luke and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class AIConversation(Document):
    def before_save(self):
        # Update message count from messages array
        if self.messages:
            import json
            try:
                messages = json.loads(self.messages) if isinstance(self.messages, str) else self.messages
                # Count only user and assistant messages (not system or tool messages)
                self.message_count = sum(
                    1 for msg in messages
                    if isinstance(msg, dict) and msg.get('role') in ['user', 'assistant']
                )
            except (json.JSONDecodeError, TypeError):
                pass

        # Update last_message_at timestamp
        self.last_message_at = frappe.utils.now()

    def validate(self):
        # Ensure users can only access their own conversations
        if not frappe.has_permission("AI Conversation", "write", doc=self):
            frappe.throw("You don't have permission to modify this conversation")
