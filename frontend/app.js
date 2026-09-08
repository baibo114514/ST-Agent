const STORAGE_KEYS = {
  apiBase: "fastgraph.console.apiBase",
  userToken: "fastgraph.console.userToken",
  userEmail: "fastgraph.console.userEmail",
  isAdmin: "fastgraph.console.isAdmin",
  activeAgentId: "fastgraph.console.activeAgentId",
  sessionAgents: "fastgraph.console.sessionAgents",
};

const state = {
  apiBase: localStorage.getItem(STORAGE_KEYS.apiBase) || (window.APP_CONFIG && window.APP_CONFIG.apiBase) || "http://127.0.0.1:8000",
  userToken: localStorage.getItem(STORAGE_KEYS.userToken) || "",
  userEmail: localStorage.getItem(STORAGE_KEYS.userEmail) || "",
  isAdmin: localStorage.getItem(STORAGE_KEYS.isAdmin) === "1",
  view: "user",
  userAgents: [],
  activeAgentId: localStorage.getItem(STORAGE_KEYS.activeAgentId) || "",
  sessions: [],
  sessionAgents: readJsonStorage(STORAGE_KEYS.sessionAgents, {}),
  sessionId: "",
  sessionToken: "",
  messages: [],
  platformAgents: [],
  knowledgeBases: [],
  knowledgeBaseOptions: [],
  knowledgePage: 1,
  knowledgePageSize: 8,
  knowledgeTotal: 0,
  knowledgeTotalPages: 0,
  selectedKbId: "",
  selectedKnowledgeBaseDetail: null,
  documents: [],
  documentPage: 1,
  documentPageSize: 12,
  documentTotal: 0,
  documentTotalPages: 0,
  jobs: [],
  jobPage: 1,
  jobPageSize: 12,
  jobTotal: 0,
  jobTotalPages: 0,
  searchResults: [],
  selectedAgentKbIds: [],
  agentKbDropdownOpen: false,
  agentKbKeyword: "",
  includeArchived: false,
  knowledgeError: "",
  kbTab: "documents",
  kbKeyword: "",
  kbSearchTimer: null,
  documentKeyword: "",
  documentSearchTimer: null,
  documentSourceFilter: "all",
  jobStatusFilter: "",
  uploadMode: "file",
  selectedDocument: null,
  selectedJob: null,
  loading: false,
  streaming: false,
};

const elements = {
  apiBaseInput: document.querySelector("#apiBaseInput"),
  authPanel: document.querySelector("#authPanel"),
  consolePanel: document.querySelector("#consolePanel"),
  authForm: document.querySelector("#authForm"),
  emailInput: document.querySelector("#emailInput"),
  passwordInput: document.querySelector("#passwordInput"),
  userIdentity: document.querySelector("#userIdentity"),
  agentListMeta: document.querySelector("#agentListMeta"),
  userAgentList: document.querySelector("#userAgentList"),
  userSessionList: document.querySelector("#userSessionList"),
  activeAgentTitle: document.querySelector("#activeAgentTitle"),
  activeAgentMeta: document.querySelector("#activeAgentMeta"),
  activeSessionMeta: document.querySelector("#activeSessionMeta"),
  messageList: document.querySelector("#messageList"),
  chatForm: document.querySelector("#chatForm"),
  chatInput: document.querySelector("#chatInput"),
  userView: document.querySelector("#userView"),
  agentAdminView: document.querySelector("#agentAdminView"),
  knowledgeAdminView: document.querySelector("#knowledgeAdminView"),
  platformAgentList: document.querySelector("#platformAgentList"),
  agentAdminStatus: document.querySelector("#agentAdminStatus"),
  agentForm: document.querySelector("#agentForm"),
  agentIdInput: document.querySelector("#agentIdInput"),
  agentCodeInput: document.querySelector("#agentCodeInput"),
  agentNameInput: document.querySelector("#agentNameInput"),
  agentDescriptionInput: document.querySelector("#agentDescriptionInput"),
  agentModelInput: document.querySelector("#agentModelInput"),
  agentRoleInput: document.querySelector("#agentRoleInput"),
  featureWebSearch: document.querySelector("#featureWebSearch"),
  featureCode: document.querySelector("#featureCode"),
  featureMemory: document.querySelector("#featureMemory"),
  featureEmail: document.querySelector("#featureEmail"),
  knowledgeEnabledInput: document.querySelector("#knowledgeEnabledInput"),
  agentKbSelect: document.querySelector("#agentKbSelect"),
  agentTopKInput: document.querySelector("#agentTopKInput"),
  agentScoreInput: document.querySelector("#agentScoreInput"),
  includeArchivedInput: document.querySelector("#includeArchivedInput"),
  kbKeywordInput: document.querySelector("#kbKeywordInput"),
  knowledgeStatus: document.querySelector("#knowledgeStatus"),
  knowledgePagerInfo: document.querySelector("#knowledgePagerInfo"),
  kbForm: document.querySelector("#kbForm"),
  kbIdInput: document.querySelector("#kbIdInput"),
  kbNamespaceInput: document.querySelector("#kbNamespaceInput"),
  kbNameInput: document.querySelector("#kbNameInput"),
  kbDescriptionInput: document.querySelector("#kbDescriptionInput"),
  kbStrategyInput: document.querySelector("#kbStrategyInput"),
  kbWebFallbackInput: document.querySelector("#kbWebFallbackInput"),
  metadataExtractionForm: document.querySelector("#metadataExtractionForm"),
  metadataExtractionEnabledInput: document.querySelector("#metadataExtractionEnabledInput"),
  metadataExtractionSchemaNameInput: document.querySelector("#metadataExtractionSchemaNameInput"),
  metadataExtractionSchemaVersionInput: document.querySelector("#metadataExtractionSchemaVersionInput"),
  metadataMappingsTable: document.querySelector("#metadataMappingsTable"),
  metadataMappingsEmpty: document.querySelector("#metadataMappingsEmpty"),
  metadataDefaultsTable: document.querySelector("#metadataDefaultsTable"),
  metadataDefaultsEmpty: document.querySelector("#metadataDefaultsEmpty"),
  metadataExtractionFormatInput: document.querySelector("#metadataExtractionFormatInput"),
  metadataExtractionMaxLinesInput: document.querySelector("#metadataExtractionMaxLinesInput"),
  metadataExtractionStripInput: document.querySelector("#metadataExtractionStripInput"),
  metadataExtractionKeepUnmappedInput: document.querySelector("#metadataExtractionKeepUnmappedInput"),
  metadataExtractionStatus: document.querySelector("#metadataExtractionStatus"),
  kbEditorDrawer: document.querySelector("#kbEditorDrawer"),
  kbEditorTitle: document.querySelector("#kbEditorTitle"),
  knowledgeBaseList: document.querySelector("#knowledgeBaseList"),
  kbEmptyState: document.querySelector("#kbEmptyState"),
  kbDetailPanel: document.querySelector("#kbDetailPanel"),
  selectedKbTitle: document.querySelector("#selectedKbTitle"),
  selectedKbDescription: document.querySelector("#selectedKbDescription"),
  selectedKbNamespace: document.querySelector("#selectedKbNamespace"),
  selectedKbStatus: document.querySelector("#selectedKbStatus"),
  archiveKbButton: document.querySelector("#archiveKbButton"),
  restoreKbButton: document.querySelector("#restoreKbButton"),
  kbDocsMetric: document.querySelector("#kbDocsMetric"),
  kbChunksMetric: document.querySelector("#kbChunksMetric"),
  kbFailedJobsMetric: document.querySelector("#kbFailedJobsMetric"),
  kbUpdatedMetric: document.querySelector("#kbUpdatedMetric"),
  uploadForm: document.querySelector("#uploadForm"),
  uploadTitleInput: document.querySelector("#uploadTitleInput"),
  uploadSourceRefInput: document.querySelector("#uploadSourceRefInput"),
  uploadFileInput: document.querySelector("#uploadFileInput"),
  uploadDirectoryInput: document.querySelector("#uploadDirectoryInput"),
  uploadStatus: document.querySelector("#uploadStatus"),
  searchInput: document.querySelector("#searchInput"),
  searchTopKInput: document.querySelector("#searchTopKInput"),
  documentKeywordInput: document.querySelector("#documentKeywordInput"),
  documentSourceFilter: document.querySelector("#documentSourceFilter"),
  jobStatusFilter: document.querySelector("#jobStatusFilter"),
  documentPagerInfo: document.querySelector("#documentPagerInfo"),
  jobPagerInfo: document.querySelector("#jobPagerInfo"),
  documentList: document.querySelector("#documentList"),
  jobList: document.querySelector("#jobList"),
  searchResults: document.querySelector("#searchResults"),
  documentDrawer: document.querySelector("#documentDrawer"),
  documentDrawerTitle: document.querySelector("#documentDrawerTitle"),
  documentDetailContent: document.querySelector("#documentDetailContent"),
  jobDrawer: document.querySelector("#jobDrawer"),
  jobDrawerTitle: document.querySelector("#jobDrawerTitle"),
  jobDetailContent: document.querySelector("#jobDetailContent"),
  toast: document.querySelector("#toast"),
};

elements.apiBaseInput.value = state.apiBase;
elements.includeArchivedInput.checked = state.includeArchived;
bindEvents();
renderUploadMode();
renderSession();
if (state.userToken) {
  bootstrap();
}

function bindEvents() {
  document.addEventListener("click", handleActionClick);
  document.addEventListener("change", handleChange);
  document.addEventListener("input", handleInput);
  document.addEventListener("keydown", handleKeydown);
  elements.authForm.addEventListener("submit", handleAuthSubmit);
  elements.chatForm.addEventListener("submit", handleChatSubmit);
  elements.agentForm.addEventListener("submit", handleAgentSubmit);
  elements.kbForm.addEventListener("submit", handleKbSubmit);
  elements.metadataExtractionForm.addEventListener("submit", handleMetadataExtractionSubmit);
  elements.uploadForm.addEventListener("submit", handleUploadSubmit);
}

async function handleActionClick(event) {
  const actionTarget = event.target.closest("[data-action]");
  const viewTarget = event.target.closest("[data-view]");
  const kbTabTarget = event.target.closest("[data-kb-tab]");
  const uploadModeTarget = event.target.closest("[data-upload-mode]");
  const clickedInAgentKbSelect = Boolean(event.target.closest?.("#agentKbSelect"));
  if (!clickedInAgentKbSelect && state.agentKbDropdownOpen) {
    closeAgentKbDropdown();
  }
  if (viewTarget) {
    const nextView = viewTarget.dataset.view;
    if (!state.isAdmin && nextView !== "user") return;
    state.view = nextView;
    renderActiveView();
    if (state.view === "agents") {
      await refreshAdmin();
    }
    if (state.view === "knowledge") {
      await refreshKnowledge();
    }
    return;
  }
  if (kbTabTarget) {
    await setKnowledgeTab(kbTabTarget.dataset.kbTab);
    return;
  }
  if (uploadModeTarget) {
    setUploadMode(uploadModeTarget.dataset.uploadMode);
    return;
  }
  if (!actionTarget) return;
  const action = actionTarget.dataset.action;
  const id = actionTarget.dataset.id || "";
  try {
    if (action === "toggle-agent-kb-menu") {
      toggleAgentKbDropdown();
      return;
    }
    if (action === "toggle-agent-kb-option") {
      toggleAgentKbOption(id);
      return;
    }
    if (action === "add-metadata-mapping") {
      addMetadataMappingRow();
      return;
    }
    if (action === "remove-metadata-mapping") {
      actionTarget.closest("tr")?.remove();
      updateMetadataTableEmptyState();
      return;
    }
    if (action === "add-metadata-default") {
      addMetadataDefaultRow();
      return;
    }
    if (action === "remove-metadata-default") {
      actionTarget.closest("tr")?.remove();
      updateMetadataTableEmptyState();
      return;
    }
    if (action === "clear-agent-kb-selection") {
      clearAgentKbSelection();
      return;
    }
    if (action === "save-api") saveApiBase();
    if (action === "logout") logout();
    if (action === "refresh-user-agents") await refreshUserAgents();
    if (action === "select-user-agent") await selectUserAgent(id);
    if (action === "refresh-sessions") await refreshSessions();
    if (action === "select-session") await selectSession(id);
    if (action === "delete-session") await deleteSession(id);
    if (action === "new-session") await createChatSession();
    if (action === "clear-chat-history") await clearChatHistory();
    if (action === "refresh-admin") await refreshAdmin();
    if (action === "refresh-knowledge") await refreshKnowledge();
    if (action === "edit-agent") editAgent(id);
    if (action === "publish-agent") await changeAgentStatus(id, "published");
    if (action === "offline-agent") await changeAgentStatus(id, "offline");
    if (action === "reset-agent-form") resetAgentForm();
    if (action === "reset-kb-form") openKnowledgeBaseEditor();
    if (action === "close-kb-editor") closeKnowledgeBaseEditor();
    if (action === "select-kb") await selectKnowledgeBase(id);
    if (action === "edit-kb") openKnowledgeBaseEditor(id || state.selectedKbId);
    if (action === "archive-kb") await archiveSelectedKnowledgeBase();
    if (action === "restore-kb") await restoreSelectedKnowledgeBase();
    if (action === "delete-kb") await deleteSelectedKnowledgeBase();
    if (action === "kb-prev-page") await changeKnowledgePage(-1);
    if (action === "kb-next-page") await changeKnowledgePage(1);
    if (action === "refresh-documents") await loadSelectedKnowledgeBaseDetail();
    if (action === "refresh-jobs") await loadSelectedKnowledgeBaseDetail();
    if (action === "clear-jobs") await clearJobs();
    if (action === "document-prev-page") await changeDocumentPage(-1);
    if (action === "document-next-page") await changeDocumentPage(1);
    if (action === "job-prev-page") await changeJobPage(-1);
    if (action === "job-next-page") await changeJobPage(1);
    if (action === "open-document") await openDocumentDetail(id);
    if (action === "close-document-drawer") closeDocumentDrawer();
    if (action === "archive-document-detail") await archiveSelectedDocument();
    if (action === "archive-document") await archiveDocument(id);
    if (action === "open-job") await openJobDetail(id);
    if (action === "close-job-drawer") closeJobDrawer();
    if (action === "delete-job") await deleteJob(id);
    if (action === "search-knowledge") await runKnowledgeSearch();
  } catch (error) {
    toast(errorMessage(error), "error");
  }
}

async function handleChange(event) {
  const target = event.target;
  try {
    if (target.matches("#agentKbSelect") || target.matches("[data-agent-kb-id]")) {
      state.selectedAgentKbIds = selectedOptions(elements.agentKbSelect);
    }
    if (target.matches("#includeArchivedInput")) {
      state.includeArchived = target.checked;
      state.knowledgePage = 1;
      await refreshKnowledge({ refreshSelected: false, refreshOptions: false, refreshTabData: true });
    }
    if (target.matches("#documentSourceFilter")) {
      state.documentSourceFilter = target.value;
      state.documentPage = 1;
      await loadSelectedKnowledgeDocuments();
    }
    if (target.matches("#jobStatusFilter")) {
      state.jobStatusFilter = target.value;
      state.jobPage = 1;
      await loadSelectedKnowledgeJobs();
    }
    if (target.matches("#uploadFileInput") || target.matches("#uploadDirectoryInput")) {
      updateUploadStatus();
    }
  } catch (error) {
    toast(errorMessage(error), "error");
  }
}

function handleInput(event) {
  const target = event.target;
  if (target.matches("#agentKbSearchInput")) {
    state.agentKbKeyword = target.value;
    state.agentKbDropdownOpen = true;
    renderKnowledgeOptions();
    focusAgentKbSearch();
  }
  if (target.matches("#kbKeywordInput")) {
    state.kbKeyword = target.value.trim();
    state.knowledgePage = 1;
    scheduleKnowledgeSearch();
  }
  if (target.matches("#documentKeywordInput")) {
    state.documentKeyword = target.value.trim();
    state.documentPage = 1;
    scheduleDocumentSearch();
  }
}

function scheduleKnowledgeSearch() {
  window.clearTimeout(state.kbSearchTimer);
  state.kbSearchTimer = window.setTimeout(() => {
    refreshKnowledge({ refreshSelected: false, refreshOptions: false, refreshTabData: false }).catch((error) => {
      toast(errorMessage(error), "error");
    });
  }, 300);
}

function scheduleDocumentSearch() {
  window.clearTimeout(state.documentSearchTimer);
  state.documentSearchTimer = window.setTimeout(() => {
    loadSelectedKnowledgeDocuments().catch((error) => {
      toast(errorMessage(error), "error");
    });
  }, 250);
}

async function handleKeydown(event) {
  const target = event.target;
  if (event.key === "Escape" && state.agentKbDropdownOpen) {
    closeAgentKbDropdown();
    return;
  }
  if (event.key === "Enter" && target.matches("#searchInput")) {
    event.preventDefault();
    try {
      await runKnowledgeSearch();
    } catch (error) {
      toast(errorMessage(error), "error");
    }
  }
}

async function handleAuthSubmit(event) {
  event.preventDefault();
  const submitter = event.submitter;
  const mode = submitter?.dataset.authMode || "login";
  const email = elements.emailInput.value.trim();
  const password = elements.passwordInput.value;
  if (!email || !password) return;
  try {
    submitter.disabled = true;
    if (mode === "register") {
      const payload = await apiRequest("/api/v1/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      state.userToken = tokenValue(payload.token);
      state.isAdmin = Boolean(payload.is_admin);
    } else {
      const form = new URLSearchParams();
      form.set("username", email);
      form.set("password", password);
      const payload = await apiRequest("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: form,
      });
      state.userToken = tokenValue(payload);
      state.isAdmin = Boolean(payload.is_admin);
    }
    state.userEmail = email;
    localStorage.setItem(STORAGE_KEYS.userToken, state.userToken);
    localStorage.setItem(STORAGE_KEYS.userEmail, state.userEmail);
    localStorage.setItem(STORAGE_KEYS.isAdmin, state.isAdmin ? "1" : "0");
    toast("已登录");
    await bootstrap();
  } catch (error) {
    toast(errorMessage(error), "error");
  } finally {
    submitter.disabled = false;
  }
}

async function bootstrap() {
  renderSession();
  await refreshCurrentUser();
  renderSession();
  await refreshUserAgents();
  await refreshSessions({ quiet: true });
  if (state.view === "agents") {
    await refreshAdmin();
  }
  if (state.view === "knowledge") {
    await refreshKnowledge();
  }
}

async function refreshCurrentUser() {
  if (!state.userToken) return;
  try {
    const me = await apiRequest("/api/v1/auth/me");
    state.isAdmin = Boolean(me.is_admin);
    state.userEmail = me.email || state.userEmail;
    localStorage.setItem(STORAGE_KEYS.isAdmin, state.isAdmin ? "1" : "0");
    localStorage.setItem(STORAGE_KEYS.userEmail, state.userEmail);
  } catch (error) {
    // token 可能失效，忽略并保持当前状态
  }
}

function renderSession() {
  const loggedIn = Boolean(state.userToken);
  elements.authPanel.classList.toggle("hidden", loggedIn);
  elements.consolePanel.classList.toggle("hidden", !loggedIn);
  elements.userIdentity.textContent = state.userEmail ? `当前用户：${state.userEmail}` : "";
  // 普通用户只显示会话页面，隐藏管理员入口
  document.querySelectorAll('[data-view="agents"], [data-view="knowledge"]').forEach((button) => {
    button.classList.toggle("hidden", !state.isAdmin);
  });
  if (!state.isAdmin && state.view !== "user") {
    state.view = "user";
  }
  renderActiveView();
}

function renderActiveView() {
  if (state.view !== "agents") {
    state.agentKbDropdownOpen = false;
    state.agentKbKeyword = "";
  }
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === state.view);
  });
  elements.userView.classList.toggle("hidden", state.view !== "user");
  elements.agentAdminView.classList.toggle("hidden", state.view !== "agents");
  elements.knowledgeAdminView.classList.toggle("hidden", state.view !== "knowledge");
}

function saveApiBase() {
  state.apiBase = elements.apiBaseInput.value.trim().replace(/\/+$/, "") || "http://127.0.0.1:8000";
  elements.apiBaseInput.value = state.apiBase;
  localStorage.setItem(STORAGE_KEYS.apiBase, state.apiBase);
  toast("API 地址已保存");
}

function logout() {
  state.userToken = "";
  state.userEmail = "";
  state.isAdmin = false;
  state.sessions = [];
  state.sessionAgents = {};
  state.activeAgentId = "";
  state.sessionId = "";
  state.sessionToken = "";
  state.messages = [];
  state.knowledgeBases = [];
  state.knowledgeBaseOptions = [];
  state.knowledgePage = 1;
  state.knowledgeTotal = 0;
  state.knowledgeTotalPages = 0;
  state.selectedKbId = "";
  state.selectedKnowledgeBaseDetail = null;
  state.documents = [];
  state.documentPage = 1;
  state.documentTotal = 0;
  state.documentTotalPages = 0;
  state.jobs = [];
  state.jobPage = 1;
  state.jobTotal = 0;
  state.jobTotalPages = 0;
  state.searchResults = [];
  window.clearTimeout(state.kbSearchTimer);
  window.clearTimeout(state.documentSearchTimer);
  localStorage.removeItem(STORAGE_KEYS.userToken);
  localStorage.removeItem(STORAGE_KEYS.userEmail);
  localStorage.removeItem(STORAGE_KEYS.isAdmin);
  localStorage.removeItem(STORAGE_KEYS.activeAgentId);
  localStorage.removeItem(STORAGE_KEYS.sessionAgents);
  renderSession();
  renderUserAgents();
  renderSessions();
  renderMessages();
}

async function refreshUserAgents() {
  if (!state.userToken) return;
  const payload = await apiRequest("/api/v1/agents");
  state.userAgents = payload.items || [];
  if (state.activeAgentId && !state.userAgents.some((agent) => agent.agentId === state.activeAgentId)) {
    state.activeAgentId = "";
  }
  if (!state.activeAgentId && state.userAgents.length > 0) {
    state.activeAgentId = state.userAgents[0].agentId;
  }
  if (state.activeAgentId) {
    localStorage.setItem(STORAGE_KEYS.activeAgentId, state.activeAgentId);
  }
  renderUserAgents();
  renderSessions();
}

function renderUserAgents() {
  if (!state.userAgents.length) {
    elements.agentListMeta.textContent = "";
    elements.userAgentList.innerHTML = empty("暂无已发布 Agent");
    renderActiveAgent();
    return;
  }
  elements.agentListMeta.textContent = `${state.userAgents.length} 个可用`;
  elements.userAgentList.innerHTML = state.userAgents.map((agent) => {
    const active = agent.agentId === state.activeAgentId ? " active" : "";
    const knowledge = agent.knowledge?.enabled ? `知识库 ${agent.knowledge.kbIds?.length || 0}` : "无知识库";
    return `
      <button class="list-item${active}" data-action="select-user-agent" data-id="${escapeAttr(agent.agentId)}">
        <strong>${escapeHtml(agent.name)}</strong>
        <small>${escapeHtml(agent.description || agent.agentCode)}</small>
        <span class="badges">
          <span class="badge">${escapeHtml(agent.modelName || "-")}</span>
          <span class="badge">${escapeHtml(knowledge)}</span>
        </span>
      </button>
    `;
  }).join("");
  renderActiveAgent();
}

async function selectUserAgent(agentId) {
  state.activeAgentId = agentId;
  localStorage.setItem(STORAGE_KEYS.activeAgentId, agentId);
  state.sessionId = "";
  state.sessionToken = "";
  state.messages = [];
  renderUserAgents();
  await restoreAgentSession();
  renderSessions();
  renderMessages();
}

function renderActiveAgent() {
  const agent = activeUserAgent();
  if (!agent) {
    elements.activeAgentTitle.textContent = "选择 Agent";
    elements.activeAgentMeta.textContent = "平台管理员发布后会出现在这里";
    elements.activeSessionMeta.textContent = "";
    return;
  }
  elements.activeAgentTitle.textContent = agent.name;
  const knowledge = agent.knowledge?.enabled
    ? `绑定 ${agent.knowledge.kbIds?.length || 0} 个知识库`
    : "未启用知识库";
  elements.activeAgentMeta.textContent = `${agent.agentCode} · ${agent.modelName} · ${knowledge}`;
  const session = activeSession();
  elements.activeSessionMeta.textContent = session
    ? `当前会话：${session.name || "New Chat"} · ${shortId(session.session_id)}`
    : "未选择会话";
}

async function createChatSession() {
  const agent = activeUserAgent();
  if (!agent) {
    toast("请选择 Agent", "error");
    return;
  }
  const name = encodeURIComponent(`${agent.name} 对话`);
  const payload = await apiRequest(`/api/v1/sessions?name=${name}`, {
    method: "POST",
  });
  applySession(payload, agent.agentId);
  upsertSession(payload);
  state.messages = [];
  persistSessionAgents();
  renderSessions();
  renderMessages();
  renderActiveAgent();
  toast("已创建新会话");
}

async function refreshSessions(options = {}) {
  if (!state.userToken) return;
  try {
    const previousSessionId = state.sessionId;
    const payload = await apiRequest("/api/v1/sessions");
    state.sessions = Array.isArray(payload) ? payload : [];
    pruneSessionAgents();
    if (options.preferSessionId) {
      const preferred = state.sessions.find((session) => session.session_id === options.preferSessionId);
      if (preferred) {
        applySession(preferred, state.activeAgentId);
      }
    } else if (state.sessionId && !state.sessions.some((session) => session.session_id === state.sessionId)) {
      state.sessionId = "";
      state.sessionToken = "";
      state.messages = [];
    }
    if (!state.sessionId) {
      await restoreAgentSession({ quiet: true });
    }
    if (state.sessionId && state.sessionId !== previousSessionId && options.loadHistory !== false) {
      await loadSessionHistory();
    }
    renderSessions();
    renderActiveAgent();
  } catch (error) {
    if (!options.quiet) {
      toast(errorMessage(error), "error");
    }
  }
}

async function selectSession(sessionId) {
  const session = state.sessions.find((item) => item.session_id === sessionId);
  if (!session) return;
  applySession(session, state.activeAgentId);
  persistSessionAgents();
  renderSessions();
  renderActiveAgent();
  await loadSessionHistory();
}

async function deleteSession(sessionId) {
  const session = state.sessions.find((item) => item.session_id === sessionId);
  if (!session) return;
  const confirmed = window.confirm(`确定删除会话「${session.name || shortId(session.session_id)}」吗？`);
  if (!confirmed) return;
  await apiRequest(`/api/v1/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
  state.sessions = state.sessions.filter((item) => item.session_id !== sessionId);
  delete state.sessionAgents[sessionId];
  persistSessionAgents();
  if (state.sessionId === sessionId) {
    state.sessionId = "";
    state.sessionToken = "";
    state.messages = [];
    const nextSession = state.sessions.find((item) => state.sessionAgents[item.session_id] === activeUserAgent()?.agentId);
    if (nextSession) {
      applySession(nextSession, state.activeAgentId);
      await loadSessionHistory();
    }
  }
  renderSessions();
  renderActiveAgent();
  renderMessages();
  toast("会话已删除");
}

async function restoreAgentSession(options = {}) {
  const agent = activeUserAgent();
  if (!agent || !state.sessions.length) return;
  const matched = state.sessions.find((session) => state.sessionAgents[session.session_id] === agent.agentId);
  if (!matched) return;
  applySession(matched, agent.agentId);
  if (!options.quiet) {
    await loadSessionHistory();
  }
}

async function loadSessionHistory() {
  if (!state.sessionId) {
    state.messages = [];
    renderMessages();
    return;
  }
  try {
    const payload = await apiRequest(`/api/v1/sessions/${encodeURIComponent(state.sessionId)}/history`);
    state.messages = Array.isArray(payload)
      ? payload.map(normalizeHistoryMessage).filter(Boolean)
      : [];
    renderMessages();
  } catch (error) {
    toast(errorMessage(error), "error");
  }
}

async function clearChatHistory() {
  if (!state.sessionId) {
    toast("请先选择会话", "error");
    return;
  }
  const confirmed = window.confirm("确定清空当前会话的聊天记录吗？此操作不可恢复。");
  if (!confirmed) return;
  await apiRequest(`/api/v1/sessions/${encodeURIComponent(state.sessionId)}/history`, {
    method: "DELETE",
  });
  state.messages = [];
  renderMessages();
  toast("聊天记录已清空");
}

function applySession(session, agentId) {
  state.sessionId = session.session_id || "";
  state.sessionToken = tokenValue(session.token);
  if (state.sessionId && agentId) {
    state.sessionAgents[state.sessionId] = agentId;
  }
}

function upsertSession(session) {
  const existingIndex = state.sessions.findIndex((item) => item.session_id === session.session_id);
  if (existingIndex >= 0) {
    state.sessions.splice(existingIndex, 1, session);
  } else {
    state.sessions.unshift(session);
  }
}

function pruneSessionAgents() {
  const validIds = new Set(state.sessions.map((session) => session.session_id));
  for (const sessionId of Object.keys(state.sessionAgents)) {
    if (!validIds.has(sessionId)) {
      delete state.sessionAgents[sessionId];
    }
  }
  persistSessionAgents();
}

function persistSessionAgents() {
  localStorage.setItem(STORAGE_KEYS.sessionAgents, JSON.stringify(state.sessionAgents));
}

async function handleChatSubmit(event) {
  event.preventDefault();
  if (state.streaming) return;
  const agent = activeUserAgent();
  const content = elements.chatInput.value.trim();
  if (!agent) {
    toast("请选择 Agent", "error");
    return;
  }
  if (!content) return;
  if (!state.sessionToken) {
    await createChatSession();
  }
  if (!state.sessionToken) return;
  elements.chatInput.value = "";
  state.messages.push({ role: "user", content });
  state.messages.push({ role: "assistant", content: "" });
  renderMessages();
  await streamAgentResponse(agent.agentId, content);
}

async function streamAgentResponse(agentId, content) {
  state.streaming = true;
  const assistantMessage = state.messages[state.messages.length - 1];
  try {
    const response = await fetch(`${state.apiBase}/api/v1/agents/${encodeURIComponent(agentId)}/chat/stream`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${state.sessionToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        messages: [{ role: "user", content }],
      }),
    });
    if (!response.ok || !response.body) {
      const text = await response.text();
      throw new Error(apiErrorMessage(parseJson(text), response.status));
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      assistantMessage.content += decoder.decode(value, { stream: true });
      renderMessages();
    }
  } catch (error) {
    assistantMessage.content += `\n${errorMessage(error)}`;
    renderMessages();
  } finally {
    state.streaming = false;
  }
}

function activeUserAgent() {
  return state.userAgents.find((agent) => agent.agentId === state.activeAgentId) || null;
}

function activeSession() {
  return state.sessions.find((session) => session.session_id === state.sessionId) || null;
}

function renderSessions() {
  const agent = activeUserAgent();
  if (!agent) {
    elements.userSessionList.innerHTML = empty("选择 Agent 后显示会话");
    return;
  }
  const visibleSessions = state.sessions.filter((session) => {
    const mappedAgentId = state.sessionAgents[session.session_id];
    return !mappedAgentId || mappedAgentId === agent.agentId;
  });
  if (!visibleSessions.length) {
    elements.userSessionList.innerHTML = empty("暂无会话");
    return;
  }
  elements.userSessionList.innerHTML = visibleSessions.map((session) => {
    const active = session.session_id === state.sessionId ? " active" : "";
    const mappedAgentId = state.sessionAgents[session.session_id];
    const mapped = mappedAgentId ? "当前 Agent" : "未绑定";
    return `
      <article class="list-item session-item${active}">
        <button class="session-item__main" data-action="select-session" data-id="${escapeAttr(session.session_id)}">
          <strong>${escapeHtml(session.name || "New Chat")}</strong>
          <small>${escapeHtml(shortId(session.session_id))}</small>
          <span class="badges">
            <span class="badge">${escapeHtml(mapped)}</span>
          </span>
        </button>
        <button class="icon-button small-button danger-action" data-action="delete-session" data-id="${escapeAttr(session.session_id)}" title="删除会话" aria-label="删除会话">
          <span aria-hidden="true">×</span>
        </button>
      </article>
    `;
  }).join("");
}

function normalizeHistoryMessage(message) {
  if (!message || typeof message !== "object") return null;
  const role = message.role === "ai" ? "assistant" : message.role;
  if (role !== "user" && role !== "assistant") return null;
  return {
    role,
    content: role === "user" ? stripInjectedKnowledgeContext(message.content) : String(message.content || ""),
  };
}

function stripInjectedKnowledgeContext(content) {
  const text = String(content || "");
  const marker = "[用户问题]\n";
  const index = text.lastIndexOf(marker);
  if (index < 0) return text;
  return text.slice(index + marker.length).trim();
}

function shortId(value) {
  const text = String(value || "");
  if (!text) return "-";
  return text.length > 8 ? `${text.slice(0, 8)}...` : text;
}

function renderMessages() {
  if (!state.messages.length) {
    elements.messageList.innerHTML = empty(state.sessionId ? "当前会话暂无消息" : "创建会话后开始对话");
    return;
  }
  elements.messageList.innerHTML = state.messages.map((message) => `
    <div class="message ${escapeAttr(message.role)}">
      <span class="role">${message.role === "user" ? "我" : "Agent"}</span>
      <div class="bubble">${escapeHtml(message.content || (state.streaming ? "..." : ""))}</div>
    </div>
  `).join("");
  elements.messageList.scrollTop = elements.messageList.scrollHeight;
}

async function refreshAdmin() {
  await Promise.allSettled([refreshPlatformAgents(), refreshKnowledge()]);
}

async function refreshPlatformAgents() {
  try {
    const payload = await apiRequest("/api/v1/admin/platform/agent-catalog?includeOffline=true");
    state.platformAgents = payload.items || [];
    elements.agentAdminStatus.textContent = `${state.platformAgents.length} 个平台 Agent`;
  } catch (error) {
    state.platformAgents = [];
    elements.agentAdminStatus.textContent = errorMessage(error);
  }
  renderPlatformAgents();
}

function renderPlatformAgents() {
  if (!state.platformAgents.length) {
    elements.platformAgentList.innerHTML = empty("暂无平台 Agent");
    return;
  }
  elements.platformAgentList.innerHTML = state.platformAgents.map((agent) => {
    const statusClass = agent.status === "published" ? "" : agent.status === "offline" ? " danger" : " warn";
    const knowledge = agent.knowledge?.enabled ? `KB ${agent.knowledge.kbIds?.length || 0}` : "no KB";
    return `
      <article class="data-row">
        <div class="data-main">
          <strong>${escapeHtml(agent.name)} <span class="muted">${escapeHtml(agent.agentCode)}</span></strong>
          <small>${escapeHtml(agent.description || agent.roleDescription || "")}</small>
          <span class="badges">
            <span class="badge${statusClass}">${escapeHtml(agent.status)}</span>
            <span class="badge">${escapeHtml(agent.modelName)}</span>
            <span class="badge">${escapeHtml(knowledge)}</span>
          </span>
        </div>
        <div class="row-actions">
          <button class="secondary-button" data-action="edit-agent" data-id="${escapeAttr(agent.agentId)}">编辑</button>
          <button class="secondary-button" data-action="publish-agent" data-id="${escapeAttr(agent.agentId)}">发布</button>
          <button class="secondary-button" data-action="offline-agent" data-id="${escapeAttr(agent.agentId)}">下线</button>
        </div>
      </article>
    `;
  }).join("");
}

function editAgent(agentId) {
  const agent = state.platformAgents.find((item) => item.agentId === agentId);
  if (!agent) return;
  elements.agentIdInput.value = agent.agentId;
  elements.agentCodeInput.value = agent.agentCode || "";
  elements.agentNameInput.value = agent.name || "";
  elements.agentDescriptionInput.value = agent.description || "";
  elements.agentModelInput.value = agent.modelName || "deepseek-chat";
  elements.agentRoleInput.value = agent.roleDescription || "";
  elements.featureWebSearch.checked = Boolean(agent.features?.web_search);
  elements.featureCode.checked = Boolean(agent.features?.code_interpreter);
  elements.featureMemory.checked = Boolean(agent.features?.memory_tools);
  elements.featureEmail.checked = Boolean(agent.features?.email_assistant);
  elements.knowledgeEnabledInput.checked = Boolean(agent.knowledge?.enabled);
  elements.agentTopKInput.value = String(agent.knowledge?.topK || 5);
  elements.agentScoreInput.value = String(agent.knowledge?.scoreThreshold || 0);
  renderKnowledgeOptions(validAgentKbIds(agent.knowledge?.kbIds || []));
}

function resetAgentForm() {
  elements.agentForm.reset();
  elements.agentIdInput.value = "";
  elements.agentModelInput.value = "deepseek-chat";
  elements.agentTopKInput.value = "5";
  elements.agentScoreInput.value = "0";
  renderKnowledgeOptions([]);
}

async function handleAgentSubmit(event) {
  event.preventDefault();
  const agentId = elements.agentIdInput.value;
  const knowledgeEnabled = elements.knowledgeEnabledInput.checked;
  const kbIds = selectedOptions(elements.agentKbSelect);
  if (knowledgeEnabled && kbIds.length === 0) {
    toast("启用知识库时至少绑定一个知识库", "error");
    return;
  }
  const payload = {
    agentCode: elements.agentCodeInput.value.trim(),
    name: elements.agentNameInput.value.trim(),
    description: elements.agentDescriptionInput.value.trim() || null,
    modelName: elements.agentModelInput.value.trim(),
    roleDescription: elements.agentRoleInput.value.trim(),
    features: {
      web_search: elements.featureWebSearch.checked,
      code_interpreter: elements.featureCode.checked,
      memory_tools: elements.featureMemory.checked,
      email_assistant: elements.featureEmail.checked,
    },
    knowledge: {
      enabled: knowledgeEnabled,
      kbIds,
      topK: numberValue(elements.agentTopKInput.value, 5),
      scoreThreshold: numberValue(elements.agentScoreInput.value, 0),
    },
    config: {},
  };
  const path = agentId
    ? `/api/v1/admin/platform/agent-catalog/${encodeURIComponent(agentId)}`
    : "/api/v1/admin/platform/agent-catalog";
  await apiRequest(path, {
    method: agentId ? "PUT" : "POST",
    body: JSON.stringify(payload),
  });
  toast("Agent 已保存");
  resetAgentForm();
  await refreshPlatformAgents();
  await refreshUserAgents();
}

async function changeAgentStatus(agentId, status) {
  await apiRequest(`/api/v1/admin/platform/agent-catalog/${encodeURIComponent(agentId)}/status`, {
    method: "PUT",
    body: JSON.stringify({ status }),
  });
  toast(status === "published" ? "Agent 已发布" : "Agent 已下线");
  await refreshPlatformAgents();
  await refreshUserAgents();
}

async function refreshKnowledge(options = {}) {
  try {
    state.knowledgeError = "";
    await refreshKnowledgeBasePage();
    const shouldRefreshOptions = options.refreshOptions ?? state.view === "agents";
    if (shouldRefreshOptions) {
      try {
        await refreshKnowledgeOptions();
      } catch (error) {
        console.warn("knowledge options refresh failed", error);
        renderKnowledgeOptions(selectedOptions(elements.agentKbSelect));
      }
    } else {
      renderKnowledgeOptions(selectedOptions(elements.agentKbSelect));
    }
    if (state.selectedKbId) {
      if (options.refreshSelected !== false) {
        await loadSelectedKnowledgeBaseDetail({ loadTabData: options.refreshTabData !== false });
      } else if (options.refreshTabData !== false) {
        await loadSelectedKnowledgeBaseTabData(state.kbTab);
      } else {
        renderKnowledgeDetail();
      }
    } else {
      state.selectedKnowledgeBaseDetail = null;
      state.documents = [];
      state.jobs = [];
      renderKnowledgeDetail();
    }
  } catch (error) {
    state.knowledgeBases = [];
    state.knowledgeBaseOptions = [];
    state.knowledgeTotal = 0;
    state.knowledgeTotalPages = 0;
    state.selectedKbId = "";
    state.selectedKnowledgeBaseDetail = null;
    state.documents = [];
    state.documentTotal = 0;
    state.documentTotalPages = 0;
    state.jobs = [];
    state.jobTotal = 0;
    state.jobTotalPages = 0;
    state.knowledgeError = errorMessage(error);
    renderKnowledgeBases();
    renderKnowledgeOptions([]);
    renderKnowledgeDetail();
  }
}

async function refreshKnowledgeBasePage() {
  const includeArchived = state.includeArchived ? "true" : "false";
  const params = new URLSearchParams({
    includeArchived,
    keyword: state.kbKeyword || "",
    page: String(state.knowledgePage),
    pageSize: String(state.knowledgePageSize),
  });
  const payload = await apiRequest(`/api/v1/admin/platform/knowledge-bases?${params.toString()}`);
  state.knowledgeBases = payload.items || [];
  state.knowledgeTotal = numberValue(payload.total, state.knowledgeBases.length);
  state.knowledgePage = numberValue(payload.page, state.knowledgePage) || 1;
  state.knowledgePageSize = numberValue(payload.pageSize, state.knowledgePageSize) || state.knowledgePageSize;
  state.knowledgeTotalPages = numberValue(payload.totalPages, 0);
  if (!state.knowledgeTotalPages && state.knowledgeTotal > 0 && state.knowledgePageSize > 0) {
    state.knowledgeTotalPages = Math.max(1, Math.ceil(state.knowledgeTotal / state.knowledgePageSize));
  }
  if (state.knowledgeTotalPages && state.knowledgePage > state.knowledgeTotalPages) {
    state.knowledgePage = state.knowledgeTotalPages;
  }
  const selectedInPage = state.knowledgeBases.find((kb) => kb.id === state.selectedKbId);
  if (!state.selectedKbId && state.knowledgeBases.length > 0) {
    state.selectedKbId = state.knowledgeBases[0].id;
    state.selectedKnowledgeBaseDetail = state.knowledgeBases[0];
  } else if (selectedInPage) {
    state.selectedKnowledgeBaseDetail = selectedInPage;
  } else if (state.kbKeyword && state.selectedKbId) {
    state.selectedKbId = "";
    state.selectedKnowledgeBaseDetail = null;
    state.documents = [];
    state.jobs = [];
  } else if (!state.includeArchived && state.selectedKnowledgeBaseDetail?.status === "archived") {
    state.selectedKbId = "";
    state.selectedKnowledgeBaseDetail = null;
    state.documents = [];
    state.jobs = [];
  }
  renderKnowledgeBases();
}

async function refreshKnowledgeOptions() {
  const payload = await apiRequest("/api/v1/admin/platform/knowledge-bases?includeArchived=false");
  state.knowledgeBaseOptions = payload.items || [];
  renderKnowledgeOptions(selectedOptions(elements.agentKbSelect));
}

function renderKnowledgeBases() {
  const filteredBases = state.knowledgeBases;
  const totalLabel = state.knowledgeTotal ? `${state.knowledgeTotal} 个知识库` : "暂无知识库";
  const pageLabel = state.knowledgeTotalPages ? `第 ${state.knowledgePage}/${state.knowledgeTotalPages} 页` : "第 1/1 页";
  elements.knowledgeStatus.textContent = state.knowledgeError
    || `${pageLabel} · 当前页 ${filteredBases.length} 条 · 总计 ${totalLabel}`;
  updatePager(elements.knowledgePagerInfo, "kb", state.knowledgePage, state.knowledgeTotalPages, state.knowledgeTotal);
  if (!state.knowledgeBases.length) {
    elements.knowledgeBaseList.innerHTML = empty("暂无知识库");
    renderKnowledgeDetail();
    return;
  }
  if (!filteredBases.length) {
    elements.knowledgeBaseList.innerHTML = empty("没有匹配的知识库");
    renderKnowledgeDetail();
    return;
  }
  elements.knowledgeBaseList.innerHTML = filteredBases.map((kb) => {
    const active = kb.id === state.selectedKbId ? " selected" : "";
    const statusClass = knowledgeStatusClass(kb.status);
    return `
      <button class="kb-item${active}" data-action="select-kb" data-id="${escapeAttr(kb.id)}">
        <span class="kb-item__signal" data-status="${escapeAttr(kb.status)}"></span>
        <span class="kb-item__body">
          <span class="kb-item__top">
            <strong>${escapeHtml(kb.name)}</strong>
            <span class="badge${statusClass}">${escapeHtml(knowledgeStatusLabel(kb.status))}</span>
          </span>
          <span class="kb-item__desc">${escapeHtml(kb.description || "暂无说明")}</span>
          <span class="kb-item__meta">
            <span>${escapeHtml(namespaceLabel(kb.namespace))}</span>
            <span>${escapeHtml(kb.documentCount || 0)} 文档</span>
            <span>${escapeHtml(kb.chunkCount || 0)} chunks</span>
          </span>
        </span>
      </button>
    `;
  }).join("");
  renderKnowledgeDetail();
}

function renderKnowledgeOptions(selectedIds = state.selectedAgentKbIds) {
  const selectedValues = setSelectedAgentKbIds(selectedIds);
  const selected = new Set(selectedValues);
  const options = agentKnowledgeOptions();
  const selectableOptions = options.filter((kb) => kb.status === "active");
  const selectedItems = selectedValues
    .map((kbId) => findKnowledgeBaseById(kbId))
    .filter(Boolean);
  const keyword = state.agentKbKeyword.trim().toLowerCase();
  const filteredOptions = selectableOptions.filter((kb) => {
    const searchable = [
      kb.name,
      kb.namespace,
      namespaceLabel(kb.namespace),
      kb.description,
    ].join(" ").toLowerCase();
    return !keyword || searchable.includes(keyword);
  });
  const isOpen = state.agentKbDropdownOpen && selectableOptions.length > 0;
  const controlDisabled = selectableOptions.length === 0 ? " disabled" : "";
  const selectedTags = selectedItems.length
    ? selectedItems.slice(0, 2).map((kb) => `
        <span class="agent-kb-tag" title="${escapeAttr(kb.name)}">${escapeHtml(kb.name)}</span>
      `).join("")
    : `<span class="agent-kb-placeholder">选择知识库</span>`;
  const overflowTag = selectedItems.length > 2
    ? `<span class="agent-kb-tag agent-kb-tag--more">+${selectedItems.length - 2}</span>`
    : "";
  const hiddenInputs = selectedValues.map((kbId) => `
    <input type="hidden" data-agent-kb-id value="${escapeAttr(kbId)}" />
  `).join("");
  const optionsHtml = filteredOptions.length
    ? filteredOptions.map((kb) => {
      const isSelected = selected.has(kb.id);
      return `
        <button
          type="button"
          class="agent-kb-select__option${isSelected ? " selected" : ""}"
          role="option"
          aria-selected="${isSelected ? "true" : "false"}"
          data-action="toggle-agent-kb-option"
          data-id="${escapeAttr(kb.id)}"
        >
          <span class="agent-kb-select__check" aria-hidden="true">${isSelected ? "✓" : ""}</span>
          <span class="agent-kb-select__option-body">
            <strong>${escapeHtml(kb.name)}</strong>
            <small>${escapeHtml(namespaceLabel(kb.namespace))} · ${escapeHtml(kb.documentCount || 0)} 文档 · ${escapeHtml(kb.chunkCount || 0)} chunks</small>
          </span>
        </button>
      `;
    }).join("")
    : `<div class="agent-kb-select__empty">${escapeHtml(keyword ? "没有匹配的知识库" : "暂无可绑定知识库")}</div>`;

  elements.agentKbSelect.classList.toggle("open", isOpen);
  elements.agentKbSelect.innerHTML = `
    <button
      type="button"
      class="agent-kb-select__control"
      data-action="toggle-agent-kb-menu"
      aria-haspopup="listbox"
      aria-expanded="${isOpen ? "true" : "false"}"
      ${controlDisabled}
    >
      <span class="agent-kb-select__value">${selectedTags}${overflowTag}</span>
      <span class="agent-kb-select__arrow" aria-hidden="true">⌄</span>
    </button>
    <div class="agent-kb-select__hidden" hidden>${hiddenInputs}</div>
    ${isOpen ? `
      <div class="agent-kb-select__menu">
        <div class="agent-kb-select__search">
          <input
            id="agentKbSearchInput"
            type="search"
            placeholder="搜索知识库"
            value="${escapeAttr(state.agentKbKeyword)}"
            autocomplete="off"
          />
        </div>
        <div class="agent-kb-select__options" role="listbox" aria-multiselectable="true">
          ${optionsHtml}
        </div>
        <div class="agent-kb-select__menu-foot">
          <span>已选 ${selectedValues.length} 个</span>
          <button type="button" class="link-button" data-action="clear-agent-kb-selection">清空</button>
        </div>
      </div>
    ` : ""}
  `;
}

function agentKnowledgeOptions() {
  const merged = new Map();
  [...state.knowledgeBaseOptions, ...state.knowledgeBases].forEach((kb) => {
    if (kb?.id) merged.set(kb.id, kb);
  });
  return Array.from(merged.values());
}

function validAgentKbIds(kbIds) {
  const known = agentKnowledgeOptions();
  if (!known.length) return kbIds || [];
  const knownIds = new Set(known.map((kb) => kb.id));
  return (kbIds || []).filter((kbId) => knownIds.has(kbId));
}

function setSelectedAgentKbIds(selectedIds) {
  state.selectedAgentKbIds = Array.from(new Set(
    (selectedIds || []).map((value) => String(value || "").trim()).filter(Boolean),
  ));
  return state.selectedAgentKbIds;
}

function toggleAgentKbDropdown() {
  const opening = !state.agentKbDropdownOpen;
  state.agentKbDropdownOpen = opening;
  if (opening) {
    state.agentKbKeyword = "";
  }
  renderKnowledgeOptions();
  if (opening) focusAgentKbSearch();
}

function closeAgentKbDropdown() {
  state.agentKbDropdownOpen = false;
  state.agentKbKeyword = "";
  renderKnowledgeOptions();
}

function toggleAgentKbOption(kbId) {
  if (!kbId) return;
  const selected = new Set(state.selectedAgentKbIds);
  if (selected.has(kbId)) {
    selected.delete(kbId);
  } else {
    selected.add(kbId);
  }
  state.selectedAgentKbIds = Array.from(selected);
  renderKnowledgeOptions();
  focusAgentKbSearch();
}

function clearAgentKbSelection() {
  state.selectedAgentKbIds = [];
  renderKnowledgeOptions();
  focusAgentKbSearch();
}

function focusAgentKbSearch() {
  window.requestAnimationFrame(() => {
    const input = document.querySelector("#agentKbSearchInput");
    if (!input) return;
    input.focus();
    const position = input.value.length;
    input.setSelectionRange(position, position);
  });
}

async function selectKnowledgeBase(kbId) {
  state.selectedKbId = kbId;
  state.selectedKnowledgeBaseDetail = findKnowledgeBaseById(kbId) || null;
  state.searchResults = [];
  state.documents = [];
  state.jobs = [];
  state.documentPage = 1;
  state.jobPage = 1;
  state.documentTotal = 0;
  state.documentTotalPages = 0;
  state.jobTotal = 0;
  state.jobTotalPages = 0;
  window.clearTimeout(state.documentSearchTimer);
  renderKnowledgeBases();
  renderKnowledgeDetail();
  await loadSelectedKnowledgeBaseDetail();
}

function editKnowledgeBase(kbId) {
  openKnowledgeBaseEditor(kbId);
}

function openKnowledgeBaseEditor(kbId = "") {
  const kb = findKnowledgeBaseById(kbId);
  elements.kbForm.reset();
  elements.kbIdInput.value = kb?.id || "";
  elements.kbNamespaceInput.value = kb?.namespace || "default";
  elements.kbNamespaceInput.disabled = Boolean(kb?.id);
  elements.kbNameInput.value = kb?.name || "";
  elements.kbDescriptionInput.value = kb?.description || "";
  elements.kbStrategyInput.value = kb?.searchPolicyJson?.strategy || "";
  elements.kbWebFallbackInput.checked = Boolean(kb?.searchPolicyJson?.allowWebFallback);
  elements.kbEditorTitle.textContent = kb ? "编辑知识库" : "新建知识库";
  elements.kbEditorDrawer.classList.remove("hidden");
  window.setTimeout(() => elements.kbNameInput.focus(), 0);
}

function closeKnowledgeBaseEditor() {
  elements.kbEditorDrawer.classList.add("hidden");
  elements.kbNamespaceInput.disabled = false;
}

function metadataExtractionConfig(kb) {
  return {
    enabled: kb?.metadataExtractionJson?.enabled !== false,
    schema: kb?.metadataExtractionJson?.schema || { name: "generic", version: "1" },
    mappings: kb?.metadataExtractionJson?.mappings || {},
    defaults: kb?.metadataExtractionJson?.defaults || {},
    keepUnmappedInDomain: kb?.metadataExtractionJson?.keepUnmappedInDomain !== false,
    format: kb?.metadataExtractionJson?.format || "markdown_fields",
    stripExtractedBlock: kb?.metadataExtractionJson?.stripExtractedBlock !== false,
    maxLines: numberValue(kb?.metadataExtractionJson?.maxLines, 100),
  };
}

function metadataMappingRows(mappings) {
  return Object.entries(mappings || {}).map(([sourceKey, mapping]) => {
    const config = typeof mapping === "string" ? { path: mapping } : (mapping || {});
    return {
      sourceKey,
      path: config.path || "",
      type: config.type || "auto",
    };
  });
}

function metadataDefaultRows(defaults) {
  return Object.entries(defaults || {}).map(([path, value]) => ({
    path,
    value: JSON.stringify(value),
  }));
}

function renderMetadataMappingRows(mappings) {
  const rows = metadataMappingRows(mappings);
  elements.metadataMappingsTable.innerHTML = rows.map((row) => `
    <tr>
      <td><input data-metadata-field="sourceKey" value="${escapeAttr(row.sourceKey)}" placeholder="例如 区域" /></td>
      <td><input data-metadata-field="path" value="${escapeAttr(row.path)}" placeholder="例如 common.region" /></td>
      <td>
        <select data-metadata-field="type">
          <option value="auto"${row.type === "auto" ? " selected" : ""}>自动</option>
          <option value="string"${row.type === "string" ? " selected" : ""}>文本</option>
          <option value="list"${row.type === "list" ? " selected" : ""}>列表</option>
          <option value="boolean"${row.type === "boolean" ? " selected" : ""}>布尔</option>
        </select>
      </td>
      <td class="metadata-row-action">
        <button type="button" class="icon-button danger-action" data-action="remove-metadata-mapping" title="删除字段" aria-label="删除字段">×</button>
      </td>
    </tr>
  `).join("");
  updateMetadataTableEmptyState();
}

function renderMetadataDefaultRows(defaults) {
  const rows = metadataDefaultRows(defaults);
  elements.metadataDefaultsTable.innerHTML = rows.map((row) => `
    <tr>
      <td><input data-metadata-default="path" value="${escapeAttr(row.path)}" placeholder="例如 common.documentType" /></td>
      <td><input data-metadata-default="value" value="${escapeAttr(row.value)}" placeholder='例如 "policy" 或 []' /></td>
      <td class="metadata-row-action">
        <button type="button" class="icon-button danger-action" data-action="remove-metadata-default" title="删除默认值" aria-label="删除默认值">×</button>
      </td>
    </tr>
  `).join("");
  updateMetadataTableEmptyState();
}

function addMetadataMappingRow() {
  const row = document.createElement("tr");
  row.innerHTML = `
    <td><input data-metadata-field="sourceKey" placeholder="例如 区域" /></td>
    <td><input data-metadata-field="path" placeholder="例如 common.region" /></td>
    <td>
      <select data-metadata-field="type">
        <option value="auto">自动</option>
        <option value="string">文本</option>
        <option value="list">列表</option>
        <option value="boolean">布尔</option>
      </select>
    </td>
    <td class="metadata-row-action">
      <button type="button" class="icon-button danger-action" data-action="remove-metadata-mapping" title="删除字段" aria-label="删除字段">×</button>
    </td>
  `;
  elements.metadataMappingsTable.append(row);
  updateMetadataTableEmptyState();
  row.querySelector("[data-metadata-field='sourceKey']")?.focus();
}

function addMetadataDefaultRow() {
  const row = document.createElement("tr");
  row.innerHTML = `
    <td><input data-metadata-default="path" placeholder="例如 common.documentType" /></td>
    <td><input data-metadata-default="value" placeholder='例如 "policy" 或 []' /></td>
    <td class="metadata-row-action">
      <button type="button" class="icon-button danger-action" data-action="remove-metadata-default" title="删除默认值" aria-label="删除默认值">×</button>
    </td>
  `;
  elements.metadataDefaultsTable.append(row);
  updateMetadataTableEmptyState();
  row.querySelector("[data-metadata-default='path']")?.focus();
}

function updateMetadataTableEmptyState() {
  elements.metadataMappingsEmpty.classList.toggle("hidden", Boolean(elements.metadataMappingsTable.rows.length));
  elements.metadataDefaultsEmpty.classList.toggle("hidden", Boolean(elements.metadataDefaultsTable.rows.length));
}

function readMetadataMappings() {
  const mappings = {};
  for (const row of Array.from(elements.metadataMappingsTable.rows)) {
    const sourceKey = row.querySelector("[data-metadata-field='sourceKey']")?.value.trim();
    const path = row.querySelector("[data-metadata-field='path']")?.value.trim();
    const type = row.querySelector("[data-metadata-field='type']")?.value || "auto";
    if (!sourceKey && !path) continue;
    if (!sourceKey || !path) throw new Error("字段映射的原始字段名和目标路径不能为空");
    mappings[sourceKey] = type === "auto" ? path : { path, type };
  }
  return mappings;
}

function readMetadataDefaults() {
  const defaults = {};
  for (const row of Array.from(elements.metadataDefaultsTable.rows)) {
    const path = row.querySelector("[data-metadata-default='path']")?.value.trim();
    const rawValue = row.querySelector("[data-metadata-default='value']")?.value.trim();
    if (!path && !rawValue) continue;
    if (!path || !rawValue) throw new Error("默认字段的目标路径和默认值不能为空");
    try {
      defaults[path] = JSON.parse(rawValue);
    } catch (error) {
      throw new Error(`默认值不是有效 JSON：${error.message}`);
    }
  }
  return defaults;
}

function renderMetadataExtraction() {
  const kb = state.selectedKnowledgeBaseDetail || selectedKnowledgeBase();
  if (!kb || !elements.metadataExtractionForm) return;
  const config = metadataExtractionConfig(kb);
  elements.metadataExtractionEnabledInput.checked = config.enabled;
  elements.metadataExtractionSchemaNameInput.value = config.schema.name || "generic";
  elements.metadataExtractionSchemaVersionInput.value = config.schema.version || "1";
  renderMetadataMappingRows(config.mappings);
  renderMetadataDefaultRows(config.defaults);
  elements.metadataExtractionFormatInput.value = config.format;
  elements.metadataExtractionMaxLinesInput.value = config.maxLines;
  elements.metadataExtractionStripInput.checked = config.stripExtractedBlock;
  elements.metadataExtractionKeepUnmappedInput.checked = config.keepUnmappedInDomain;
  elements.metadataExtractionStatus.textContent = config.enabled
    ? `当前格式：${config.format === "markdown_fields" ? "Markdown 字段头" : config.format === "yaml_front_matter" ? "YAML front matter" : "不提取"}`
    : "元数据提取已关闭，新上传文档将保留完整正文。";
}

async function handleMetadataExtractionSubmit(event) {
  event.preventDefault();
  const kb = selectedKnowledgeBase();
  if (!kb) return;
  let mappings;
  let defaults;
  try {
    mappings = readMetadataMappings();
    defaults = readMetadataDefaults();
  } catch (error) {
    toast(`字段配置格式错误：${error.message}`, "error");
    return;
  }
  const payload = {
    metadataExtractionJson: {
      enabled: elements.metadataExtractionEnabledInput.checked,
      schema: {
        name: elements.metadataExtractionSchemaNameInput.value.trim() || "generic",
        version: elements.metadataExtractionSchemaVersionInput.value.trim() || "1",
      },
      mappings,
      defaults,
      keepUnmappedInDomain: elements.metadataExtractionKeepUnmappedInput.checked,
      format: elements.metadataExtractionFormatInput.value,
      stripExtractedBlock: elements.metadataExtractionStripInput.checked,
      maxLines: numberValue(elements.metadataExtractionMaxLinesInput.value, 100),
    },
  };
  const saved = await apiRequest(`/api/v1/admin/platform/knowledge-bases/${encodeURIComponent(kb.id)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  state.selectedKnowledgeBaseDetail = saved;
  state.knowledgeBases = state.knowledgeBases.map((item) => item.id === saved.id ? saved : item);
  renderKnowledgeBases();
  toast("元数据提取配置已保存");
}

async function handleKbSubmit(event) {
  event.preventDefault();
  const kbId = elements.kbIdInput.value;
  const strategy = elements.kbStrategyInput.value.trim();
  const allowWebFallback = elements.kbWebFallbackInput.checked;
  const searchPolicy = {};
  if (strategy) searchPolicy.strategy = strategy;
  if (allowWebFallback) searchPolicy.allowWebFallback = true;
  const payload = {
    namespace: elements.kbNamespaceInput.value,
    name: elements.kbNameInput.value.trim(),
    description: elements.kbDescriptionInput.value.trim() || null,
    searchPolicyJson: searchPolicy,
  };
  const path = kbId
    ? `/api/v1/admin/platform/knowledge-bases/${encodeURIComponent(kbId)}`
    : "/api/v1/admin/platform/knowledge-bases";
  const saved = await apiRequest(path, {
    method: kbId ? "PUT" : "POST",
    body: JSON.stringify(payload),
  });
  elements.kbForm.reset();
  elements.kbIdInput.value = "";
  closeKnowledgeBaseEditor();
  if (saved?.id) {
    state.selectedKbId = saved.id;
    state.selectedKnowledgeBaseDetail = saved;
  }
  toast("知识库已保存");
  await refreshKnowledge();
}

async function loadSelectedKnowledgeBaseDetail(options = {}) {
  const kb = selectedKnowledgeBase();
  const requestedKbId = kb?.id || "";
  if (!kb) {
    state.selectedKnowledgeBaseDetail = null;
    state.documents = [];
    state.jobs = [];
    renderKnowledgeDetail();
    return;
  }
  const tabLoader = options.loadTabData === false ? Promise.resolve() : loadSelectedKnowledgeBaseTabData(state.kbTab);
  const [detailResult, tabResult] = await Promise.allSettled([
    apiRequest(`/api/v1/admin/platform/knowledge-bases/${encodeURIComponent(kb.id)}`),
    tabLoader,
  ]);
  // 竞态保护：用户已切换到其他知识库，丢弃过期响应
  if (state.selectedKbId !== requestedKbId) return;
  if (detailResult.status === "fulfilled") {
    state.selectedKnowledgeBaseDetail = detailResult.value;
  } else if (!state.selectedKnowledgeBaseDetail || state.selectedKnowledgeBaseDetail.id !== kb.id) {
    state.selectedKnowledgeBaseDetail = kb;
  }
  if (tabResult.status === "rejected") {
    const tabError = errorMessage(tabResult.reason);
    if (state.kbTab === "documents") {
      elements.documentList.innerHTML = empty(tabError);
    }
    if (state.kbTab === "jobs") {
      elements.jobList.innerHTML = empty(tabError);
    }
  }
  renderKnowledgeDetail();
}

async function loadSelectedKnowledgeBaseTabData(targetTab = "") {
  if (targetTab === "documents" || (!targetTab && state.kbTab === "documents")) {
    await loadSelectedKnowledgeDocuments();
  } else if (targetTab === "jobs" || (!targetTab && state.kbTab === "jobs")) {
    await loadSelectedKnowledgeJobs();
  } else {
    renderKnowledgeDetail();
  }
}

async function loadSelectedKnowledgeDocuments() {
  const kb = selectedKnowledgeBase();
  if (!kb) {
    state.documents = [];
    state.documentTotal = 0;
    state.documentTotalPages = 0;
    renderKnowledgeDetail();
    return;
  }
  const requestedKbId = kb.id;
  const includeArchived = state.includeArchived ? "true" : "false";
  const sourceType = state.documentSourceFilter === "all" ? "" : state.documentSourceFilter;
  const params = new URLSearchParams({
    includeArchived,
    keyword: state.documentKeyword || "",
    sourceType,
    page: String(state.documentPage),
    pageSize: String(state.documentPageSize),
  });
  const payload = await apiRequest(
    `/api/v1/admin/platform/knowledge-bases/${encodeURIComponent(kb.id)}/documents?${params.toString()}`,
  );
  if (state.selectedKbId !== requestedKbId) return;
  state.documents = payload.items || [];
  state.documentTotal = numberValue(payload.total, state.documents.length);
  state.documentPage = numberValue(payload.page, state.documentPage) || 1;
  state.documentPageSize = numberValue(payload.pageSize, state.documentPageSize) || state.documentPageSize;
  state.documentTotalPages = numberValue(payload.totalPages, 0);
  if (!state.documentTotalPages && state.documentTotal > 0 && state.documentPageSize > 0) {
    state.documentTotalPages = Math.max(1, Math.ceil(state.documentTotal / state.documentPageSize));
  }
  if (state.documentTotalPages && state.documentPage > state.documentTotalPages) {
    state.documentPage = state.documentTotalPages;
  }
  renderDocuments();
}

async function loadSelectedKnowledgeJobs() {
  const kb = selectedKnowledgeBase();
  if (!kb) {
    state.jobs = [];
    state.jobTotal = 0;
    state.jobTotalPages = 0;
    renderKnowledgeDetail();
    return;
  }
  const requestedKbId = kb.id;
  const jobStatus = state.jobStatusFilter ? `&status=${encodeURIComponent(state.jobStatusFilter)}` : "";
  const params = new URLSearchParams({
    kbId: kb.id,
    page: String(state.jobPage),
    pageSize: String(state.jobPageSize),
  });
  if (state.jobStatusFilter) {
    params.set("status", state.jobStatusFilter);
  }
  const payload = await apiRequest(`/api/v1/admin/platform/knowledge-ingest-jobs?${params.toString()}`);
  if (state.selectedKbId !== requestedKbId) return;
  state.jobs = payload.items || [];
  state.jobTotal = numberValue(payload.total, state.jobs.length);
  state.jobPage = numberValue(payload.page, state.jobPage) || 1;
  state.jobPageSize = numberValue(payload.pageSize, state.jobPageSize) || state.jobPageSize;
  state.jobTotalPages = numberValue(payload.totalPages, 0);
  if (!state.jobTotalPages && state.jobTotal > 0 && state.jobPageSize > 0) {
    state.jobTotalPages = Math.max(1, Math.ceil(state.jobTotal / state.jobPageSize));
  }
  if (state.jobTotalPages && state.jobPage > state.jobTotalPages) {
    state.jobPage = state.jobTotalPages;
  }
  renderJobs();
}

function renderKnowledgeDetail() {
  const kb = state.selectedKnowledgeBaseDetail || selectedKnowledgeBase();
  elements.kbEmptyState.classList.toggle("hidden", Boolean(kb));
  elements.kbDetailPanel.classList.toggle("hidden", !kb);
  if (!kb) {
    elements.selectedKbTitle.textContent = "选择知识库";
    updatePager(elements.documentPagerInfo, "doc", 1, 0, 0);
    updatePager(elements.jobPagerInfo, "job", 1, 0, 0);
    return;
  }
  const statusClass = knowledgeStatusClass(kb.status);
  const uploadDisabled = kb.status !== "active";
  elements.selectedKbTitle.textContent = kb.name || "未命名知识库";
  elements.selectedKbDescription.textContent = kb.description || "暂无说明";
  elements.selectedKbNamespace.textContent = namespaceLabel(kb.namespace);
  elements.selectedKbStatus.textContent = kb.status || "-";
  elements.selectedKbStatus.className = `badge${statusClass}`;
  elements.archiveKbButton.classList.toggle("hidden", uploadDisabled);
  elements.restoreKbButton.classList.toggle("hidden", !uploadDisabled);
  elements.kbDocsMetric.textContent = String(kb.documentCount || state.documentTotal || state.documents.length || 0);
  elements.kbChunksMetric.textContent = String(kb.chunkCount || 0);
  elements.kbFailedJobsMetric.textContent = String(kb.failedJobCount || failedJobCount(state.jobs));
  elements.kbUpdatedMetric.textContent = formatTime(kb.updatedAt);
  document.querySelectorAll(".detail-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.kbTab === state.kbTab);
  });
  document.querySelectorAll("[data-kb-panel]").forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.kbPanel !== state.kbTab);
  });
  document.querySelectorAll("[data-kb-tab='upload']").forEach((button) => {
    if (!button.classList.contains("detail-tab")) {
      button.disabled = uploadDisabled;
    }
  });
  Array.from(elements.uploadForm.elements || []).forEach((control) => {
    control.disabled = uploadDisabled;
  });
  Array.from(elements.metadataExtractionForm.elements || []).forEach((control) => {
    control.disabled = uploadDisabled;
  });
  renderDocuments();
  renderJobs();
  renderSearchResults();
  renderMetadataExtraction();
  renderUploadMode();
}

async function setKnowledgeTab(tab) {
  if (!["documents", "jobs", "search", "metadata", "upload"].includes(tab)) return;
  state.kbTab = tab;
  renderKnowledgeDetail();
  if (tab === "documents") {
    await loadSelectedKnowledgeDocuments();
  } else if (tab === "jobs") {
    await loadSelectedKnowledgeJobs();
  }
}

function renderDocuments() {
  const docs = state.documents;
  if (!state.documents.length) {
    elements.documentList.innerHTML = empty("暂无文档");
    updatePager(elements.documentPagerInfo, "doc", state.documentPage, state.documentTotalPages, state.documentTotal);
    return;
  }
  elements.documentList.innerHTML = docs.map((doc) => {
    const statusClass = documentStatusClass(doc.ingestStatus);
    const canArchive = doc.ingestStatus !== "archived";
    return `
      <article class="knowledge-row document-row">
        <div class="data-main">
          <button class="link-button" data-action="open-document" data-id="${escapeAttr(doc.id)}">
            ${escapeHtml(doc.title || doc.fileName || doc.id)}
          </button>
          <small>${escapeHtml(doc.sourceRef || doc.fileName || doc.id)}</small>
          ${doc.ingestError ? `<small class="danger-text">${escapeHtml(doc.ingestError)}</small>` : ""}
        </div>
        <span class="badge">${escapeHtml(sourceLabel(doc.sourceType))}</span>
        <span class="badge${statusClass}">${escapeHtml(doc.ingestStatus || "-")}</span>
        <span class="metric-text">${escapeHtml(doc.chunkCount || 0)} chunks</span>
        <span class="metric-text">${escapeHtml(formatTime(doc.updatedAt))}</span>
        <div class="row-actions">
          <button class="secondary-button" data-action="open-document" data-id="${escapeAttr(doc.id)}">详情</button>
          ${canArchive ? `<button class="secondary-button danger-action" data-action="archive-document" data-id="${escapeAttr(doc.id)}">归档</button>` : ""}
        </div>
      </article>
    `;
  }).join("");
  updatePager(elements.documentPagerInfo, "doc", state.documentPage, state.documentTotalPages, state.documentTotal);
}

function renderJobs() {
  if (!state.jobs.length) {
    elements.jobList.innerHTML = empty("暂无任务");
    updatePager(elements.jobPagerInfo, "job", state.jobPage, state.jobTotalPages, state.jobTotal);
    return;
  }
  elements.jobList.innerHTML = state.jobs.map((job) => {
    const statusClass = jobStatusClass(job.status);
    const canDelete = isTerminalJob(job.status);
    return `
      <article class="knowledge-row job-row">
        <div class="data-main">
          <button class="link-button" data-action="open-job" data-id="${escapeAttr(job.id)}">
            ${escapeHtml(job.sourceSummary || job.id)}
          </button>
          <small>${escapeHtml(job.traceId || job.id)}</small>
          ${job.errorMessage ? `<small class="danger-text">${escapeHtml(job.errorMessage)}</small>` : ""}
        </div>
        <span class="badge">${escapeHtml(sourceLabel(job.sourceType))}</span>
        <span class="badge${statusClass}">${escapeHtml(job.status || "-")}</span>
        <span class="metric-text">${escapeHtml(jobEffectSummary(job))}</span>
        <span class="metric-text">${escapeHtml(job.submittedBy || "-")}</span>
        <span class="metric-text">${escapeHtml(formatTime(job.updatedAt))}</span>
        <div class="row-actions">
          <button class="secondary-button" data-action="open-job" data-id="${escapeAttr(job.id)}">详情</button>
          ${canDelete ? `<button class="secondary-button danger-action" data-action="delete-job" data-id="${escapeAttr(job.id)}">删除</button>` : ""}
        </div>
      </article>
    `;
  }).join("");
  updatePager(elements.jobPagerInfo, "job", state.jobPage, state.jobTotalPages, state.jobTotal);
}

function renderSearchResults() {
  if (!state.searchResults.length) {
    elements.searchResults.innerHTML = empty("暂无检索结果");
    return;
  }
  elements.searchResults.innerHTML = state.searchResults.map((item) => `
    <article class="search-result">
      <div class="search-result-head">
        <strong>${escapeHtml(item.title || item.documentId)}</strong>
          <span class="badges">
          <span class="badge">${escapeHtml(item.kbName || item.kbId)}</span>
          <span class="badge">${escapeHtml(sourceLabel(item.sourceType))}</span>
          <span class="badge">${escapeHtml(item.score)}</span>
          </span>
        </div>
      <p>${escapeHtml(item.contentExcerpt || "")}</p>
      <small class="muted">${escapeHtml(item.sourceRef || item.chunkId || "")}</small>
    </article>
  `).join("");
}

function setUploadMode(mode) {
  if (!["file", "directory"].includes(mode)) return;
  state.uploadMode = mode;
  elements.uploadFileInput.value = "";
  elements.uploadDirectoryInput.value = "";
  renderUploadMode();
  updateUploadStatus();
}

function renderUploadMode() {
  const kb = selectedKnowledgeBase();
  const uploadDisabled = kb?.status !== "active";
  document.querySelectorAll("[data-upload-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.uploadMode === state.uploadMode);
    button.disabled = uploadDisabled;
  });
  document.querySelectorAll("[data-upload-panel]").forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.uploadPanel !== state.uploadMode);
  });
  elements.uploadTitleInput.disabled = uploadDisabled || state.uploadMode === "directory";
  elements.uploadSourceRefInput.disabled = uploadDisabled;
}

async function handleUploadSubmit(event) {
  event.preventDefault();
  const kb = selectedKnowledgeBase();
  if (!kb) {
    toast("请选择知识库", "error");
    return;
  }
  const files = selectedUploadFiles();
  if (!files.length) {
    toast("请选择文件或目录", "error");
    return;
  }
  await uploadKnowledgeFiles(kb, files);
  elements.uploadForm.reset();
  renderUploadMode();
  updateUploadStatus();
  await refreshKnowledge();
}

async function uploadKnowledgeFiles(kb, files) {
  const supported = files.filter(isSupportedUploadFile);
  const skipped = files.length - supported.length;
  if (!supported.length) {
    toast("没有可上传的文档类型", "error");
    return;
  }
  let completed = 0;
  let failed = 0;
  for (const file of supported) {
    const relativePath = file.webkitRelativePath || file.name;
    const sourceRef = uploadSourceRef(relativePath);
    const form = new FormData();
    form.append("file", file);
    form.append("sourceRef", sourceRef);
    form.append("metadata", JSON.stringify({
      relativePath,
      sourceRef,
      uploadMode: state.uploadMode,
      source: state.uploadMode === "directory" ? "browser_directory_upload" : "browser_file_upload",
    }));
    const title = state.uploadMode === "file" && supported.length === 1
      ? elements.uploadTitleInput.value.trim()
      : "";
    if (title) form.append("title", title);
    elements.uploadStatus.textContent = `正在上传 ${completed + failed + 1}/${supported.length}：${sourceRef}`;
    try {
      await apiRequest(`/api/v1/admin/platform/knowledge-bases/${encodeURIComponent(kb.id)}/ingest/file`, {
        method: "POST",
        body: form,
      });
      completed += 1;
    } catch (error) {
      failed += 1;
      elements.uploadStatus.textContent = `上传失败：${sourceRef} · ${errorMessage(error)}`;
    }
  }
  const pieces = [`成功 ${completed}`];
  if (failed) pieces.push(`失败 ${failed}`);
  if (skipped) pieces.push(`跳过 ${skipped}`);
  toast(`目录/文件上传完成：${pieces.join("，")}`, failed ? "error" : "success");
}

function selectedUploadFiles() {
  const byPath = new Map();
  const input = state.uploadMode === "directory" ? elements.uploadDirectoryInput : elements.uploadFileInput;
  for (const file of Array.from(input.files || [])) {
    byPath.set(file.webkitRelativePath || file.name, file);
  }
  return Array.from(byPath.values());
}

function updateUploadStatus() {
  const files = selectedUploadFiles();
  if (!files.length) {
    elements.uploadStatus.textContent = "";
    return;
  }
  const supported = files.filter(isSupportedUploadFile).length;
  const modeLabel = state.uploadMode === "directory" ? "目录" : "文件";
  const totalSize = files.reduce((sum, file) => sum + Number(file.size || 0), 0);
  elements.uploadStatus.textContent = `已选择${modeLabel} ${files.length} 项，可上传 ${supported} 项 · ${formatBytes(totalSize)}`;
}

function uploadSourceRef(relativePath) {
  const prefix = elements.uploadSourceRefInput.value.trim().replace(/[\\/]+$/, "");
  return prefix ? `${prefix}/${relativePath}` : relativePath;
}

function isSupportedUploadFile(file) {
  const name = String(file.name || "").toLowerCase();
  const type = String(file.type || "").toLowerCase();
  return (
    type.startsWith("text/")
    || type === "application/pdf"
    || [".pdf", ".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm", ".log"].some((suffix) => name.endsWith(suffix))
  );
}

async function runKnowledgeSearch() {
  const kb = selectedKnowledgeBase();
  const query = elements.searchInput.value.trim();
  if (!kb) {
    toast("请选择知识库", "error");
    return;
  }
  if (!query) {
    toast("请输入搜索内容", "error");
    return;
  }
  const payload = await apiRequest("/api/v1/admin/platform/knowledge-search", {
    method: "POST",
    body: JSON.stringify({
      query,
      kbIds: [kb.id],
      topK: numberValue(elements.searchTopKInput.value, 5),
      minScore: 0,
      metadataFilter: {},
    }),
  });
  state.searchResults = payload.items || [];
  renderSearchResults();
}

async function openDocumentDetail(documentId) {
  const kb = selectedKnowledgeBase();
  if (!kb || !documentId) return;
  elements.documentDrawerTitle.textContent = "文档详情";
  elements.documentDetailContent.innerHTML = empty("正在加载文档详情");
  elements.documentDrawer.classList.remove("hidden");
  const documentDetail = await apiRequest(
    `/api/v1/admin/platform/knowledge-bases/${encodeURIComponent(kb.id)}/documents/${encodeURIComponent(documentId)}`,
  );
  state.selectedDocument = documentDetail;
  renderDocumentDetail();
}

function renderDocumentDetail() {
  const doc = state.selectedDocument;
  if (!doc) {
    elements.documentDetailContent.innerHTML = empty("暂无文档详情");
    return;
  }
  elements.documentDrawerTitle.textContent = doc.title || doc.fileName || "文档详情";
  const canArchive = doc.ingestStatus !== "archived";
  elements.documentDetailContent.innerHTML = `
    <dl class="detail-list">
      ${detailPair("标题", doc.title || "-")}
      ${detailPair("来源", `${sourceLabel(doc.sourceType)} / ${doc.docKind || "-"}`)}
      ${detailPair("状态", doc.ingestStatus || "-")}
      ${detailPair("文件", doc.fileName || "-")}
      ${detailPair("来源备注", doc.sourceRef || "-")}
      ${detailPair("大小", formatBytes(Number(doc.fileSize || 0)))}
      ${detailPair("Chunks", doc.chunkCount || 0)}
      ${detailPair("版本", `v${doc.version || 1}`)}
      ${detailPair("最近任务", doc.lastIngestJobId || "历史数据")}
      ${detailPair("更新时间", formatTime(doc.updatedAt))}
    </dl>
    <section class="drawer-section">
      <h3>摘要</h3>
      <pre class="excerpt">${escapeHtml(doc.contentExcerpt || "暂无摘要")}</pre>
    </section>
    <section class="drawer-section">
      <h3>Metadata</h3>
      <pre class="metadata">${escapeHtml(formatJson(doc.metadataJson || {}))}</pre>
    </section>
    <div class="form-actions">
      ${canArchive ? `<button class="secondary-button danger-action" data-action="archive-document-detail">归档文档</button>` : ""}
    </div>
  `;
}

async function archiveSelectedDocument() {
  const documentId = state.selectedDocument?.id;
  if (!documentId) return;
  await archiveDocument(documentId);
  closeDocumentDrawer();
}

function closeDocumentDrawer() {
  state.selectedDocument = null;
  elements.documentDrawer.classList.add("hidden");
}

async function openJobDetail(jobId) {
  if (!jobId) return;
  elements.jobDrawerTitle.textContent = "任务详情";
  elements.jobDetailContent.innerHTML = empty("正在加载任务详情");
  elements.jobDrawer.classList.remove("hidden");
  state.selectedJob = await apiRequest(`/api/v1/admin/platform/knowledge-ingest-jobs/${encodeURIComponent(jobId)}`);
  renderJobDetail();
}

function renderJobDetail() {
  const job = state.selectedJob;
  if (!job) {
    elements.jobDetailContent.innerHTML = empty("暂无任务详情");
    return;
  }
  elements.jobDrawerTitle.textContent = job.sourceSummary || "任务详情";
  const steps = Array.isArray(job.steps) ? job.steps : [];
  const effects = Array.isArray(job.documentEffects) ? job.documentEffects : [];
  elements.jobDetailContent.innerHTML = `
    <dl class="detail-list">
      ${detailPair("来源", job.sourceSummary || "-")}
      ${detailPair("类型", sourceLabel(job.sourceType))}
      ${detailPair("状态", job.status || "-")}
      ${detailPair("提交人", job.submittedBy || "-")}
      ${detailPair("TraceId", job.traceId || "-")}
      ${detailPair("尝试次数", job.attemptCount || 0)}
      ${detailPair("开始", formatTime(job.startedAt))}
      ${detailPair("结束", formatTime(job.endedAt))}
      ${detailPair("更新", formatTime(job.updatedAt))}
      ${detailPair("错误", job.errorMessage || "-")}
    </dl>
    <section class="drawer-section">
      <h3>步骤</h3>
      <div class="step-list">
        ${steps.length ? steps.map(renderJobStep).join("") : empty("暂无步骤")}
      </div>
    </section>
    <section class="drawer-section">
      <h3>文档影响</h3>
      <div class="effect-list">
        ${effects.length ? effects.map(renderDocumentEffect).join("") : empty("暂无文档影响")}
      </div>
    </section>
    <section class="drawer-section">
      <h3>结果 JSON</h3>
      <pre class="metadata">${escapeHtml(formatJson(job.resultJson || {}))}</pre>
    </section>
    <div class="form-actions">
      ${isTerminalJob(job.status) ? `<button class="secondary-button danger-action" data-action="delete-job" data-id="${escapeAttr(job.id)}">删除任务记录</button>` : ""}
    </div>
  `;
}

function renderJobStep(step) {
  return `
    <article class="timeline-item">
      <span class="kb-item__signal" data-status="${escapeAttr(step.status)}"></span>
      <div>
        <strong>${escapeHtml(step.stepName || step.id)}</strong>
        <small>${escapeHtml(step.status || "-")} · ${escapeHtml(formatTime(step.startedAt))}</small>
        ${step.errorMessage ? `<small class="danger-text">${escapeHtml(step.errorMessage)}</small>` : ""}
        <pre>${escapeHtml(formatJson(step.summary || {}))}</pre>
      </div>
    </article>
  `;
}

function renderDocumentEffect(effect) {
  return `
    <article class="effect-item">
      <strong>${escapeHtml(effectLabel(effect.operation))}</strong>
      <span>${escapeHtml(effect.title || effect.documentId || "-")}</span>
      <small>${escapeHtml(effect.documentId || "")}</small>
    </article>
  `;
}

function closeJobDrawer() {
  state.selectedJob = null;
  elements.jobDrawer.classList.add("hidden");
}

async function archiveSelectedKnowledgeBase() {
  const kb = selectedKnowledgeBase();
  if (!kb) return;
  await apiRequest(`/api/v1/admin/platform/knowledge-bases/${encodeURIComponent(kb.id)}/archive`, {
    method: "POST",
  });
  toast("知识库已归档");
  await refreshKnowledge();
}

async function restoreSelectedKnowledgeBase() {
  const kb = selectedKnowledgeBase();
  if (!kb) return;
  await apiRequest(`/api/v1/admin/platform/knowledge-bases/${encodeURIComponent(kb.id)}/restore`, {
    method: "POST",
  });
  toast("知识库已恢复");
  await refreshKnowledge();
}

async function changeKnowledgePage(delta) {
  const nextPage = Math.max(1, state.knowledgePage + delta);
  if (nextPage === state.knowledgePage) return;
  state.knowledgePage = nextPage;
  await refreshKnowledge({ refreshSelected: false, refreshOptions: false, refreshTabData: false });
}

async function changeDocumentPage(delta) {
  const nextPage = Math.max(1, state.documentPage + delta);
  if (nextPage === state.documentPage) return;
  state.documentPage = nextPage;
  await loadSelectedKnowledgeDocuments();
}

async function changeJobPage(delta) {
  const nextPage = Math.max(1, state.jobPage + delta);
  if (nextPage === state.jobPage) return;
  state.jobPage = nextPage;
  await loadSelectedKnowledgeJobs();
}

function updatePager(target, kind, page, totalPages, totalItems) {
  if (!target) return;
  const canPrev = page > 1;
  const canNext = totalPages > 0 ? page < totalPages : totalItems > 0;
  const info = totalPages > 0
    ? `第 ${page}/${totalPages} 页 · ${totalItems || 0} 条`
    : totalItems > 0
      ? `第 ${page} 页 · ${totalItems} 条`
      : "暂无数据";
  target.textContent = info;
  const prevButton = target.previousElementSibling;
  const nextButton = target.nextElementSibling;
  if (prevButton) prevButton.disabled = !canPrev;
  if (nextButton) nextButton.disabled = !canNext;
}

async function deleteSelectedKnowledgeBase() {
  const kb = selectedKnowledgeBase();
  if (!kb) return;
  const confirmed = window.confirm(`确定永久删除知识库「${kb.name}」吗？这会同时删除文档、分片和任务记录。`);
  if (!confirmed) return;
  await apiRequest(`/api/v1/admin/platform/knowledge-bases/${encodeURIComponent(kb.id)}`, {
    method: "DELETE",
  });
  state.selectedAgentKbIds = state.selectedAgentKbIds.filter((kbId) => kbId !== kb.id);
  renderKnowledgeOptions(state.selectedAgentKbIds);
  state.selectedKbId = "";
  state.selectedKnowledgeBaseDetail = null;
  state.documents = [];
  state.jobs = [];
  state.searchResults = [];
  toast("知识库已删除");
  await Promise.all([refreshPlatformAgents(), refreshUserAgents()]);
  await refreshKnowledge({ refreshSelected: false, refreshTabData: false, refreshOptions: true });
}

async function archiveDocument(documentId) {
  const kb = selectedKnowledgeBase();
  if (!kb) return;
  await apiRequest(
    `/api/v1/admin/platform/knowledge-bases/${encodeURIComponent(kb.id)}/documents/${encodeURIComponent(documentId)}/archive`,
    { method: "POST" },
  );
  toast("文档已归档");
  await refreshKnowledge();
}

async function deleteJob(jobId) {
  const job = state.jobs.find((item) => item.id === jobId);
  if (job && job.status === "running") {
    const confirmed = window.confirm("该任务状态为「运行中」，可能是进程中断导致的卡死任务。确定删除吗？");
    if (!confirmed) return;
  }
  await apiRequest(`/api/v1/admin/platform/knowledge-ingest-jobs/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
  });
  if (state.selectedJob?.id === jobId) {
    closeJobDrawer();
  }
  toast("任务记录已删除");
  await refreshKnowledge();
}

async function clearJobs() {
  const kb = selectedKnowledgeBase();
  if (!kb) {
    toast("请选择知识库", "error");
    return;
  }
  const confirmed = window.confirm(
    `确定清空知识库「${kb.name}」的已结束入库任务吗？运行中和排队中的任务会保留。`,
  );
  if (!confirmed) return;
  const result = await apiRequest(
    `/api/v1/admin/platform/knowledge-ingest-jobs?kbId=${encodeURIComponent(kb.id)}`,
    { method: "DELETE" },
  );
  state.jobPage = 1;
  if (state.selectedJob && state.selectedJob.kbId === kb.id) {
    closeJobDrawer();
  }
  toast(`已清空 ${result.deletedJobCount || 0} 条已结束任务`);
  await refreshKnowledge();
}

function failedJobCount(jobs) {
  return jobs.filter((job) => job.status === "failed").length;
}

function knowledgeStatusLabel(status) {
  if (status === "active") return "启用";
  if (status === "archived") return "归档";
  return status || "-";
}

function knowledgeStatusClass(status) {
  return status === "active" ? "" : " warn";
}

function namespaceLabel(value) {
  if (value === "policy") return "政策";
  if (value === "customer_service") return "客服";
  return value || "default";
}

function sourceLabel(value) {
  if (value === "file") return "文件";
  if (value === "url") return "URL";
  if (value === "qa") return "QA";
  return value || "-";
}

function documentStatusClass(value) {
  if (value === "completed") return "";
  if (value === "archived" || value === "queued" || value === "running") return " warn";
  return " danger";
}

function jobStatusClass(value) {
  if (value === "completed") return "";
  if (value === "queued" || value === "running" || value === "partial_completed") return " warn";
  if (value === "failed" || value === "canceled") return " danger";
  return " warn";
}

function isTerminalJob(value) {
  // 终态任务 + running（可能卡死）任务都允许删除
  return ["completed", "partial_completed", "failed", "canceled", "running"].includes(value);
}

function effectLabel(operation) {
  if (operation === "created") return "新增";
  if (operation === "updated") return "更新";
  if (operation === "unchanged") return "未变化";
  if (operation === "deleted") return "删除";
  return operation || "-";
}

function jobEffectSummary(job) {
  const effects = Array.isArray(job.documentEffects) ? job.documentEffects : [];
  if (!effects.length) {
    return job.status === "failed" ? "失败" : "历史任务";
  }
  const counts = effects.reduce((result, effect) => {
    const operation = effect.operation || "unknown";
    result[operation] = (result[operation] || 0) + 1;
    return result;
  }, {});
  return Object.entries(counts)
    .map(([operation, count]) => `${effectLabel(operation)} ${count}`)
    .join(" / ");
}

function detailPair(label, value) {
  return `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value ?? "-")}</dd></div>`;
}

function formatJson(value) {
  try {
    return JSON.stringify(value || {}, null, 2);
  } catch {
    return "{}";
  }
}

function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function selectedKnowledgeBase() {
  if (!state.selectedKbId) return null;
  if (state.selectedKnowledgeBaseDetail?.id === state.selectedKbId) {
    return state.selectedKnowledgeBaseDetail;
  }
  return findKnowledgeBaseById(state.selectedKbId);
}

function findKnowledgeBaseById(kbId) {
  if (!kbId) return null;
  return (
    state.knowledgeBases.find((kb) => kb.id === kbId)
    || state.knowledgeBaseOptions.find((kb) => kb.id === kbId)
    || null
  );
}

async function apiRequest(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const body = options.body;
  if (state.userToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${state.userToken}`);
  }
  if (body && !(body instanceof FormData) && !(body instanceof URLSearchParams) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${state.apiBase}${path}`, {
    ...options,
    headers,
  });
  const text = await response.text();
  const payload = parseJson(text);
  if (!response.ok) {
    throw new Error(apiErrorMessage(payload, response.status));
  }
  return payload;
}

function parseJson(text) {
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function readJsonStorage(key, fallback) {
  try {
    const value = localStorage.getItem(key);
    if (!value) return fallback;
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" ? parsed : fallback;
  } catch {
    return fallback;
  }
}

function tokenValue(payload) {
  if (!payload) return "";
  if (typeof payload === "string") return payload;
  if (payload.access_token) return payload.access_token;
  if (payload.token?.access_token) return payload.token.access_token;
  return "";
}

function apiErrorMessage(payload, status) {
  if (typeof payload === "string") return payload || `HTTP ${status}`;
  if (payload?.detail) {
    if (typeof payload.detail === "string") return payload.detail;
    if (payload.detail.message) return payload.detail.message;
    if (payload.detail.code) return payload.detail.code;
    return JSON.stringify(payload.detail);
  }
  if (payload?.message) return payload.message;
  return `HTTP ${status}`;
}

function errorMessage(error) {
  if (error instanceof Error && error.message) return error.message;
  return "操作失败";
}

function selectedOptions(select) {
  if (!select) return [];
  if (select.selectedOptions) {
    return Array.from(select.selectedOptions).map((option) => option.value);
  }
  if (select.classList.contains("agent-kb-select")) {
    return Array.from(select.querySelectorAll("input[data-agent-kb-id]")).map((option) => option.value);
  }
  return Array.from(select.querySelectorAll("input[type='checkbox']:checked")).map((option) => option.value);
}

function numberValue(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function empty(label) {
  return `<div class="empty">${escapeHtml(label)}</div>`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function toast(message, type = "success") {
  elements.toast.textContent = message;
  elements.toast.style.background = type === "error" ? "#7f1d1d" : "#17211c";
  elements.toast.classList.add("show");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => {
    elements.toast.classList.remove("show");
  }, 2600);
}
