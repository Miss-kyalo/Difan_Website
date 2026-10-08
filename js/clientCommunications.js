document.addEventListener('DOMContentLoaded', () => {
  const section = document.getElementById('dashboard-community-section');
  const clientMessagesView = document.getElementById('client-messages-view');
  const staffMessagesView = document.getElementById('staff-messages-view');
  const messagesNavigation = document.getElementById('messages-navigation');
  if (!section || !clientMessagesView || !staffMessagesView || !messagesNavigation) return;

  const allowedStaffRoles = new Set(['admin', 'hr', 'accountant', 'boss']);
  const clientNoticeFeed = document.getElementById('client-notice-feed');
  const staffNoticeFeed = document.getElementById('staff-notice-feed');
  const clientNoticeStatus = document.getElementById('client-notice-status');
  const staffNoticeStatus = document.getElementById('staff-notice-status');
  const clientConversationList = document.getElementById('client-conversation-list');
  const staffConversationList = document.getElementById('staff-conversation-list');
  const clientMessageThread = document.getElementById('client-message-thread');
  const staffMessageThread = document.getElementById('staff-message-thread');
  const clientMessageStatus = document.getElementById('client-message-status');
  const staffMessageStatus = document.getElementById('staff-message-status');
  const clientMessageRole = document.getElementById('client-message-role');
  const clientMessageContact = document.getElementById('client-message-contact');
  const clientMessageForm = document.getElementById('client-message-form');
  const staffMessageForm = document.getElementById('staff-message-form');
  const staffRecipient = document.getElementById('staff-message-recipient');
  const staffStartForm = document.getElementById('staff-start-conversation-form');
  const staffInboxButton = document.getElementById('staff-inbox-button');
  const selectedThreadTitles = {
    client: document.getElementById('client-thread-title'),
    staff: document.getElementById('staff-thread-title'),
  };
  let activeConversationId = null;
  let availableContacts = [];

  function getToken() {
    const token = localStorage.getItem('jwt_token');
    if (!token) throw new Error('Please sign in to continue.');
    return token;
  }

  async function apiRequest(path, options = {}) {
    const response = await fetch(`http://localhost:5000${path}`, {
      ...options,
      headers: {
        Authorization: 'Bearer ' + getToken(),
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || 'The request could not be completed.');
    return data;
  }

  function formatDate(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? ''
      : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
  }

  function renderNotices(target, notices) {
    target.replaceChildren();
    if (!notices.length) {
      const empty = document.createElement('p');
      empty.className = 'community-empty-state';
      empty.textContent = 'There are no notices yet.';
      target.appendChild(empty);
      return;
    }

    for (const notice of notices) {
      const article = document.createElement('article');
      article.className = 'community-post client-notice';
      const header = document.createElement('div');
      header.className = 'community-post-header';
      const identity = document.createElement('div');
      const title = document.createElement('h3');
      title.className = 'community-post-author';
      title.textContent = notice.title;
      const byline = document.createElement('time');
      byline.className = 'community-post-time';
      byline.textContent = `${notice.author_name} · ${notice.author_role.toUpperCase()} · ${formatDate(notice.created_at)}`;
      identity.append(title, byline);
      header.appendChild(identity);
      const body = document.createElement('p');
      body.className = 'community-post-content';
      body.textContent = notice.body;
      article.append(header, body);
      target.appendChild(article);
    }
  }

  async function loadNotices(role) {
    const target = role === 'client' ? clientNoticeFeed : staffNoticeFeed;
    const status = role === 'client' ? clientNoticeStatus : staffNoticeStatus;
    status.textContent = 'Loading client notices...';
    try {
      const data = await apiRequest('/api/portal/client-notices');
      renderNotices(target, data.notices);
      status.textContent = data.notices.length
        ? `${data.notices.length} current notice${data.notices.length === 1 ? '' : 's'}.`
        : 'No client notices have been published.';
    } catch (error) {
      status.textContent = error.message || 'Unable to load client notices.';
    }
  }

  function renderMessages(target, messages, currentUserId) {
    target.replaceChildren();
    if (!messages.length) {
      const empty = document.createElement('p');
      empty.className = 'community-empty-state';
      empty.textContent = 'No messages in this conversation yet. Send a message to begin.';
      target.appendChild(empty);
      return;
    }
    for (const message of messages) {
      const bubble = document.createElement('article');
      bubble.className = message.sender_id === currentUserId
        ? 'client-chat-bubble client-chat-outgoing'
        : 'client-chat-bubble client-chat-incoming';
      const sender = document.createElement('strong');
      sender.textContent = message.sender_name;
      const body = document.createElement('p');
      body.textContent = message.body;
      const time = document.createElement('time');
      time.textContent = formatDate(message.created_at);
      bubble.append(sender, body, time);
      target.appendChild(bubble);
    }
    target.scrollTop = target.scrollHeight;
  }

  async function openConversation(conversationId, role, peerName) {
    activeConversationId = conversationId;
    const target = role === 'client' ? clientMessageThread : staffMessageThread;
    const form = role === 'client' ? clientMessageForm : staffMessageForm;
    const status = role === 'client' ? clientMessageStatus : staffMessageStatus;
    const title = selectedThreadTitles[role];
    title.textContent = peerName || 'Conversation';
    target.replaceChildren();
    form.hidden = true;
    status.textContent = 'Loading conversation...';
    try {
      const data = await apiRequest(`/api/portal/client-conversations/${conversationId}/messages`);
      const user = window.DifanApp?.state?.currentUser || {};
      renderMessages(target, data.messages, Number(user.id));
      form.hidden = false;
      status.textContent = '';
    } catch (error) {
      status.textContent = error.message || 'Unable to load the conversation.';
    }
  }

  function renderConversations(target, conversations, role) {
    target.replaceChildren();
    if (!conversations.length) {
      const empty = document.createElement('p');
      empty.className = 'community-empty-state';
      empty.textContent = role === 'client'
        ? 'Start a private conversation with Admin, HR, or Accounts.'
        : 'No client conversations have been assigned to your account.';
      target.appendChild(empty);
      return;
    }
    for (const conversation of conversations) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'client-conversation-button';
      button.setAttribute('aria-pressed', String(conversation.id === activeConversationId));
      const name = document.createElement('strong');
      name.textContent = `${conversation.peer_name} · ${conversation.peer_role.toUpperCase()}`;
      const preview = document.createElement('span');
      preview.textContent = conversation.last_message || 'No messages yet';
      const updated = document.createElement('time');
      updated.textContent = formatDate(conversation.updated_at);
      button.append(name, preview, updated);
      button.addEventListener('click', () => {
        openConversation(conversation.id, role, conversation.peer_name);
      });
      target.appendChild(button);
    }
  }

  function updateContactOptions(selectedContact = '') {
    const selectedRole = clientMessageRole.value;
    clientMessageContact.replaceChildren(
      new Option(selectedRole ? 'Choose a contact' : 'Choose a role first', ''),
    );
    clientMessageContact.disabled = !selectedRole;
    for (const contact of availableContacts.filter((item) => item.role === selectedRole)) {
      clientMessageContact.add(new Option(contact.display_name, String(contact.id)));
    }
    if (availableContacts.some(
      (contact) => contact.role === selectedRole && String(contact.id) === selectedContact,
    )) {
      clientMessageContact.value = selectedContact;
    }
  }

  function updateStaffRecipientOptions(selectedContact = '') {
    if (!staffRecipient) return;
    staffRecipient.replaceChildren(new Option('Choose a client', ''));
    for (const contact of availableContacts) {
      staffRecipient.add(new Option(contact.display_name, String(contact.id)));
    }
    if (availableContacts.some((contact) => String(contact.id) === selectedContact)) {
      staffRecipient.value = selectedContact;
    }
  }

  async function loadConversations(role) {
    const target = role === 'client' ? clientConversationList : staffConversationList;
    const status = role === 'client' ? clientMessageStatus : staffMessageStatus;
    status.textContent = 'Loading conversations...';
    try {
      const data = await apiRequest('/api/portal/client-conversations');
      if (role === 'client') {
        const currentRole = clientMessageRole.value;
        const currentContact = clientMessageContact.value;
        availableContacts = data.contacts;
        clientMessageRole.value = currentRole;
        updateContactOptions(currentContact);
      } else {
        const currentRecipient = staffRecipient?.value || '';
        availableContacts = data.contacts;
        updateStaffRecipientOptions(currentRecipient);
      }
      renderConversations(target, data.conversations, role);
      const activeConversation = data.conversations.find((item) => item.id === activeConversationId);
      if (activeConversation) {
        await openConversation(activeConversation.id, role, activeConversation.peer_name);
      } else if (activeConversationId !== null) {
        activeConversationId = null;
        (role === 'client' ? clientMessageForm : staffMessageForm).hidden = true;
        selectedThreadTitles[role].textContent = role === 'client'
          ? 'Select a conversation'
          : 'Select a client conversation';
        (role === 'client' ? clientMessageThread : staffMessageThread).replaceChildren();
      }
      if (!activeConversationId) status.textContent = '';
    } catch (error) {
      status.textContent = error.message || 'Unable to load conversations.';
    }
  }

  function bindMessageForm(form, input, role) {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!activeConversationId) return;
      const sendButton = form.querySelector('button[type="submit"]');
      sendButton.disabled = true;
      const status = role === 'client' ? clientMessageStatus : staffMessageStatus;
      status.textContent = 'Sending message...';
      try {
        await apiRequest(`/api/portal/client-conversations/${activeConversationId}/messages`, {
          method: 'POST',
          body: JSON.stringify({ body: input.value }),
        });
        input.value = '';
        await loadConversations(role);
        status.textContent = 'Message sent.';
      } catch (error) {
        status.textContent = error.message || 'Unable to send the message.';
      } finally {
        sendButton.disabled = false;
      }
    });
  }

  const clientStartForm = document.getElementById('client-start-conversation-form');
  clientMessageRole.addEventListener('change', () => updateContactOptions());
  clientStartForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const contactId = Number(clientMessageContact.value);
    if (!Number.isInteger(contactId) || contactId < 1) return;
    clientMessageStatus.textContent = 'Opening private conversation...';
    try {
      const data = await apiRequest('/api/portal/client-conversations', {
        method: 'POST',
        body: JSON.stringify({ staff_user_id: contactId }),
      });
      activeConversationId = data.conversation.id;
      await loadConversations('client');
      await openConversation(data.conversation.id, 'client', data.conversation.peer_name);
    } catch (error) {
      clientMessageStatus.textContent = error.message || 'Unable to start the conversation.';
    }
  });

  staffStartForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const clientId = Number(staffRecipient.value);
    if (!Number.isInteger(clientId) || clientId < 1) return;
    staffMessageStatus.textContent = 'Opening private conversation...';
    try {
      const data = await apiRequest('/api/portal/client-conversations', {
        method: 'POST',
        body: JSON.stringify({ client_user_id: clientId }),
      });
      activeConversationId = data.conversation.id;
      await loadConversations('staff');
      await openConversation(data.conversation.id, 'staff', data.conversation.peer_name);
      staffMessageStatus.textContent = '';
    } catch (error) {
      staffMessageStatus.textContent = error.message || 'Unable to start the conversation.';
    }
  });

  const noticeForm = document.getElementById('client-notice-form');
  noticeForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submitButton = noticeForm.querySelector('button[type="submit"]');
    const title = document.getElementById('client-notice-title');
    const body = document.getElementById('client-notice-body');
    submitButton.disabled = true;
    staffNoticeStatus.textContent = 'Publishing notice...';
    try {
      await apiRequest('/api/portal/client-notices', {
        method: 'POST',
        body: JSON.stringify({ title: title.value, body: body.value }),
      });
      noticeForm.reset();
      await loadNotices('staff');
      staffNoticeStatus.textContent = 'Notice published to client dashboards.';
    } catch (error) {
      staffNoticeStatus.textContent = error.message || 'Unable to publish the notice.';
    } finally {
      submitButton.disabled = false;
    }
  });

  bindMessageForm(
    clientMessageForm,
    document.getElementById('client-message-input'),
    'client',
  );
  bindMessageForm(
    staffMessageForm,
    document.getElementById('staff-message-input'),
    'staff',
  );

  async function loadForCurrentUser() {
    const role = window.DifanApp?.state?.currentUser?.role;
    const isClient = role === 'client';
    const isStaff = allowedStaffRoles.has(role);
    section.hidden = !isClient && !isStaff;
    clientMessagesView.hidden = !isClient;
    staffMessagesView.hidden = !isStaff;
    messagesNavigation.hidden = !isClient && !isStaff;
    activeConversationId = null;
    if (!isClient && !isStaff) return;
    await loadNotices(isClient ? 'client' : 'staff');
    if (window.DifanApp?.state?.activeTab === 'messages') {
      await loadConversations(isClient ? 'client' : 'staff');
    }
  }

  messagesNavigation.addEventListener('click', () => {
    const role = window.DifanApp?.state?.currentUser?.role;
    if (role === 'client') loadConversations('client');
    else if (allowedStaffRoles.has(role)) loadConversations('staff');
  });
  document.querySelectorAll('[data-target-tab="messages"]').forEach((button) => {
    button.addEventListener('click', () => {
      const role = window.DifanApp?.state?.currentUser?.role;
      if (role === 'client') loadConversations('client');
      else if (allowedStaffRoles.has(role)) loadConversations('staff');
    });
  });
  if (staffInboxButton) {
    staffInboxButton.addEventListener('click', () => {
      const staffMessagesTab = document.querySelector('.nav-link[data-target-tab="messages"]');
      staffMessagesTab?.click();
    });
  }

  window.addEventListener('difan:session-ready', loadForCurrentUser);
  const user = window.DifanApp?.state?.currentUser;
  if (user?.id) loadForCurrentUser();
});
