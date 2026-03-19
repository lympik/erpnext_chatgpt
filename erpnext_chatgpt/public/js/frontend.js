// Wait for the DOM to be fully loaded before initializing
document.addEventListener("DOMContentLoaded", initializeChat);

// Version marker for debugging - remove after testing
console.log("ERPNext ChatGPT Frontend loaded - v2.0 with write confirmation support");

// Session-based conversation state
let currentSessionId = null;
let conversation = []; // Local display cache
let pendingConfirmation = null; // Stores pending write operation confirmation

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

async function openChatDialog() {
  // Check if dialog already exists
  let dialog = document.getElementById("chatDialog");

  if (!dialog) {
    // Create new dialog only if it doesn't exist
    dialog = createChatDialog();
    document.body.appendChild(dialog);
  }

  // Show the dialog
  $(dialog).modal("show");

  // Load conversation
  await loadConversation();
}

async function loadConversation() {
  const lastSessionId = localStorage.getItem("lastAISessionId");

  if (lastSessionId) {
    // Load the last session from server
    await loadSession(lastSessionId);
  } else {
    // No existing conversation, show welcome prompts
    conversation = [];
    showSuggestionPrompts();
  }
}

async function loadSession(sessionId) {
  try {
    const response = await frappe.call({
      method: "erpnext_chatgpt.erpnext_chatgpt.api.get_conversation",
      args: { session_id: sessionId }
    });

    if (response?.message?.success) {
      currentSessionId = sessionId;
      conversation = response.message.messages || [];
      updateConversationTitle(response.message.title);

      if (conversation.length === 0) {
        showSuggestionPrompts();
      } else {
        displayConversation(conversation);
      }

      // Check for pending confirmation first
      const hasPendingConfirmation = await checkPendingConfirmation(sessionId);

      // Only check for pending continuation if there's no pending confirmation
      // A session shouldn't have both states simultaneously
      if (!hasPendingConfirmation) {
        checkPendingContinuation(response.message.continuation_state);
      }
    } else {
      console.error("Failed to load session:", response?.message?.error);
      // Session not found, create new one
      await createNewConversation();
    }
  } catch (error) {
    console.error("Error loading session:", error);
    // Fall back to creating new conversation
    await createNewConversation();
  }
}

async function checkPendingConfirmation(sessionId) {
  try {
    const response = await frappe.call({
      method: "erpnext_chatgpt.erpnext_chatgpt.api.get_pending_confirmation",
      args: { session_id: sessionId }
    });

    if (response?.message?.pending_confirmation) {
      pendingConfirmation = response.message.pending_confirmation;
      renderWriteConfirmation(pendingConfirmation);
      return true; // Indicate that a pending confirmation was found
    }
  } catch (error) {
    console.error("Error checking pending confirmation:", error);
  }
  return false; // No pending confirmation
}

function checkPendingContinuation(continuationState) {
  // Check if the session has a saved continuation state (limit reached)
  // This is called after loading a session to restore the limit reached UI
  // The continuationState is passed directly from the loadSession response
  if (!continuationState) {
    return;
  }

  console.log("Found pending continuation state:", continuationState);

  // Reconstruct the limit reached data for the UI
  // Filter out 'think' entries to match the backend's initial response behavior
  const limitData = {
    status: "limit_reached",
    message: "The AI was interrupted at the iteration limit. You can continue or stop here.",
    progress_summary: {
      iterations_used: continuationState.iteration || 0,
      max_iterations: 15,
      tools_called: continuationState.tool_usage_log?.filter(t => t.tool_name !== 'think').map(t => t.tool_name) || [],
      thinking_steps: continuationState.tool_usage_log?.filter(t => t.is_thinking).length || 0
    }
  };

  renderLimitReachedUI(limitData);
}

async function createNewConversation() {
  try {
    // Clear any pending confirmation from previous conversation
    pendingConfirmation = null;
    removeConfirmationPanel();

    const response = await frappe.call({
      method: "erpnext_chatgpt.erpnext_chatgpt.api.create_conversation",
    });

    if (response?.message?.success) {
      currentSessionId = response.message.session_id;
      localStorage.setItem("lastAISessionId", currentSessionId);
      conversation = [];
      updateConversationTitle("New Conversation");
      showSuggestionPrompts();
      console.log("Created new conversation:", currentSessionId);
    } else {
      console.error("Failed to create conversation:", response?.message?.error);
      showSuggestionPrompts();
    }
  } catch (error) {
    console.error("Error creating conversation:", error);
    showSuggestionPrompts();
  }
}

function updateConversationTitle(title) {
  const titleElement = document.getElementById("chatDialogTitle");
  if (titleElement) {
    // Truncate title if too long
    const displayTitle = title.length > 40 ? title.substring(0, 37) + "..." : title;
    titleElement.textContent = displayTitle;
    titleElement.title = title; // Full title on hover
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
    <div class="modal-dialog modal-lg" role="document">
      <div class="modal-content">
        <div class="modal-header">
          <div class="d-flex align-items-center">
            <button type="button" class="btn btn-sm btn-outline-secondary mr-2" onclick="window.showConversationList()" title="View conversations">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>
            </button>
            <h5 class="modal-title mb-0" id="chatDialogTitle">AI Assistant</h5>
          </div>
          <div>
            <button type="button" class="btn btn-sm btn-outline-secondary mr-1" onclick="window.downloadDebugLog()" title="Download debug log">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
            </button>
            <button type="button" class="btn btn-sm btn-outline-primary mr-2" onclick="window.startNewConversation()" title="New conversation">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
              New
            </button>
            <button type="button" class="close" data-dismiss="modal" aria-label="Close">
              <span aria-hidden="true">&times;</span>
            </button>
          </div>
        </div>
        <div class="modal-body p-0">
          <div id="conversationListPanel" style="display: none; position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: white; z-index: 10; overflow-y: auto;">
            <div class="p-3 border-bottom d-flex justify-content-between align-items-center">
              <h6 class="mb-0">Conversations</h6>
              <button type="button" class="btn btn-sm btn-outline-secondary" onclick="window.hideConversationList()">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
              </button>
            </div>
            <div id="conversationListContent" class="p-2"></div>
          </div>
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

// Make startNewConversation globally available
window.startNewConversation = async function() {
  await createNewConversation();
}

// Make showConversationList globally available
window.showConversationList = async function() {
  const panel = document.getElementById("conversationListPanel");
  const content = document.getElementById("conversationListContent");

  if (panel && content) {
    panel.style.display = "block";
    content.innerHTML = '<div class="text-center p-3"><span class="spinner-border spinner-border-sm" role="status"></span> Loading...</div>';

    try {
      const response = await frappe.call({
        method: "erpnext_chatgpt.erpnext_chatgpt.api.list_conversations",
        args: { status: "Active", limit: 20 }
      });

      if (response?.message?.success) {
        renderConversationList(response.message.conversations);
      } else {
        content.innerHTML = '<div class="alert alert-warning m-2">Failed to load conversations</div>';
      }
    } catch (error) {
      console.error("Error loading conversations:", error);
      content.innerHTML = '<div class="alert alert-danger m-2">Error loading conversations</div>';
    }
  }
}

// Make hideConversationList globally available
window.hideConversationList = function() {
  const panel = document.getElementById("conversationListPanel");
  if (panel) {
    panel.style.display = "none";
  }
}

function renderConversationList(conversations) {
  const content = document.getElementById("conversationListContent");
  if (!content) return;

  if (conversations.length === 0) {
    content.innerHTML = '<div class="text-muted text-center p-3">No conversations yet</div>';
    return;
  }

  let html = '<div class="list-group list-group-flush">';
  conversations.forEach(conv => {
    const isActive = conv.name === currentSessionId;
    const lastMessageTime = conv.last_message_at ? formatRelativeTime(conv.last_message_at) : 'Just created';

    html += `
      <a href="#" class="list-group-item list-group-item-action ${isActive ? 'active' : ''}"
         onclick="window.switchConversation('${conv.name}')" style="cursor: pointer;">
        <div class="d-flex w-100 justify-content-between align-items-start">
          <div style="overflow: hidden;">
            <h6 class="mb-1 text-truncate" style="max-width: 280px;">${escapeHTML(conv.title || 'Untitled')}</h6>
            <small class="${isActive ? 'text-white-50' : 'text-muted'}">${conv.message_count || 0} messages</small>
          </div>
          <div class="text-right" style="white-space: nowrap;">
            <small class="${isActive ? 'text-white-50' : 'text-muted'}">${lastMessageTime}</small>
            <br>
            <button class="btn btn-sm btn-link p-0 ${isActive ? 'text-white' : ''}" onclick="event.stopPropagation(); window.archiveConversation('${conv.name}')" title="Archive">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
            </button>
          </div>
        </div>
      </a>
    `;
  });
  html += '</div>';

  content.innerHTML = html;
}

function formatRelativeTime(dateStr) {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

// Make switchConversation globally available
window.switchConversation = async function(sessionId) {
  // Clear any pending confirmation from current conversation
  pendingConfirmation = null;
  removeConfirmationPanel();

  window.hideConversationList();
  await loadSession(sessionId);
  localStorage.setItem("lastAISessionId", sessionId);
}

// Make archiveConversation globally available
window.archiveConversation = async function(sessionId) {
  if (!confirm("Archive this conversation?")) return;

  try {
    const response = await frappe.call({
      method: "erpnext_chatgpt.erpnext_chatgpt.api.archive_conversation",
      args: { session_id: sessionId }
    });

    if (response?.message?.success) {
      // Refresh the list
      if (sessionId === currentSessionId) {
        // If we archived the current conversation, start a new one
        await createNewConversation();
      }
      window.showConversationList();
    } else {
      frappe.msgprint("Failed to archive conversation");
    }
  } catch (error) {
    console.error("Error archiving conversation:", error);
    frappe.msgprint("Error archiving conversation");
  }
}

// Legacy clearConversation - now starts a new conversation
window.clearConversation = async function() {
  await createNewConversation();
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

  // Add user message to local display
  conversation.push({ role: "user", content: question });
  displayConversation(conversation);

  try {
    // Ensure we have a session ID
    if (!currentSessionId) {
      await createNewConversation();
    }

    // Send only session_id + message to server (server handles full history)
    const response = await fetch(
      "/api/method/erpnext_chatgpt.erpnext_chatgpt.api.ask_openai_question",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Frappe-CSRF-Token": frappe.csrf_token,
        },
        body: JSON.stringify({
          session_id: currentSessionId,
          message: question
        }),
      }
    );

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    console.log("API response:", data);
    console.log("data.message:", data.message);
    console.log("data.message?.status:", data.message?.status);
    console.log("Status equals pending_confirmation:", data.message?.status === "pending_confirmation");

    // Check if this is a pending confirmation response
    if (data.message?.status === "pending_confirmation") {
      console.log("Pending confirmation received:", data.message.pending_confirmation);
      pendingConfirmation = data.message.pending_confirmation;

      // Update session ID if returned
      if (data.message?.session_id) {
        currentSessionId = data.message.session_id;
        localStorage.setItem("lastAISessionId", currentSessionId);
      }

      // Display the confirmation UI
      try {
        renderWriteConfirmation(pendingConfirmation);
      } catch (err) {
        console.error("Error rendering confirmation UI:", err);
        // Fall back to displaying a simple message
        const answerDiv = document.getElementById("answer");
        if (answerDiv) {
          answerDiv.innerHTML += `<div class="alert alert-danger">Error displaying confirmation: ${err.message}</div>`;
        }
      }
      return; // Don't process as a normal response
    }

    // Check if this is a limit reached response
    if (data.message?.status === "limit_reached") {
      console.log("Iteration limit reached:", data.message.progress_summary);

      // Update session ID if returned
      if (data.message?.session_id) {
        currentSessionId = data.message.session_id;
        localStorage.setItem("lastAISessionId", currentSessionId);
      }

      // Display the limit reached UI
      renderLimitReachedUI(data.message);
      return; // Don't process as a normal response
    }

    const parsedMessage = parseResponseMessage(data);
    console.log("Parsed message with tool usage:", parsedMessage.tool_usage);

    // Update local conversation cache
    conversation.push({
      role: "assistant",
      content: parsedMessage.content,
      content_display: parsedMessage.content_display,
      tool_usage: parsedMessage.tool_usage
    });

    // Update session ID if returned (in case it was created during the call)
    if (data.message?.session_id) {
      currentSessionId = data.message.session_id;
      localStorage.setItem("lastAISessionId", currentSessionId);
    }

    displayConversation(conversation);

    // Update title after first message
    if (conversation.filter(m => m.role === "user").length === 1) {
      updateConversationTitle(question.length > 40 ? question.substring(0, 37) + "..." : question);
    }

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
    return { content: "No response received.", content_display: "No response received.", tool_usage: [] };
  }

  // If the response is an object with a message property, use that
  const message = response.message ?? response;

  // Extract tool usage if present
  const tool_usage = message.tool_usage || [];

  // If the message is a string, return it directly
  if (typeof message === "string") {
    return { content: message, content_display: message, tool_usage: tool_usage };
  }

  // If the message is an object with content property
  if (message && typeof message === "object" && "content" in message) {
    // Use content_display for UI if available, otherwise strip HTML comments from content
    const content = message.content || "";
    const content_display = message.content_display || content.replace(/\n\n<!--[\s\S]*?-->/g, "");
    return { content: content, content_display: content_display, tool_usage: tool_usage };
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
      return { content: content, content_display: content, tool_usage: tool_usage };
    }
  }

  // If we can't parse the message in any known format, return the stringified version
  const stringified = JSON.stringify(message, null, 2);
  return { content: stringified, content_display: stringified, tool_usage: tool_usage };
}

function displayConversation(conversation) {
  const conversationContainer = document.getElementById("answer");
  conversationContainer.innerHTML = "";

  let displayIndex = 0;
  conversation.forEach((message) => {
    // Only display user and assistant messages with actual content
    // Skip tool messages, system messages, and messages without content
    const role = message.role;
    if (role !== "user" && role !== "assistant") {
      return; // Skip tool, system, and other message types
    }

    const displayContent = message.content_display || message.content;
    if (!displayContent || displayContent === "null") {
      return; // Skip messages with no content
    }

    // For assistant messages, skip if it only has tool_calls (no final answer)
    if (role === "assistant" && message.tool_calls && !displayContent) {
      return;
    }

    const messageElement = document.createElement("div");
    messageElement.className =
      role === "user" ? "alert alert-primary" : "alert alert-light";

    let content = renderMessageContent(displayContent);

    // If this is an assistant message with a created entity, show a quick link
    if (role === "assistant" && message.created_entity) {
      content += renderCreatedEntityLink(message.created_entity);
    }

    // If this is an assistant message with tool usage, add a toggle button and hidden details
    if (role === "assistant" && message.tool_usage && message.tool_usage.length > 0) {
      console.log("Message has tool usage:", message.tool_usage);
      const messageId = `msg-${displayIndex}`;
      content += renderToolUsageToggle(message.tool_usage, messageId);
    }

    messageElement.innerHTML = content;
    conversationContainer.appendChild(messageElement);
    displayIndex++;
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

  // Separate thinking from regular tools
  const thinkingEntries = toolUsage.filter(t => t.is_thinking);
  const regularTools = toolUsage.filter(t => !t.is_thinking);

  // Collect all fetched entities from non-thinking tool calls
  const allEntities = [];
  regularTools.forEach(tool => {
    console.log("Tool usage entry:", tool.tool_name, "fetched_entities:", tool.fetched_entities);
    if (tool.fetched_entities && tool.fetched_entities.length > 0) {
      tool.fetched_entities.forEach(entity => {
        // Avoid duplicates
        if (!allEntities.find(e => e.id === entity.id && e.doctype === entity.doctype)) {
          allEntities.push(entity);
        }
      });
    }
  });
  console.log("All entities for chips:", allEntities);

  let html = `<div class="mt-2">`;

  // Regular tools section
  if (regularTools.length > 0) {
    html += `
      <button
        class="btn btn-sm btn-outline-secondary"
        onclick="toggleToolUsage('${messageId}')"
        style="font-size: 12px; padding: 4px 10px; border-radius: 4px;"
      >
        ℹ️ <span id="${messageId}-toggle-text">Show</span> data access info (${regularTools.length} ${regularTools.length === 1 ? 'query' : 'queries'})
      </button>
      ${renderEntityChips(allEntities, messageId)}
      <div id="${messageId}-details" style="display: none;" class="mt-2">
        ${renderToolUsageDetails(regularTools)}
      </div>
    `;
  }

  // Thinking section (collapsible)
  if (thinkingEntries.length > 0) {
    html += `
      <button
        class="btn btn-sm btn-outline-info ml-2"
        onclick="toggleThinking('${messageId}')"
        style="font-size: 12px; padding: 4px 10px; border-radius: 4px;"
      >
        🧠 <span id="${messageId}-thinking-toggle-text">Show</span> AI reasoning (${thinkingEntries.length})
      </button>
      <div id="${messageId}-thinking-details" style="display: none;" class="mt-2">
        ${renderThinkingDetails(thinkingEntries)}
      </div>
    `;
  }

  html += `</div>`;
  return html;
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

// Make toggleThinking globally available for onclick events
window.toggleThinking = function(messageId) {
  const details = document.getElementById(`${messageId}-thinking-details`);
  const toggleText = document.getElementById(`${messageId}-thinking-toggle-text`);

  if (details && toggleText) {
    if (details.style.display === "none") {
      details.style.display = "block";
      toggleText.textContent = "Hide";
    } else {
      details.style.display = "none";
      toggleText.textContent = "Show";
    }
  }
}

function renderThinkingDetails(thinkingEntries) {
  if (!thinkingEntries || thinkingEntries.length === 0) return "";

  let html = `
    <div class="card" style="background-color: #e7f3ff; border: 1px solid #b6d4fe;">
      <div class="card-body" style="padding: 10px;">
        <h6 class="card-title" style="font-size: 14px; margin-bottom: 10px; color: #084298;">
          🧠 AI Reasoning Process
        </h6>
        <div style="font-size: 12px;">
  `;

  thinkingEntries.forEach((entry, index) => {
    const params = entry.parameters || {};
    const reasoning = params.reasoning || 'No reasoning provided';
    const plan = params.plan;
    const observations = params.observations;

    html += `
      <div class="mb-2" style="padding: 8px; background: white; border-radius: 4px; border-left: 3px solid #0d6efd;">
        <div style="color: #333; margin-bottom: 4px;">
          <strong>Step ${index + 1}:</strong> ${escapeHTML(reasoning)}
        </div>
        ${plan ? `<div style="color: #666; font-size: 11px;"><strong>Plan:</strong> ${escapeHTML(plan)}</div>` : ''}
        ${observations ? `<div style="color: #666; font-size: 11px;"><strong>Observations:</strong> ${escapeHTML(observations)}</div>` : ''}
      </div>
    `;
  });

  html += `
        </div>
      </div>
    </div>
  `;

  return html;
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
        <strong>${index + 1}. ${escapeHTML(formatToolName(tool.tool_name))}</strong>
        <span class="${statusClass}">${statusIcon}</span>
        ${tool.result_summary ? `<br><span class="text-muted">${escapeHTML(String(tool.result_summary))}</span>` : ''}
        ${renderToolParameters(tool.parameters)}
        ${tool.error ? `<br><span class="text-danger">Error: ${escapeHTML(String(tool.error))}</span>` : ''}
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
      paramStrings.push(`${escapeHTML(key)}: ${escapeHTML(JSON.stringify(value))}`);
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
    return `<a href="#" id="${linkId}" class="erpnext-doc-link" style="color: #007bff; text-decoration: underline; cursor: pointer;" title="Open ${escapeHTML(normalizedDocType)}: ${escapeHTML(docName.trim())}">${escapeHTML(match)}</a>`;
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
    return `<a href="#" id="${linkId}" class="erpnext-doc-link" style="color: #007bff; text-decoration: underline; cursor: pointer;" title="Open Service Protocol: ${escapeHTML(protocolName.trim())}">${escapeHTML(match)}</a>`;
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

  if (content === null || content === undefined) return "";
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
    return finalContent;
  }

  // Handle Claude content block format: [{type: "text", text: "..."}]
  if (Array.isArray(content)) {
    // Extract text from content blocks
    const textParts = content
      .filter(block => block && (block.type === "text" || block.text))
      .map(block => block.text || "")
      .filter(text => text);

    if (textParts.length > 0) {
      return renderMessageContent(textParts.join("\n"));
    }

    // If no text blocks found, skip rendering
    return "";
  }

  // Handle single content block object: {type: "text", text: "..."}
  if (typeof content === "object") {
    if (content.type === "text" && content.text) {
      return renderMessageContent(content.text);
    }
    // Skip tool_use blocks and other non-text objects
    if (content.type === "tool_use" || content.type === "tool_result") {
      return "";
    }
    // For other objects, don't show "Toggle Object" - just skip
    return "";
  }

  return "";
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


// =============================================================================
// Write Operation Confirmation UI
// =============================================================================

function renderWriteConfirmation(confirmationData) {
  console.log("renderWriteConfirmation called with:", confirmationData);

  const answerDiv = document.getElementById("answer");
  if (!answerDiv) {
    console.error("answer div not found");
    return;
  }

  // Format the tool name for display
  const toolDisplayName = formatToolName(confirmationData.tool_name || 'unknown');
  const confirmationMessage = confirmationData.confirmation_message || `Execute ${toolDisplayName}`;
  const params = confirmationData.parameters || {};

  // Build parameter preview
  let paramPreview = '';
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') {
      const label = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
      paramPreview += `<div style="margin-bottom: 6px;"><strong>${escapeHTML(label)}:</strong> ${escapeHTML(String(value))}</div>`;
    }
  }
  if (!paramPreview) {
    paramPreview = '<em>No parameters specified</em>';
  }

  // Create the confirmation panel HTML
  const confirmationPanel = document.createElement('div');
  confirmationPanel.id = 'write-confirmation-panel';
  confirmationPanel.className = 'alert alert-warning';
  confirmationPanel.style.cssText = 'border-left: 4px solid #f0ad4e;';
  confirmationPanel.innerHTML = `
    <div style="display: flex; align-items: center; margin-bottom: 12px;">
      <span style="font-size: 24px; margin-right: 10px;">⚠️</span>
      <h5 style="margin: 0; font-weight: 600;">Confirm: ${escapeHTML(confirmationMessage)}</h5>
    </div>
    <p style="color: #666; margin-bottom: 15px; font-size: 13px;">
      Please review the data below before proceeding with this operation.
    </p>
    <div style="background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 6px; padding: 12px; margin-bottom: 15px;">
      ${paramPreview}
    </div>
    <div style="display: flex; gap: 10px; flex-wrap: wrap;">
      <button id="confirmAcceptBtn" class="btn btn-success">✓ Accept</button>
      <button id="confirmChangeBtn" class="btn btn-secondary">✎ Request Changes</button>
      <button id="confirmDenyBtn" class="btn btn-danger">✕ Deny</button>
    </div>
    <div id="changeInputArea" style="display: none; margin-top: 15px;">
      <textarea id="changeInputText" class="form-control" rows="3" placeholder="What would you like to change?" style="margin-bottom: 10px;"></textarea>
      <div style="display: flex; gap: 10px;">
        <button id="submitChangeBtn" class="btn btn-primary">Send Changes</button>
        <button id="cancelChangeBtn" class="btn btn-link">Cancel</button>
      </div>
    </div>
  `;

  // Append the confirmation panel to the answer div
  answerDiv.appendChild(confirmationPanel);
  console.log("Confirmation panel appended");

  // Scroll to the confirmation panel
  scrollToBottom();

  // Attach event handlers using setTimeout to ensure DOM is ready
  setTimeout(() => {
    const acceptBtn = document.getElementById('confirmAcceptBtn');
    const denyBtn = document.getElementById('confirmDenyBtn');
    const changeBtn = document.getElementById('confirmChangeBtn');
    const cancelBtn = document.getElementById('cancelChangeBtn');
    const submitBtn = document.getElementById('submitChangeBtn');
    const changeInput = document.getElementById('changeInputText');

    if (acceptBtn) acceptBtn.addEventListener('click', () => handleConfirmAction('accept'));
    if (denyBtn) denyBtn.addEventListener('click', () => handleConfirmAction('deny'));
    if (changeBtn) changeBtn.addEventListener('click', showChangeInput);
    if (cancelBtn) cancelBtn.addEventListener('click', hideChangeInput);
    if (submitBtn) submitBtn.addEventListener('click', submitChangeRequest);
    if (changeInput) {
      changeInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          submitChangeRequest();
        }
      });
    }
    console.log("Event handlers attached");
  }, 0);
}

function renderReadOnlyPreview(parameters) {
  if (!parameters || Object.keys(parameters).length === 0) {
    return '<p style="color: #666; font-style: italic; margin: 0;">No parameters specified</p>';
  }

  return Object.entries(parameters)
    .filter(([key, value]) => value !== null && value !== undefined && value !== '')
    .map(([key, value]) => {
      const label = formatLabel(key);
      const displayValue = typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
      return `
        <div style="display: flex; margin-bottom: 8px; font-size: 14px;">
          <span style="color: #495057; font-weight: 500; min-width: 120px;">${escapeHTML(label)}:</span>
          <span style="color: #212529;">${escapeHTML(displayValue)}</span>
        </div>
      `;
    }).join('');
}

function formatLabel(key) {
  // Convert snake_case or camelCase to Title Case
  return key
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/\b\w/g, l => l.toUpperCase());
}

function showChangeInput() {
  document.getElementById('changeInputArea').style.display = 'block';
  document.getElementById('changeInputText').focus();
}

function hideChangeInput() {
  document.getElementById('changeInputArea').style.display = 'none';
  document.getElementById('changeInputText').value = '';
}

async function handleConfirmAction(action) {
  const acceptBtn = document.getElementById('confirmAcceptBtn');
  const denyBtn = document.getElementById('confirmDenyBtn');
  const changeBtn = document.getElementById('confirmChangeBtn');

  // Disable all buttons
  acceptBtn.disabled = true;
  denyBtn.disabled = true;
  changeBtn.disabled = true;

  // Show loading state on the clicked button
  const activeBtn = action === 'accept' ? acceptBtn : denyBtn;
  const originalText = activeBtn.innerHTML;
  activeBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> Processing...';

  try {
    await sendWriteConfirmation(action);
  } catch (error) {
    console.error('Error handling confirmation:', error);
    frappe.msgprint({
      title: 'Error',
      indicator: 'red',
      message: `Failed to process confirmation: ${error.message}`
    });

    // Re-enable buttons on error
    acceptBtn.disabled = false;
    denyBtn.disabled = false;
    changeBtn.disabled = false;
    activeBtn.innerHTML = originalText;
  }
}

async function submitChangeRequest() {
  const changeText = document.getElementById('changeInputText').value.trim();
  if (!changeText) {
    frappe.msgprint({
      title: 'Input Required',
      indicator: 'yellow',
      message: 'Please describe what you would like to change.'
    });
    return;
  }

  const submitBtn = document.getElementById('submitChangeBtn');
  submitBtn.disabled = true;
  submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> Sending...';

  try {
    await sendWriteConfirmation('change', changeText);
  } catch (error) {
    console.error('Error submitting change request:', error);
    frappe.msgprint({
      title: 'Error',
      indicator: 'red',
      message: `Failed to submit changes: ${error.message}`
    });

    submitBtn.disabled = false;
    submitBtn.innerHTML = 'Send Changes';
  }
}

async function sendWriteConfirmation(action, userMessage = null) {
  if (!currentSessionId) {
    throw new Error('No active session');
  }

  // Remove the confirmation panel
  removeConfirmationPanel();

  // Clear the pending confirmation
  pendingConfirmation = null;

  // Show a processing message in the conversation
  const processingMessage = document.createElement('div');
  processingMessage.id = 'confirmation-processing';
  processingMessage.className = 'alert alert-light';
  processingMessage.innerHTML = `
    <div style="display: flex; align-items: center; gap: 10px;">
      <span class="spinner-border spinner-border-sm" role="status"></span>
      <span>${action === 'accept' ? 'Executing operation...' : action === 'change' ? 'Processing your changes...' : 'Processing denial...'}</span>
    </div>
  `;
  document.getElementById('answer').appendChild(processingMessage);
  scrollToBottom();

  try {
    const response = await fetch(
      "/api/method/erpnext_chatgpt.erpnext_chatgpt.api.confirm_write_operation",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Frappe-CSRF-Token": frappe.csrf_token,
        },
        body: JSON.stringify({
          session_id: currentSessionId,
          action: action,
          user_message: userMessage
        }),
      }
    );

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    console.log("Confirmation response:", data);

    // Remove the processing message
    const processingEl = document.getElementById('confirmation-processing');
    if (processingEl) {
      processingEl.remove();
    }

    // Check if this is another pending confirmation (e.g., after 'change')
    if (data.message?.status === "pending_confirmation") {
      console.log("Another pending confirmation received:", data.message.pending_confirmation);
      pendingConfirmation = data.message.pending_confirmation;
      renderWriteConfirmation(pendingConfirmation);
      return;
    }

    // Parse the response as a normal message
    const parsedMessage = parseResponseMessage(data);

    // Add to conversation, including created entity info if present
    conversation.push({
      role: "assistant",
      content: parsedMessage.content,
      content_display: parsedMessage.content_display,
      tool_usage: parsedMessage.tool_usage,
      created_entity: data.message?.created_entity || null
    });

    // Update session ID if returned
    if (data.message?.session_id) {
      currentSessionId = data.message.session_id;
      localStorage.setItem("lastAISessionId", currentSessionId);
    }

    // Display the updated conversation
    displayConversation(conversation);

  } catch (error) {
    // Remove the processing message on error
    const processingEl = document.getElementById('confirmation-processing');
    if (processingEl) {
      processingEl.remove();
    }
    throw error;
  }
}

function removeConfirmationPanel() {
  const panel = document.getElementById('write-confirmation-panel');
  if (panel) {
    panel.remove();
  }
}

function renderCreatedEntityLink(createdEntity) {
  if (!createdEntity || !createdEntity.id) return '';

  const doctype = createdEntity.doctype || 'Document';
  const label = createdEntity.label || createdEntity.id;
  const url = createdEntity.url || `/app/${doctype.toLowerCase().replace(/ /g, '-')}/${encodeURIComponent(createdEntity.id)}`;
  const icon = getEntityIcon(doctype);

  // Return HTML for inline display in the conversation
  return `
    <div style="margin-top: 12px; padding: 10px 14px; background: #d4edda; border: 1px solid #c3e6cb; border-radius: 6px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;">
      <div style="display: flex; align-items: center; gap: 8px; color: #155724;">
        <span style="font-size: 18px;">✅</span>
        <span><strong>${escapeHTML(doctype)}</strong> created successfully</span>
      </div>
      <a href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer"
         class="btn btn-sm btn-success"
         style="display: inline-flex; align-items: center; gap: 6px; text-decoration: none;">
        <span>${icon}</span>
        <span>Open ${escapeHTML(label)}</span>
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
          <polyline points="15 3 21 3 21 9"></polyline>
          <line x1="10" y1="14" x2="21" y2="3"></line>
        </svg>
      </a>
    </div>
  `;
}

// Make confirmation functions globally available for potential external use
window.handleConfirmAction = handleConfirmAction;
window.showChangeInput = showChangeInput;
window.hideChangeInput = hideChangeInput;
window.submitChangeRequest = submitChangeRequest;

// =============================================================================
// Iteration Limit Reached UI
// =============================================================================

function renderLimitReachedUI(limitData) {
  console.log("renderLimitReachedUI called with:", limitData);

  const answerDiv = document.getElementById("answer");
  if (!answerDiv) {
    console.error("answer div not found");
    return;
  }

  const progress = limitData.progress_summary || {};
  const toolsCalled = progress.tools_called || [];
  const iterations = progress.iterations_used || 0;
  const maxIterations = progress.max_iterations || 15;
  const thinkingSteps = progress.thinking_steps || 0;

  // Build a summary of tools used
  const toolSummary = {};
  toolsCalled.forEach(tool => {
    toolSummary[tool] = (toolSummary[tool] || 0) + 1;
  });

  let toolListHtml = '';
  for (const [tool, count] of Object.entries(toolSummary)) {
    toolListHtml += `<div style="display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #eee;">
      <span>${escapeHTML(formatToolName(tool))}</span>
      <span class="badge badge-secondary">${count}x</span>
    </div>`;
  }

  // Create the limit reached panel
  const limitPanel = document.createElement('div');
  limitPanel.id = 'limit-reached-panel';
  limitPanel.className = 'alert alert-info';
  limitPanel.style.cssText = 'border-left: 4px solid #17a2b8;';
  limitPanel.innerHTML = `
    <div style="display: flex; align-items: center; margin-bottom: 12px;">
      <span style="font-size: 24px; margin-right: 10px;">⏱️</span>
      <h5 style="margin: 0; font-weight: 600;">Processing Limit Reached</h5>
    </div>
    <p style="color: #0c5460; margin-bottom: 15px;">
      ${escapeHTML(limitData.message || 'The AI has used all available iterations but hasn\'t finished yet.')}
    </p>
    <div style="background: #d1ecf1; border: 1px solid #bee5eb; border-radius: 6px; padding: 12px; margin-bottom: 15px;">
      <div style="display: flex; justify-content: space-between; margin-bottom: 10px;">
        <strong>Progress:</strong>
        <span>${iterations} / ${maxIterations} iterations</span>
      </div>
      <div style="background: #fff; border-radius: 4px; height: 8px; overflow: hidden; margin-bottom: 10px;">
        <div style="background: #17a2b8; height: 100%; width: ${Math.min(100, (iterations / maxIterations) * 100)}%;"></div>
      </div>
      ${thinkingSteps > 0 ? `<div style="font-size: 12px; color: #0c5460; margin-bottom: 8px;">🧠 ${thinkingSteps} reasoning steps</div>` : ''}
      <div style="font-size: 13px; max-height: 150px; overflow-y: auto;">
        <strong style="display: block; margin-bottom: 6px;">Tools used (${toolsCalled.length} calls):</strong>
        ${toolListHtml || '<em>No tools called yet</em>'}
      </div>
    </div>
    <div style="display: flex; gap: 10px; flex-wrap: wrap;">
      <button id="limitContinueBtn" class="btn btn-primary">
        ▶️ Continue Processing
      </button>
      <button id="limitStopBtn" class="btn btn-secondary">
        ⏹️ Stop Here
      </button>
    </div>
  `;

  // Append the panel to the answer div
  answerDiv.appendChild(limitPanel);
  console.log("Limit reached panel appended");

  // Scroll to the panel
  scrollToBottom();

  // Attach event handlers
  setTimeout(() => {
    const continueBtn = document.getElementById('limitContinueBtn');
    const stopBtn = document.getElementById('limitStopBtn');

    if (continueBtn) continueBtn.addEventListener('click', () => handleLimitAction('continue'));
    if (stopBtn) stopBtn.addEventListener('click', () => handleLimitAction('stop'));
    console.log("Limit action handlers attached");
  }, 0);
}

async function handleLimitAction(action) {
  const continueBtn = document.getElementById('limitContinueBtn');
  const stopBtn = document.getElementById('limitStopBtn');

  // Disable buttons
  if (continueBtn) continueBtn.disabled = true;
  if (stopBtn) stopBtn.disabled = true;

  // Show loading state
  const activeBtn = action === 'continue' ? continueBtn : stopBtn;
  if (activeBtn) {
    const originalText = activeBtn.innerHTML;
    activeBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> Processing...';
  }

  // Remove the limit panel
  removeLimitReachedPanel();

  // Show a processing message
  const processingMessage = document.createElement('div');
  processingMessage.id = 'limit-processing';
  processingMessage.className = 'alert alert-light';
  processingMessage.innerHTML = `
    <div style="display: flex; align-items: center; gap: 10px;">
      <span class="spinner-border spinner-border-sm" role="status"></span>
      <span>${action === 'continue' ? 'Continuing processing...' : 'Stopping and saving progress...'}</span>
    </div>
  `;
  document.getElementById('answer').appendChild(processingMessage);
  scrollToBottom();

  try {
    const response = await fetch(
      "/api/method/erpnext_chatgpt.erpnext_chatgpt.api.continue_from_limit",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Frappe-CSRF-Token": frappe.csrf_token,
        },
        body: JSON.stringify({
          session_id: currentSessionId,
          action: action
        }),
      }
    );

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    console.log("Continue from limit response:", data);

    // Remove processing message
    const processingEl = document.getElementById('limit-processing');
    if (processingEl) processingEl.remove();

    // Check if we hit the limit again
    if (data.message?.status === "limit_reached") {
      console.log("Limit reached again:", data.message.progress_summary);
      renderLimitReachedUI(data.message);
      return;
    }

    // Check if there's a pending confirmation
    if (data.message?.status === "pending_confirmation") {
      pendingConfirmation = data.message.pending_confirmation;
      renderWriteConfirmation(pendingConfirmation);
      return;
    }

    // Parse and display the response
    const parsedMessage = parseResponseMessage(data);
    conversation.push({
      role: "assistant",
      content: parsedMessage.content,
      content_display: parsedMessage.content_display,
      tool_usage: parsedMessage.tool_usage
    });

    // Update session ID if returned
    if (data.message?.session_id) {
      currentSessionId = data.message.session_id;
      localStorage.setItem("lastAISessionId", currentSessionId);
    }

    displayConversation(conversation);

  } catch (error) {
    console.error('Error handling limit action:', error);

    // Remove processing message
    const processingEl = document.getElementById('limit-processing');
    if (processingEl) processingEl.remove();

    frappe.msgprint({
      title: 'Error',
      indicator: 'red',
      message: `Failed to ${action === 'continue' ? 'continue' : 'stop'}: ${error.message}`
    });
  }
}

function removeLimitReachedPanel() {
  const panel = document.getElementById('limit-reached-panel');
  if (panel) {
    panel.remove();
  }
}

// Make limit action functions globally available
window.handleLimitAction = handleLimitAction;


// =============================================================================
// Debug Log Download
// =============================================================================

window.downloadDebugLog = async function() {
  try {
    // Collect all debug information
    const debugData = {
      meta: {
        exported_at: new Date().toISOString(),
        session_id: currentSessionId,
        user: frappe.session.user,
        user_agent: navigator.userAgent,
        url: window.location.href,
        frappe_version: frappe.boot?.versions?.frappe || 'unknown',
        erpnext_version: frappe.boot?.versions?.erpnext || 'unknown'
      },
      conversation: {
        local_cache: conversation,
        message_count: conversation.length,
        user_messages: conversation.filter(m => m.role === 'user').length,
        assistant_messages: conversation.filter(m => m.role === 'assistant').length
      },
      tool_usage: extractAllToolUsage(),
      pending_confirmation: pendingConfirmation,
      local_storage: {
        lastAISessionId: localStorage.getItem('lastAISessionId')
      }
    };

    // Try to fetch server-side session data
    if (currentSessionId) {
      try {
        const serverData = await fetchServerDebugData(currentSessionId);
        debugData.server_session = serverData;
      } catch (err) {
        debugData.server_session = { error: err.message };
      }
    }

    // Generate filename with timestamp
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const filename = `ai-chat-debug-${currentSessionId || 'no-session'}-${timestamp}.json`;

    // Create and download the file
    const blob = new Blob([JSON.stringify(debugData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    frappe.show_alert({
      message: `Debug log downloaded: ${filename}`,
      indicator: 'green'
    }, 3);

  } catch (error) {
    console.error('Error downloading debug log:', error);
    frappe.msgprint({
      title: 'Download Error',
      indicator: 'red',
      message: `Failed to download debug log: ${error.message}`
    });
  }
};

function extractAllToolUsage() {
  // Extract all tool usage from conversation
  const allToolUsage = [];
  conversation.forEach((msg, index) => {
    if (msg.tool_usage && msg.tool_usage.length > 0) {
      allToolUsage.push({
        message_index: index,
        role: msg.role,
        tools: msg.tool_usage.map(tool => ({
          tool_name: tool.tool_name,
          parameters: tool.parameters,
          status: tool.status,
          result_summary: tool.result_summary,
          is_thinking: tool.is_thinking,
          error: tool.error,
          recovery_hint: tool.recovery_hint,
          timestamp: tool.timestamp
        }))
      });
    }
  });
  return allToolUsage;
}

async function fetchServerDebugData(sessionId) {
  const response = await frappe.call({
    method: 'erpnext_chatgpt.erpnext_chatgpt.api.get_debug_data',
    args: { session_id: sessionId }
  });

  if (response?.message?.success) {
    return response.message;
  } else {
    throw new Error(response?.message?.error || 'Failed to fetch server data');
  }
}
