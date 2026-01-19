frappe.ui.form.on("OpenAI Settings", {
  refresh: function (frm) {
    // Add custom button to test connection
    frm.add_custom_button(__("Test Connection"), function () {
      frappe.call({
        method: "erpnext_chatgpt.erpnext_chatgpt.api.test_connection",
        callback: function (r) {
          if (r.message) {
            if (r.message.success) {
              frappe.msgprint({
                title: __("Success"),
                message: r.message.message,
                indicator: "green",
              });
            } else {
              frappe.msgprint({
                title: __("Connection Failed"),
                message: r.message.message,
                indicator: "red",
              });
            }
          }
        }
      });
    });

    // Add help text for model selection
    if (frm.fields_dict.model) {
      frm.set_df_property("model", "description",
        "<b>Model Guide:</b><br>" +
        "• <b>gpt-4o-mini</b>: Best value - cheap, fast, 128k context (recommended)<br>" +
        "• <b>gpt-4o</b>: Fast GPT-4 class, 128k context<br>" +
        "• <b>gpt-4.1</b>: Excellent for coding tasks, 1M context<br>" +
        "• <b>gpt-4.1-mini</b>: Faster/cheaper coding model, 1M context<br>" +
        "• <b>gpt-5-mini</b>: Fast reasoning model, great balance<br>" +
        "• <b>gpt-5.1</b>: Advanced reasoning model<br>" +
        "• <b>gpt-5.2</b>: Latest flagship, best quality<br>" +
        "• <b>gpt-3.5-turbo</b>: Legacy, 8k context (not recommended)<br>" +
        "<br><i>Note: GPT-5 models may require higher API tier.</i>"
      );
    }

    // Add help text for max tokens
    if (frm.fields_dict.max_tokens) {
      frm.set_df_property("max_tokens", "description",
        "Maximum tokens for conversation context. Higher values allow longer conversations but may increase costs. " +
        "Recommended: 4000-8000 for normal use, 16000+ for long conversations."
      );
    }
  },

  api_key: function(frm) {
    // Mask the API key for security
    if (frm.doc.api_key && frm.doc.api_key.length > 10) {
      // Show only first 7 and last 4 characters
      let masked = frm.doc.api_key.substring(0, 7) + "..." + frm.doc.api_key.slice(-4);
      frm.set_df_property("api_key", "description", `Current key: ${masked}`);
    }
  },

  model: function(frm) {
    // Show cost indication when model changes
    const costInfo = {
      "gpt-4o-mini": "Low cost, 128k context (recommended)",
      "gpt-4o": "Moderate cost, 128k context",
      "gpt-4.1": "Moderate cost, 1M context, great for coding",
      "gpt-4.1-mini": "Low cost, 1M context",
      "gpt-5-mini": "Moderate cost, fast reasoning",
      "gpt-5.1": "Higher cost, advanced reasoning",
      "gpt-5.2": "Premium cost, flagship model",
      "gpt-3.5-turbo": "Legacy, 8k context only",
      "gpt-4": "Legacy, 8k context only",
      "gpt-4-turbo": "Moderate cost, 128k context"
    };

    if (frm.doc.model && costInfo[frm.doc.model]) {
      frappe.show_alert({
        message: `Model: ${frm.doc.model} (${costInfo[frm.doc.model]})`,
        indicator: "blue"
      }, 3);
    }
  }
});
