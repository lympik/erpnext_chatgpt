// Wait for the DOM to be fully loaded before initializing
document.addEventListener("DOMContentLoaded", initializeChat);

let conversation = [];

async function initializeChat() {
  await loadMarkedJs();
  await loadDompurify();

  checkUserPermissionsAndShowButton();
}

async function checkUserPermissionsAndShowButton() {
  try {
    const response = await frappe.call({
      method: "erpnext_chatgpt.erpnext_chatgpt.api.check_openai_key_and_role",
    });
    if (response?.message?.show_button) {
      showChatButton();
    }
  } catch (error) {
    console.error("Error checking permissions:", error);
  }
}

function showChatButton() {
  const chatButton = createChatButton();
  document.body.appendChild(chatButton);
  chatButton.addEventListener("click", openChatDialog);
}

function createChatButton() {
  const button = document.createElement("button");
  Object.assign(button, {
    id: "chatButton",
    className: "btn btn-primary btn-circle",
    innerHTML: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path><circle cx="9" cy="10" r="1"></circle><circle cx="15" cy="10" r="1"></circle></svg>',
    title: "Open AI Assistant",
  });
  Object.assign(button.style, {
    position: "fixed",
    zIndex: "1000",
    bottom: "20px",
    right: "20px",
    width: "56px",
    height: "56px",
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    boxShadow: "0 2px 10px rgba(0,0,0,0.2)",
  });
  return button;
}

function openChatDialog() {
  // Check if dialog already exists
  let dialog = document.getElementById("chatDialog");

  if (!dialog) {
    // Create new dialog only if it doesn't exist
    dialog = createChatDialog();
    document.body.appendChild(dialog);
  }

  // Show the dialog
  $(dialog).modal("show");

  // Load existing conversation from localStorage if available
  const saved = localStorage.getItem("chatConversation");
  if (saved) {
    conversation = JSON.parse(saved);
    displayConversation(conversation);
  } else {
    // Show suggestion prompts when chat is empty
    showSuggestionPrompts();
  }
}

function createChatDialog() {
  const dialog = document.createElement("div");
  dialog.id = "chatDialog";
  dialog.className = "modal fade";
  dialog.setAttribute("tabindex", "-1");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-labelledby", "chatDialogTitle");
  dialog.innerHTML = `
    <div class="modal-dialog" role="document">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title" id="chatDialogTitle">AI Assistant</h5>
          <div>
            <button type="button" class="btn btn-sm btn-outline-secondary mr-2" onclick="window.clearConversation()">Clear Chat</button>
            <button type="button" class="close" data-dismiss="modal" aria-label="Close">
              <span aria-hidden="true">&times;</span>
            </button>
          </div>
        </div>
        <div class="modal-body">
          <div id="answer" class="p-3" style="background: #f4f4f4; min-height: 400px; max-height: 400px; overflow-y: auto;"></div>
        </div>
        <div class="modal-footer d-flex align-items-center" style="flex-wrap:nowrap;">
          <input type="text" id="question" class="form-control mr-2" placeholder="Ask a question..." aria-label="Ask a question">
          <button type="button" class="btn btn-primary" id="askButton">Ask</button>
        </div>
      </div>
    </div>
  `;

  const askButton = dialog.querySelector("#askButton");
  askButton.addEventListener("click", window.handleAskButtonClick);

  const questionInput = dialog.querySelector("#question");
  questionInput.addEventListener("keypress", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      window.handleAskButtonClick();
    }
  });

  return dialog;
}

// Make handleAskButtonClick globally available
window.handleAskButtonClick = function() {
  const input = document.getElementById("question");
  const question = input.value.trim();
  if (!question) return;

  // Clear the input immediately after getting the question
  input.value = "";

  // Call askQuestion which will handle disabling/enabling
  askQuestion(question);
}

// Make clearConversation globally available
window.clearConversation = function() {
  conversation = [];
  localStorage.removeItem("chatConversation");
  const answerDiv = document.getElementById("answer");
  if (answerDiv) {
    answerDiv.innerHTML = "";
  }
  showSuggestionPrompts();
}

function showSuggestionPrompts() {
  const answerDiv = document.getElementById("answer");
  if (!answerDiv) return;

  const prompts = [
    "Show me today's sales invoices",
    "What are the pending purchase orders?",
    "Find service protocol for serial number OCU-00001",
    "List overdue customer invoices",
    "Show stock levels for my top items",
    "What's the total sales this month?",
    "Show recent delivery notes",
    "List all employees in the Sales department",
    "Find customer orders for ABC Company",
    "Show payment entries from last week"
  ];

  // Randomly select 4 prompts
  const selectedPrompts = [];
  const promptsCopy = [...prompts];
  for (let i = 0; i < 4 && promptsCopy.length > 0; i++) {
    const randomIndex = Math.floor(Math.random() * promptsCopy.length);
    selectedPrompts.push(promptsCopy.splice(randomIndex, 1)[0]);
  }

  answerDiv.innerHTML = `
    <div style="padding: 20px; text-align: center;">
      <div style="margin-bottom: 20px;">
        <h5 style="color: #666; font-weight: normal;">Welcome to ERPNext AI Assistant</h5>
        <p style="color: #888; font-size: 14px;">Ask me anything about your ERP data</p>
      </div>
      <div style="margin-top: 30px;">
        <p style="color: #666; font-size: 13px; margin-bottom: 15px;">Try asking:</p>
        <div style="display: flex; flex-wrap: wrap; gap: 10px; justify-content: center;">
          ${selectedPrompts.map(prompt => `
            <button
              class="btn btn-outline-primary btn-sm suggestion-prompt"
              onclick="useSuggestionPrompt('${prompt.replace(/'/g, "\\'")}')"
              style="border-radius: 20px; padding: 8px 16px; font-size: 13px; white-space: nowrap;"
            >
              ${prompt}
            </button>
          `).join('')}
        </div>
      </div>
    </div>
  `;
}

// Make useSuggestionPrompt globally available
window.useSuggestionPrompt = function(prompt) {
  const questionInput = document.getElementById("question");
  if (questionInput) {
    questionInput.value = prompt;
    window.handleAskButtonClick();
  }
}


async function askQuestion(question) {
  // Get input and button elements
  const input = document.getElementById("question");
  const askButton = document.getElementById("askButton");

  // Disable input and button while loading
  input.disabled = true;
  askButton.disabled = true;
  askButton.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Processing...';

  // Add user message to conversation
  conversation.push({ role: "user", content: question });
  displayConversation(conversation);

  try {
    const response = await fetch(
      "/api/method/erpnext_chatgpt.erpnext_chatgpt.api.ask_openai_question",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Frappe-CSRF-Token": frappe.csrf_token,
        },
        body: JSON.stringify({ conversation }),
      }
    );

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    console.log("API response:", data);

    const parsedMessage = parseResponseMessage(data);
    console.log("Parsed message with tool usage:", parsedMessage.tool_usage);
    conversation.push({
      role: "assistant",
      content: parsedMessage.content,
      tool_usage: parsedMessage.tool_usage
    });

    // Save conversation to localStorage
    localStorage.setItem("chatConversation", JSON.stringify(conversation));
    displayConversation(conversation);
  } catch (error) {
    console.error("Error in askQuestion:", error);
    // Remove the user message if there was an error
    conversation.pop();
    document.getElementById("answer").innerHTML += `
      <div class="alert alert-danger" role="alert">
        Error: ${error.message}. Please try again later.
      </div>
    `;
  } finally {
    // Re-enable input and button
    input.disabled = false;
    askButton.disabled = false;
    askButton.innerHTML = 'Ask';

    // Focus back on input for convenience
    input.focus();
  }
}

function parseResponseMessage(response) {
  // If the response is null or undefined, return an error message
  if (response == null) {
    return { content: "No response received.", tool_usage: [] };
  }

  // If the response is an object with a message property, use that
  const message = response.message ?? response;

  // Extract tool usage if present
  const tool_usage = message.tool_usage || [];

  // If the message is a string, return it directly
  if (typeof message === "string") {
    return { content: message, tool_usage: tool_usage };
  }

  // If the message is an object with a content property, return that
  if (message && typeof message === "object" && "content" in message) {
    return { content: message.content, tool_usage: tool_usage };
  }

  // If the message is an array, try to find a content item
  if (Array.isArray(message)) {
    const contentItem = message.find(
      (item) =>
        (Array.isArray(item) && item[0] === "content") ||
        (item && typeof item === "object" && "content" in item)
    );
    if (contentItem) {
      const content = Array.isArray(contentItem) ? contentItem[1] : contentItem.content;
      return { content: content, tool_usage: tool_usage };
    }
  }

  // If we can't parse the message in any known format, return the stringified version
  return { content: JSON.stringify(message, null, 2), tool_usage: tool_usage };
}

function displayConversation(conversation) {
  const conversationContainer = document.getElementById("answer");
  conversationContainer.innerHTML = "";

  conversation.forEach((message, index) => {
    const messageElement = document.createElement("div");
    messageElement.className =
      message.role === "user" ? "alert alert-primary" : "alert alert-light";

    // Add the main message content
    let content = renderMessageContent(message.content);

    // If this is an assistant message with tool usage, add a toggle button and hidden details
    if (message.role === "assistant" && message.tool_usage && message.tool_usage.length > 0) {
      console.log("Message has tool usage:", message.tool_usage);
      const messageId = `msg-${index}`;
      content += renderToolUsageToggle(message.tool_usage, messageId);
    }

    messageElement.innerHTML = content;
    conversationContainer.appendChild(messageElement);
  });

  // Scroll to bottom of conversation
  scrollToBottom();
}

function scrollToBottom() {
  const conversationContainer = document.getElementById("answer");
  if (conversationContainer) {
    // Use setTimeout to ensure DOM is updated before scrolling
    setTimeout(() => {
      conversationContainer.scrollTo({
        top: conversationContainer.scrollHeight,
        behavior: 'smooth'
      });
    }, 10);
  }
}

function renderToolUsageToggle(toolUsage, messageId) {
  if (!toolUsage || toolUsage.length === 0) return "";

  // Collect all fetched entities from all tool calls
  const allEntities = [];
  toolUsage.forEach(tool => {
    if (tool.fetched_entities && tool.fetched_entities.length > 0) {
      tool.fetched_entities.forEach(entity => {
        // Avoid duplicates
        if (!allEntities.find(e => e.id === entity.id && e.doctype === entity.doctype)) {
          allEntities.push(entity);
        }
      });
    }
  });

  return `
    <div class="mt-2">
      <button
        class="btn btn-sm btn-outline-secondary"
        onclick="toggleToolUsage('${messageId}')"
        style="font-size: 12px; padding: 4px 10px; border-radius: 4px;"
      >
        ℹ️ <span id="${messageId}-toggle-text">Show</span> data access info (${toolUsage.length} ${toolUsage.length === 1 ? 'query' : 'queries'})
      </button>
      ${renderEntityChips(allEntities, messageId)}
      <div id="${messageId}-details" style="display: none;" class="mt-2">
        ${renderToolUsageDetails(toolUsage)}
      </div>
    </div>
  `;
}

function renderEntityChips(entities, messageId) {
  if (!entities || entities.length === 0) return "";

  const chips = entities.map((entity, index) => {
    const chipId = `${messageId}-chip-${index}`;
    const docTypeUrl = entity.doctype.toLowerCase().replace(/ /g, '-');
    const encodedId = encodeURIComponent(entity.id);
    const url = `/app/${docTypeUrl}/${encodedId}`;

    // Truncate long labels
    const displayLabel = entity.label.length > 25
      ? entity.label.substring(0, 22) + '...'
      : entity.label;

    return `
      <a
        href="${url}"
        target="_blank"
        class="entity-chip"
        id="${chipId}"
        title="${entity.doctype}: ${entity.label}"
        style="
          display: inline-flex;
          align-items: center;
          padding: 4px 10px;
          margin: 2px;
          background-color: #e9ecef;
          border: 1px solid #ced4da;
          border-radius: 16px;
          font-size: 12px;
          color: #495057;
          text-decoration: none;
          white-space: nowrap;
          transition: background-color 0.2s, border-color 0.2s;
        "
        onmouseover="this.style.backgroundColor='#dee2e6'; this.style.borderColor='#adb5bd';"
        onmouseout="this.style.backgroundColor='#e9ecef'; this.style.borderColor='#ced4da';"
      >
        <span style="margin-right: 4px;">${getEntityIcon(entity.doctype)}</span>
        ${displayLabel}
      </a>
    `;
  }).join('');

  return `
    <div style="display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; margin-bottom: 4px;">
      ${chips}
    </div>
  `;
}

function getEntityIcon(doctype) {
  const icons = {
    'Customer': '👤',
    'Supplier': '🏭',
    'Item': '📦',
    'Employee': '👨‍💼',
    'Lead': '🎯',
    'Contact': '📇',
    'Delivery Note': '🚚',
    'Sales Invoice': '🧾',
    'Sales Order': '📋',
    'Purchase Order': '🛒',
    'Purchase Invoice': '📄',
    'Quotation': '💬',
    'Service Protocol': '🔧',
    'Stock Entry': '📥',
    'Payment Entry': '💳',
    'Journal Entry': '📒',
  };
  return icons[doctype] || '📄';
}

// Make toggleToolUsage globally available for onclick events
window.toggleToolUsage = function(messageId) {
  const details = document.getElementById(`${messageId}-details`);
  const toggleText = document.getElementById(`${messageId}-toggle-text`);

  if (details.style.display === "none") {
    details.style.display = "block";
    toggleText.textContent = "Hide";
  } else {
    details.style.display = "none";
    toggleText.textContent = "Show";
  }
}

function renderToolUsageDetails(toolUsage) {
  let toolHtml = `
    <div class="card" style="background-color: #f8f9fa; border: 1px solid #dee2e6;">
      <div class="card-body" style="padding: 10px;">
        <h6 class="card-title" style="font-size: 14px; margin-bottom: 10px;">
          🗄️ Data Accessed (${toolUsage.length} ${toolUsage.length === 1 ? 'query' : 'queries'})
        </h6>
        <div style="font-size: 12px;">
  `;

  toolUsage.forEach((tool, index) => {
    const statusIcon = tool.status === 'success' ? '✓' : '✗';
    const statusClass = tool.status === 'success' ? 'text-success' : 'text-danger';

    toolHtml += `
      <div class="mb-2" style="padding-left: 10px; border-left: 2px solid #dee2e6;">
        <strong>${index + 1}. ${formatToolName(tool.tool_name)}</strong>
        <span class="${statusClass}">${statusIcon}</span>
        ${tool.result_summary ? `<br><span class="text-muted">${tool.result_summary}</span>` : ''}
        ${renderToolParameters(tool.parameters)}
        ${tool.error ? `<br><span class="text-danger">Error: ${tool.error}</span>` : ''}
      </div>
    `;
  });

  toolHtml += `
        </div>
      </div>
    </div>
  `;

  return toolHtml;
}

function formatToolName(toolName) {
  // Convert snake_case to readable format
  return toolName
    .replace(/_/g, ' ')
    .replace(/\b\w/g, l => l.toUpperCase());
}

function renderToolParameters(params) {
  if (!params || Object.keys(params).length === 0) return "";

  let paramHtml = "<br><small style='margin-left: 20px;'>Parameters: ";
  const paramStrings = [];

  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") {
      paramStrings.push(`${key}: ${JSON.stringify(value)}`);
    }
  }

  if (paramStrings.length > 0) {
    paramHtml += paramStrings.join(", ");
  } else {
    paramHtml += "none";
  }

  paramHtml += "</small>";
  return paramHtml;
}

function convertERPNextReferencesToLinks(content) {
  // If content already contains HTML anchor tags from markdown parsing,
  // we need to be careful not to double-link things
  // First, let's temporarily replace existing anchor tags to protect them
  const anchorPlaceholders = [];
  let protectedContent = content.replace(/<a[^>]*>.*?<\/a>/gi, (match) => {
    const placeholder = `__ANCHOR_PLACEHOLDER_${anchorPlaceholders.length}__`;
    anchorPlaceholders.push(match);
    return placeholder;
  });

  // Map of common ERPNext DocTypes to their display names
  const docTypeMap = {
    'Sales Invoice': 'Sales Invoice',
    'Purchase Invoice': 'Purchase Invoice',
    'Sales Order': 'Sales Order',
    'Purchase Order': 'Purchase Order',
    'Delivery Note': 'Delivery Note',
    'Material Request': 'Material Request',
    'Stock Entry': 'Stock Entry',
    'Payment Entry': 'Payment Entry',
    'Journal Entry': 'Journal Entry',
    'Customer': 'Customer',
    'Supplier': 'Supplier',
    'Item': 'Item',
    'Employee': 'Employee',
    'Lead': 'Lead',
    'Opportunity': 'Opportunity',
    'Quotation': 'Quotation',
    'Purchase Receipt': 'Purchase Receipt',
    'Work Order': 'Work Order',
    'BOM': 'BOM',
    'Task': 'Task',
    'Project': 'Project',
    'Asset': 'Asset',
    'Service Protocol': 'Service Protocol'
  };

  // Create regex pattern for all DocTypes
  const docTypePattern = Object.keys(docTypeMap).join('|');

  // Pattern to match DocType: DocumentName format
  // Matches patterns like "Sales Invoice: SINV-2025-00001" or "Delivery Note: MAT-DN-2025-00201"
  const docRefRegex = new RegExp(
    `\\b(${docTypePattern}):\\s*([A-Z0-9][A-Z0-9\\-/\\.]+(?:[0-9]+)?)\\b`,
    'gi'
  );

  // Also match standalone Service Protocol references (SVP-YYYY-####)
  // But only if they're not already in a link
  const serviceProtocolRegex = /\b(SVP-\d{4}-\d{4})\b/gi;

  // Generate unique IDs for click handlers
  let linkCounter = 0;
  const clickHandlers = [];

  // Replace document references with clickable links (working on protected content)
  let processedContent = protectedContent.replace(docRefRegex, (match, docType, docName) => {
    linkCounter++;
    const linkId = `erpnext-link-${Date.now()}-${linkCounter}`;
    const normalizedDocType = Object.keys(docTypeMap).find(
      key => key.toLowerCase() === docType.toLowerCase()
    ) || docType;

    // Store the click handler to be attached after rendering
    clickHandlers.push({
      id: linkId,
      docType: normalizedDocType,
      docName: docName.trim()
    });

    // Return a styled link element
    return `<a href="#" id="${linkId}" class="erpnext-doc-link" style="color: #007bff; text-decoration: underline; cursor: pointer;" title="Open ${normalizedDocType}: ${docName.trim()}">${match}</a>`;
  });

  // Also replace standalone Service Protocol references (but not if they're placeholders)
  processedContent = processedContent.replace(serviceProtocolRegex, (match, protocolName, offset, string) => {
    // Check if this match is part of a placeholder
    if (string.substring(offset - 20, offset).includes('__ANCHOR_PLACEHOLDER_')) {
      return match; // Don't replace if it's part of a placeholder
    }

    linkCounter++;
    const linkId = `erpnext-link-${Date.now()}-${linkCounter}`;

    // Store the click handler to be attached after rendering
    clickHandlers.push({
      id: linkId,
      docType: 'Service Protocol',
      docName: protocolName.trim()
    });

    // Return a styled link element
    return `<a href="#" id="${linkId}" class="erpnext-doc-link" style="color: #007bff; text-decoration: underline; cursor: pointer;" title="Open Service Protocol: ${protocolName.trim()}">${match}</a>`;
  });

  // Restore the original anchor tags
  anchorPlaceholders.forEach((anchor, index) => {
    processedContent = processedContent.replace(`__ANCHOR_PLACEHOLDER_${index}__`, anchor);
  });

  // Attach click handlers after the content is rendered
  // Using setTimeout to ensure DOM is updated
  if (clickHandlers.length > 0) {
    setTimeout(() => {
      clickHandlers.forEach(handler => {
        const element = document.getElementById(handler.id);
        if (element) {
          element.addEventListener('click', (e) => {
            e.preventDefault();
            console.log(`Opening ${handler.docType}: ${handler.docName} in new tab`);
            // Build the URL for the document
            const url = `/app/${handler.docType.toLowerCase().replace(/ /g, '-')}/${encodeURIComponent(handler.docName)}`;
            // Open in new tab
            window.open(url, '_blank');
          });
        }
      });
    }, 100);
  }

  return processedContent;
}

function renderMessageContent(content) {
  console.log("Rendering content:", content);

  if (content === null) return "<em>null</em>";
  if (typeof content === "boolean") return `<strong>${content}</strong>`;
  if (typeof content === "number") return `<span>${content}</span>`;
  if (typeof content === "string") {
    // First parse markdown to convert markdown links to HTML
    const parsed = marked.parse(content);
    // Then sanitize the HTML
    const sanitized = DOMPurify.sanitize(parsed);
    // Finally, convert any remaining plain text ERPNext references to links
    // (but this won't affect already-rendered HTML links)
    const finalContent = convertERPNextReferencesToLinks(sanitized);
    console.log(finalContent);
    return finalContent;
  }
  if (Array.isArray(content)) {
    return `<ul class="list-group">${content
      .map(
        (item) =>
          `<li class="list-group-item">${renderMessageContent(item)}</li>`
      )
      .join("")}</ul>`;
  }
  if (typeof content === "object") return renderCollapsibleObject(content);

  return `<em>Unsupported type: ${typeof content}</em>`;
}

function renderCollapsibleObject(object) {
  const objectEntries = Object.entries(object)
    .map(
      ([key, value]) =>
        `<div><strong>${key}:</strong> ${renderMessageContent(value)}</div>`
    )
    .join("");
  return `
    <div class="collapsible-object">
      <button class="btn btn-sm btn-secondary" onclick="toggleCollapse(this)">Toggle Object</button>
      <div class="object-content" style="display: none; padding-left: 15px;">
        ${objectEntries}
      </div>
    </div>
  `;
}

// Make toggleCollapse globally available
window.toggleCollapse = function(button) {
  const content = button.nextElementSibling;
  content.style.display = content.style.display === "none" ? "block" : "none";
}

function isMarkdown(content) {
  return /[#*_~`]/.test(content);
}

function escapeHTML(text) {
  const map = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  };
  return text.replace(/[&<>"']/g, (m) => map[m]);
}

function cleanUrl(url) {
  try {
    const parsedUrl = new URL(url);
    return parsedUrl.href;
  } catch (error) {
    return null;
  }
}

async function loadMarkedJs() {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://cdn.jsdelivr.net/npm/marked/marked.min.js";
    script.onload = () => {
      class ERPNextRenderer extends marked.Renderer {
        // Block-level renderer methods
        heading(token) {
          const escapedText = token.text.toLowerCase().replace(/[^\w]+/g, "-");
          return `
            <h${token.depth} class="erpnext-heading" id="${escapedText}">
              ${token.text}
              <a href="#${escapedText}" class="anchor-link">
                <i class="fa fa-link" aria-hidden="true"></i>
              </a>
            </h${token.depth}>
          `;
        }

        cleanUrl(url) {
          return cleanUrl(url);
        }

        code(token) {
          const lang = token.lang || "plaintext";
          return `<pre><code class="hljs language-${lang}">${
            this.options.highlight
              ? this.options.highlight(token.text, lang)
              : token.text
          }</code></pre>`;
        }

        table(token) {
          let header = "";
          let body = "";

          // Generate table header
          header =
            "<thead><tr>" +
            token.header.map((cell) => this.tablecell(cell)).join("") +
            "</tr></thead>";

          // Generate table body
          body =
            "<tbody>" +
            token.rows
              .map((row) => {
                return (
                  "<tr>" +
                  row.map((cell) => this.tablecell(cell)).join("") +
                  "</tr>"
                );
              })
              .join("") +
            "</tbody>";

          return `
            <div class="table-responsive">
              <table class="table table-bordered table-hover">
                ${header}
                ${body}
              </table>
            </div>
          `;
        }

        tablecell(token) {
          const type = token.header ? "th" : "td";
          const classes = token.align ? `class="text-${token.align}"` : "";
          return `<${type} ${classes}>${this.parseInline(
            token.tokens
          )}</${type}>`;
        }

        list(token) {
          const type = token.ordered ? "ol" : "ul";
          const start = token.start === "" ? "" : ` start="${token.start}"`;
          return `<${type}${start}>\n${token.items
            .map((item) => this.listitem(item))
            .join("")}</${type}>\n`;
        }

        listitem(token) {
          const checkbox = token.task ? this.checkbox(token.checked) : "";
          const content = this.parseInline(token.tokens);
          return `<li>${checkbox}${content}</li>\n`;
        }

        checkbox(checked) {
          return `<input type="checkbox" ${
            checked ? "checked" : ""
          } disabled> `;
        }

        // Inline-level renderer methods
        link(token) {
          const href = this.cleanUrl(token.href);
          if (href === null) {
            return token.text;
          }
          return `<a href="${href}" target="_blank" rel="noopener noreferrer" title="${
            token.title || ""
          }">${token.text}</a>`;
        }

        image(token) {
          const src = this.cleanUrl(token.href);
          if (src === null) {
            return token.text;
          }
          return `<img src="${src}" alt="${token.text}" title="${
            token.title || ""
          }" class="img-fluid rounded">`;
        }

        // Helper method to parse inline tokens
        parseInline(tokens) {
          return tokens
            .map((token) => {
              switch (token.type) {
                case "text":
                case "escape":
                case "tag":
                  return this.text(token);
                case "link":
                  return this.link(token);
                case "image":
                  return this.image(token);
                case "strong":
                  return this.strong(token);
                case "em":
                  return this.em(token);
                case "codespan":
                  return this.codespan(token);
                case "br":
                  return this.br(token);
                case "del":
                  return this.del(token);
                default:
                  return "";
              }
            })
            .join("");
        }
      }
      const erpNextRenderer = new ERPNextRenderer();
      marked.setOptions({
        renderer: erpNextRenderer,
      });
      resolve();
    };
    script.onerror = () => reject(new Error("Failed to load marked.js"));
    document.head.appendChild(script);
  });
}

async function loadDompurify() {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src =
      "https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.1.6/purify.min.js";
    script.onload = resolve;
    script.onerror = () => reject(new Error("Failed to load dompurify"));
    document.head.appendChild(script);
  });
}
