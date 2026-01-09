/* AI Prompts Editor */

let currentCategory = null;
let currentPromptName = null;
let allPrompts = {};

async function loadPromptsEditor() {
  try {
    const data = await fetchJSON("/api/prompts");
    allPrompts = data.prompts || {};
    
    // Populate category selector
    const categorySelect = document.getElementById("prompt-category");
    categorySelect.innerHTML = '<option value="">Select a category...</option>';
    
    Object.keys(allPrompts).forEach(category => {
      const option = document.createElement("option");
      option.value = category;
      option.textContent = getCategoryDisplayName(category);
      categorySelect.appendChild(option);
    });
    
  } catch (e) {
    console.error("Error loading prompts:", e);
    showPromptMessage("Error loading prompts: " + e.message, "error");
  }
}

function getCategoryDisplayName(category) {
  const names = {
    'expansion': 'Portfolio Expansion',
    'dream': 'Dream Worker (KG Edges)',
    'think': 'Think Worker (Trading Committee)',
    'options': 'Options Workers'
  };
  return names[category] || category;
}

function onCategoryChange() {
  const categorySelect = document.getElementById("prompt-category");
  currentCategory = categorySelect.value;
  
  if (!currentCategory) {
    document.getElementById("prompt-name").innerHTML = '<option value="">Select category first</option>';
    clearPromptFields();
    return;
  }
  
  // Populate prompt name selector
  const promptNameSelect = document.getElementById("prompt-name");
  promptNameSelect.innerHTML = '<option value="">Select a prompt...</option>';
  
  const prompts = allPrompts[currentCategory] || {};
  Object.keys(prompts).forEach(promptName => {
    const option = document.createElement("option");
    option.value = promptName;
    option.textContent = formatPromptName(promptName);
    promptNameSelect.appendChild(option);
  });
  
  clearPromptFields();
}

function formatPromptName(name) {
  // Convert snake_case to Title Case
  return name.split('_').map(word => 
    word.charAt(0).toUpperCase() + word.slice(1)
  ).join(' ');
}

function onPromptNameChange() {
  const promptNameSelect = document.getElementById("prompt-name");
  currentPromptName = promptNameSelect.value;
  
  if (!currentPromptName || !currentCategory) {
    clearPromptFields();
    return;
  }
  
  const prompt = allPrompts[currentCategory][currentPromptName];
  if (prompt) {
    document.getElementById("prompt-description").value = prompt.description || '';
    document.getElementById("prompt-system").value = prompt.system || '';
    document.getElementById("prompt-user").value = prompt.user_template || '';
    
    // Show template variables info
    const variables = extractTemplateVariables(prompt.user_template || '');
    if (variables.length > 0) {
      document.getElementById("prompt-info").innerHTML = 
        `<b>Template Variables:</b> ${variables.map(v => `<code>{${v}}</code>`).join(', ')}`;
      document.getElementById("prompt-info").style.display = 'block';
    } else {
      document.getElementById("prompt-info").style.display = 'none';
    }
  }
}

function extractTemplateVariables(template) {
  const matches = template.match(/\{([^}]+)\}/g) || [];
  return [...new Set(matches.map(m => m.slice(1, -1)))];
}

function clearPromptFields() {
  document.getElementById("prompt-description").value = '';
  document.getElementById("prompt-system").value = '';
  document.getElementById("prompt-user").value = '';
  document.getElementById("prompt-info").style.display = 'none';
}

async function saveCurrentPrompt() {
  if (!currentCategory || !currentPromptName) {
    showPromptMessage("Please select a category and prompt first", "error");
    return;
  }
  
  const updatedPrompt = {
    description: document.getElementById("prompt-description").value,
    system: document.getElementById("prompt-system").value,
    user_template: document.getElementById("prompt-user").value
  };
  
  try {
    const result = await fetchJSON(`/api/prompts/${currentCategory}/${currentPromptName}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updatedPrompt)
    });
    
    if (result.success) {
      showPromptMessage("✅ Prompt saved successfully! Changes will take effect on next LLM call.", "success");
      
      // Update local cache
      allPrompts[currentCategory][currentPromptName] = updatedPrompt;
    } else {
      showPromptMessage("Error: " + (result.error || "Failed to save"), "error");
    }
  } catch (e) {
    console.error("Error saving prompt:", e);
    showPromptMessage("Error saving prompt: " + e.message, "error");
  }
}

async function reloadPrompts() {
  try {
    const result = await fetchJSON("/api/prompts/reload", {
      method: "POST"
    });
    
    if (result.success) {
      showPromptMessage("✅ Prompts reloaded from disk", "success");
      await loadPromptsEditor();
    } else {
      showPromptMessage("Error reloading prompts", "error");
    }
  } catch (e) {
    console.error("Error reloading prompts:", e);
    showPromptMessage("Error: " + e.message, "error");
  }
}

function resetCurrentPrompt() {
  if (!currentCategory || !currentPromptName) {
    return;
  }
  
  if (confirm("Reset this prompt to the last saved version?")) {
    onPromptNameChange(); // Reload from cache
    showPromptMessage("Prompt reset to last saved version", "info");
  }
}

function showPromptMessage(message, type = "info") {
  const infoBox = document.getElementById("prompt-info");
  infoBox.textContent = message;
  infoBox.style.display = 'block';
  
  // Update color based on type
  if (type === "success") {
    infoBox.style.borderColor = "#10b981";
    infoBox.style.background = "rgba(16, 185, 129, 0.1)";
  } else if (type === "error") {
    infoBox.style.borderColor = "#ef4444";
    infoBox.style.background = "rgba(239, 68, 68, 0.1)";
  } else {
    infoBox.style.borderColor = "#3b82f6";
    infoBox.style.background = "rgba(59, 130, 246, 0.1)";
  }
  
  // Auto-hide info messages after 5 seconds
  if (type === "info") {
    setTimeout(() => {
      infoBox.style.display = 'none';
    }, 5000);
  }
}
