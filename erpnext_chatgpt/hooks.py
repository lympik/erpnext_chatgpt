app_name = "erpnext_chatgpt"
app_title = "OpenAI Integration"
app_publisher = "William Luke"
app_description = "ERPNext app for OpenAI integration"
app_icon = "octicon octicon-file-directory"
app_color = "grey"
app_email = "williamluke4@gmail.com"
app_license = "MIT"

# Include JS and CSS files in header of desk.html
app_include_js = [
    "/assets/erpnext_chatgpt/js/frontend.js?v=9",
    "/assets/erpnext_chatgpt/js/openai_settings.js?v=1"
]

# Doctype JavaScript
doctype_js = {
    "OpenAI Settings": "public/js/openai_settings.js"
}

fixtures = [{"dt": "DocType", "filters": [["name", "in", ["OpenAI Settings", "AI Conversation"]]]}]
