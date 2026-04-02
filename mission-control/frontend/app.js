/**
 * Sup Mission Control — Frontend
 */

// ── State ──────────────────────────────────────────────────────
let currentProject = null;
let chatAbortController = null;

// ── DOM refs ───────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ── Navigation ─────────────────────────────────────────────────
function showView(viewId) {
  $$('.view').forEach(v => v.classList.remove('active'));
  $(`#view-${viewId}`).classList.add('active');
}

$('#btn-home').addEventListener('click', () => {
  currentProject = null;
  showView('home');
});

// ── Search ─────────────────────────────────────────────────────
let searchTimeout = null;
const searchInput = $('#search-input');
const searchResults = $('#search-results');

searchInput.addEventListener('input', () => {
  clearTimeout(searchTimeout);
  const q = searchInput.value.trim();
  if (q.length < 2) { searchResults.classList.add('hidden'); return; }
  searchTimeout = setTimeout(() => searchProjects(q), 300);
});

searchInput.addEventListener('focus', () => {
  if (searchResults.children.length > 0 && searchInput.value.trim().length >= 2) {
    searchResults.classList.remove('hidden');
  }
});

document.addEventListener('click', (e) => {
  if (!e.target.closest('.search-wrapper')) searchResults.classList.add('hidden');
});

async function searchProjects(q) {
  try {
    const res = await fetch(`/api/projects/search?q=${encodeURIComponent(q)}`);
    const data = await res.json();
    const projects = data.projects || [];
    
    searchResults.innerHTML = '';
    if (projects.length === 0) {
      searchResults.innerHTML = '<div class="search-item"><span class="detail">No projects found</span></div>';
    } else {
      projects.forEach(p => {
        const item = document.createElement('div');
        item.className = 'search-item';
        item.innerHTML = `
          <div class="name">${esc(p.name)}</div>
          <div class="detail">${esc(p.full_address || '')} · ${esc(p.record_status || '')}</div>
        `;
        item.addEventListener('click', () => {
          searchResults.classList.add('hidden');
          searchInput.value = p.name;
          openProject(p);
        });
        searchResults.appendChild(item);
      });
    }
    searchResults.classList.remove('hidden');
  } catch (err) {
    console.error('Search error:', err);
  }
}

// ── Open Project ───────────────────────────────────────────────
async function openProject(project) {
  currentProject = project;
  showView('project');
  
  // Fill header
  $('#proj-name').textContent = project.name;
  $('#proj-status').textContent = project.record_status || '—';
  $('#proj-status').className = 'status-badge ' + statusClass(project.record_status);
  $('#proj-app-link').href = project.job_url || '#';
  $('#proj-address').textContent = project.full_address || '—';
  $('#proj-rep').textContent = project.user?.name || project.projects?.[0]?.user?.name || '—';
  
  // Contact
  const contact = project.contact || project.projects?.[0]?.contact;
  $('#proj-contact').textContent = contact ? `${contact.name} (${contact.phone_number || ''})` : '—';
  
  // Dates
  $('#proj-status-date').textContent = formatDate(project.date_status_change);
  $('#proj-last-contact').textContent = project.last_contacted || '—';
  
  // Reset chat
  $('#project-chat-messages').innerHTML = `
    <div class="chat-msg assistant">Loaded ${esc(project.name)}. I have full context on this job — ask me anything or run a skill. 🏗️</div>
  `;
  
  // Load data in parallel
  const pid = project.id;
  loadFlowCards(pid);
  loadDriveFiles(project.google_drive_link);
  loadConvoTimeline(pid);
}

// ── Flow Cards ─────────────────────────────────────────────────
async function loadFlowCards(projectId) {
  const container = $('#flow-cards');
  container.innerHTML = '<div class="loading-spinner">Loading flow cards...</div>';
  
  try {
    const res = await fetch(`/api/projects/${projectId}/flow`);
    const trackers = await res.json();
    
    // Filter to meaningful cards (have a tag and are pinned or have bid data)
    const cards = trackers.filter(t => 
      t.tag || t.action_type === 'o&p' || t.action_type === 'pricelist'
    ).sort((a, b) => (a.lft || 0) - (b.lft || 0));
    
    if (cards.length === 0) {
      container.innerHTML = '<div class="loading-spinner">No flow cards found</div>';
      return;
    }
    
    container.innerHTML = '';
    cards.forEach(card => {
      const el = document.createElement('div');
      el.className = 'flow-card';
      
      const emoji = card.supplement_status_emoji || '📋';
      const tag = card.tag || card.content || card.action_type || '—';
      const gap = parseFloat(card.how_far_are_we_off) || 0;
      const gapClass = gap > 0 ? 'positive' : gap < 0 ? 'negative' : 'neutral';
      const gapStr = gap !== 0 ? `${gap > 0 ? '+' : ''}$${Math.abs(gap).toLocaleString('en', {minimumFractionDigits: 2})}` : '—';
      
      const doingWork = card.doing_the_work_status;
      const workLabel = doingWork === true ? '✅ Doing work' : doingWork === false ? '⬜ Not doing' : '';
      
      el.innerHTML = `
        <div class="flow-card-header" onclick="this.parentElement.classList.toggle('expanded')">
          <div class="flow-card-left">
            <span class="flow-card-emoji">${emoji}</span>
            <span class="flow-card-tag">${esc(tag)}</span>
            <span class="flow-card-status">${workLabel}</span>
          </div>
          <div class="flow-card-right">
            <span class="flow-card-money ${gapClass}">${gapStr}</span>
            <span class="flow-card-chevron">▶</span>
          </div>
        </div>
        <div class="flow-card-body">
          ${flowDetail('IFC Retail', card.retail_exactimate_bid)}
          ${flowDetail('INS RCV', card.latest_rcv_rcv)}
          ${flowDetail('O&P from Supp', card.op_from_ifc_supplement)}
          ${flowDetail('Original Bid', card.original_sub_bid_price)}
          ${flowDetail('NRD', card.latest_rcv_non_recoverable_depreciation)}
          ${flowDetail('Production', card.production_status)}
          ${flowDetail('Completed', card.completion_date)}
          ${card.supplement_notes ? `<div class="flow-notes">${esc(card.supplement_notes)}</div>` : ''}
          ${card.pricelist_notes ? `<div class="flow-notes">${esc(card.pricelist_notes)}</div>` : ''}
          ${card.op_card_notes ? `<div class="flow-notes">${esc(card.op_card_notes)}</div>` : ''}
          ${card.trade_production_notes ? `<div class="flow-notes">📦 ${esc(card.trade_production_notes)}</div>` : ''}
          ${card.folder_link ? `<div style="margin-top:8px"><a href="${card.folder_link}" target="_blank" class="btn-outline">📁 Drive Folder</a></div>` : ''}
        </div>
      `;
      container.appendChild(el);
    });
  } catch (err) {
    container.innerHTML = `<div class="loading-spinner" style="color:var(--red)">Error: ${esc(err.message)}</div>`;
  }
}

function flowDetail(label, value) {
  if (!value && value !== 0) return '';
  const v = typeof value === 'number' || (typeof value === 'string' && !isNaN(value) && value !== '') 
    ? `$${parseFloat(value).toLocaleString('en', {minimumFractionDigits: 2})}` 
    : value;
  return `<div class="flow-detail"><span class="label">${label}</span><span class="value">${esc(String(v))}</span></div>`;
}

// ── Drive Files ────────────────────────────────────────────────
async function loadDriveFiles(driveLink) {
  const container = $('#drive-files');
  container.innerHTML = '<div class="loading-spinner">Loading files...</div>';
  
  if (!driveLink) {
    container.innerHTML = '<div class="loading-spinner">No Drive link</div>';
    return;
  }
  
  // Extract folder ID from drive link
  const match = driveLink.match(/folders\/([a-zA-Z0-9_-]+)/);
  if (!match) {
    container.innerHTML = '<div class="loading-spinner">Could not parse Drive folder ID</div>';
    return;
  }
  
  try {
    // First get the Supplement subfolder
    const res = await fetch(`/api/drive/list/${match[1]}`);
    const data = await res.json();
    
    const suppFolder = data.files.find(f => f.name === 'Supplement' && f.mimeType.includes('folder'));
    
    if (!suppFolder) {
      container.innerHTML = '<div class="loading-spinner">No Supplement folder found</div>';
      return;
    }
    
    // List supplement folder contents (exclude Archive)
    const suppRes = await fetch(`/api/drive/list/${suppFolder.id}`);
    const suppData = await suppRes.json();
    
    const files = suppData.files.filter(f => 
      f.name !== 'Archive' && f.name !== '@ifc' && !f.mimeType.includes('folder')
    );
    
    if (files.length === 0) {
      container.innerHTML = '<div class="loading-spinner">No files in Supplement folder</div>';
      return;
    }
    
    container.innerHTML = '';
    files.sort((a, b) => a.name.localeCompare(b.name)).forEach(f => {
      const icon = f.mimeType.includes('pdf') ? '📄' : 
                   f.mimeType.includes('image') ? '🖼️' : 
                   f.mimeType.includes('spreadsheet') ? '📊' : '📎';
      const link = f.webViewLink || `https://drive.google.com/file/d/${f.id}/view`;
      const el = document.createElement('div');
      el.className = 'drive-file';
      el.innerHTML = `<span class="drive-file-icon">${icon}</span><a href="${link}" target="_blank">${esc(f.name)}</a>`;
      container.appendChild(el);
    });
  } catch (err) {
    container.innerHTML = `<div class="loading-spinner" style="color:var(--red)">Error: ${esc(err.message)}</div>`;
  }
}

// ── Convo Timeline ─────────────────────────────────────────────
async function loadConvoTimeline(projectId) {
  const container = $('#convo-timeline');
  container.innerHTML = '<div class="loading-spinner">Loading...</div>';
  container.classList.add('collapsed');
  
  try {
    const res = await fetch(`/api/projects/${projectId}/posts`);
    const data = await res.json();
    const posts = data.posts || [];
    
    if (posts.length === 0 || !posts[0].post_notes) {
      container.innerHTML = '<div class="loading-spinner">No conversation notes</div>';
      return;
    }
    
    const notes = posts[0].post_notes.sort((a, b) => 
      new Date(b.created_at) - new Date(a.created_at)
    );
    
    container.innerHTML = '';
    notes.forEach(note => {
      const el = document.createElement('div');
      el.className = 'convo-entry';
      // Strip HTML tags but keep structure
      const body = note.body
        .replace(/<br\s*\/?>/gi, '\n')
        .replace(/<div>/gi, '\n')
        .replace(/<\/div>/gi, '')
        .replace(/<span[^>]*class="mention-tag"[^>]*>([^<]*)<\/span>/gi, '$1')
        .replace(/<span[^>]*class="user-mention-message"[^>]*>([^<]*)<\/span>/gi, '@$1')
        .replace(/<[^>]+>/g, '')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
      
      el.innerHTML = `
        <div class="convo-entry-header">
          <span class="convo-author">${esc(note.user?.name || 'Unknown')}</span>
          <span class="convo-date">${formatDate(note.created_at)}</span>
        </div>
        <div class="convo-body">${esc(body)}</div>
      `;
      container.appendChild(el);
    });
  } catch (err) {
    container.innerHTML = `<div class="loading-spinner" style="color:var(--red)">Error: ${esc(err.message)}</div>`;
  }
}

// ── Collapsible sections ───────────────────────────────────────
$$('.section-header.collapsible').forEach(header => {
  header.addEventListener('click', () => {
    const targetId = header.dataset.target;
    const body = $(`#${targetId}`);
    const h3 = header.querySelector('h3');
    body.classList.toggle('collapsed');
    const isCollapsed = body.classList.contains('collapsed');
    h3.textContent = h3.textContent.replace(/^[▶▼]/, isCollapsed ? '▶' : '▼');
  });
});

// ── Chat ───────────────────────────────────────────────────────
function setupChat(inputId, sendBtnId, messagesId, contextFn) {
  const input = $(`#${inputId}`);
  const btn = $(`#${sendBtnId}`);
  const messages = $(`#${messagesId}`);
  
  async function send() {
    const text = input.value.trim();
    if (!text) return;
    
    // Add user message
    appendMsg(messages, 'user', text);
    input.value = '';
    
    // Build messages array with context
    const systemMsg = contextFn ? contextFn() : '';
    const chatMessages = [
      ...(systemMsg ? [{ role: 'user', content: systemMsg }] : []),
      { role: 'user', content: text }
    ];
    
    // Add assistant placeholder
    const assistantEl = appendMsg(messages, 'assistant', '⏳ Thinking...');
    
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: chatMessages,
          user: currentProject ? `project-${currentProject.id}` : 'home',
          stream: true,
        }),
      });
      
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      
      // Stream the response
      assistantEl.textContent = '';
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let fullText = '';
      
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n').filter(l => l.trim());
        
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            if (data === '[DONE]') continue;
            try {
              const parsed = JSON.parse(data);
              const delta = parsed.choices?.[0]?.delta?.content;
              if (delta) {
                fullText += delta;
                assistantEl.textContent = fullText;
                messages.scrollTop = messages.scrollHeight;
              }
            } catch (e) {
              // Skip unparseable chunks
            }
          }
        }
      }
      
      if (!fullText) assistantEl.textContent = '(No response)';
    } catch (err) {
      assistantEl.textContent = `❌ Error: ${err.message}`;
      assistantEl.style.color = 'var(--red)';
    }
    
    messages.scrollTop = messages.scrollHeight;
  }
  
  btn.addEventListener('click', send);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
}

function appendMsg(container, role, text) {
  const el = document.createElement('div');
  el.className = `chat-msg ${role}`;
  el.textContent = text;
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
  return el;
}

// Home chat
setupChat('home-chat-input', 'home-chat-send', 'home-chat-messages', null);

// Project chat with context
setupChat('project-chat-input', 'project-chat-send', 'project-chat-messages', () => {
  if (!currentProject) return '';
  return `[Context: The user is looking at project "${currentProject.name}" (ID: ${currentProject.id}). ` +
    `Address: ${currentProject.full_address || '?'}. Status: ${currentProject.record_status || '?'}. ` +
    `Provide project-specific answers. Pull convo/flow data if needed.]`;
});

// ── Action Buttons ─────────────────────────────────────────────
$('#btn-estimate').addEventListener('click', () => {
  if (!currentProject) return;
  const msg = `Run @estimate for ${currentProject.name}`;
  $('#project-chat-input').value = msg;
  $('#project-chat-send').click();
});

$('#btn-review').addEventListener('click', () => {
  if (!currentProject) return;
  const msg = `Run @review for ${currentProject.name}`;
  $('#project-chat-input').value = msg;
  $('#project-chat-send').click();
});

$('#btn-markup').addEventListener('click', () => {
  if (!currentProject) return;
  const msg = `Run @markup for ${currentProject.name}`;
  $('#project-chat-input').value = msg;
  $('#project-chat-send').click();
});

$('#btn-precall').addEventListener('click', () => {
  if (!currentProject) return;
  const msg = `Run @precall for ${currentProject.name}`;
  $('#project-chat-input').value = msg;
  $('#project-chat-send').click();
});

$('#btn-calling').addEventListener('click', () => {
  if (!currentProject) return;
  const msg = `Run @calling for ${currentProject.name}`;
  $('#project-chat-input').value = msg;
  $('#project-chat-send').click();
});

// ── Tasks ──────────────────────────────────────────────────────
async function loadTasks() {
  const container = $('#tasks-list');
  
  try {
    const res = await fetch('/api/tasks?status=active');
    const data = await res.json();
    const projects = data.projects || [];
    
    if (projects.length === 0) {
      container.innerHTML = '<div class="loading-spinner">No pending supplement tasks</div>';
      return;
    }
    
    container.innerHTML = '';
    projects.forEach(p => {
      const el = document.createElement('div');
      el.className = 'task-card';
      el.innerHTML = `
        <div class="task-name">${esc(p.name)}</div>
        <div class="task-meta">${esc(p.full_address || '')} · ${esc(p.user?.name || '')}</div>
        <span class="task-status ${statusClass(p.record_status)}">${esc(p.record_status || '—')}</span>
      `;
      el.addEventListener('click', () => {
        searchInput.value = p.name;
        openProject(p);
      });
      container.appendChild(el);
    });
  } catch (err) {
    container.innerHTML = `<div class="loading-spinner" style="color:var(--red)">Error loading tasks: ${esc(err.message)}</div>`;
  }
}

// ── Helpers ─────────────────────────────────────────────────────
function esc(str) {
  if (!str) return '';
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

function formatDate(dateStr) {
  if (!dateStr) return '—';
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  } catch { return dateStr; }
}

function statusClass(status) {
  if (!status) return 'default';
  const s = status.toUpperCase();
  if (s.includes('SUPP SENT') || s.includes('SUPP_SENT')) return 'supp-sent';
  if (s.includes('INS RESPONDED') || s.includes('INS_RESPONDED')) return 'ins-responded';
  if (s.includes('OFFICE HANDS') || s.includes('OFFICE_HANDS')) return 'office-hands';
  if (s.includes('SUPP COMPLETED') || s.includes('SUPP_COMPLETED')) return 'supp-completed';
  return 'default';
}

// ── Chat collapse toggle ───────────────────────────────────────
$('#btn-collapse-chat').addEventListener('click', () => {
  const layout = $('.project-layout');
  const btn = $('#btn-collapse-chat');
  layout.classList.toggle('chat-collapsed');
  btn.textContent = layout.classList.contains('chat-collapsed') ? '▶' : '◀';
});

// ── Init ───────────────────────────────────────────────────────
loadTasks();
