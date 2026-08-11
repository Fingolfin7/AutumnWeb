/* ============================================================================
   AUTUMN — INSIGHTS PAGE BEHAVIOUR                            insights_page.js
   ----------------------------------------------------------------------------
   Lifted verbatim out of an inline <script> in insights.html (UI_REDESIGN.md
   chunk 12). Two hundred lines of behaviour inside a template could not be
   reviewed or diffed; the logic below is unchanged except that the five values
   Django used to interpolate now arrive as one JSON blob:

       <script id="insights-config" type="application/json"> … </script>

   which the page renders and this file parses. Everything else — the chat
   transcript builder, model/provider switching, message selection, the
   filters panel — is as it was.
   ==========================================================================*/
(function () {
  "use strict";

  var CONFIG = JSON.parse(document.getElementById('insights-config').textContent);
  var PROVIDER_MODELS = CONFIG.providerModels || {};
  var OPENAI_REASONING_EFFORTS = CONFIG.openaiReasoningEffortsByModel || {};
  function repopulateModels(provider, selectedModel){
      const modelSelect = $('#model');
      modelSelect.empty();
      const entries = PROVIDER_MODELS[provider] || [];
      entries.forEach(entry => {
          const opt = $('<option></option>').val(entry.value).text(entry.label);
          if (entry.value === selectedModel) opt.attr('selected','selected');
          modelSelect.append(opt);
      });
      if (!selectedModel && entries.length>0){
          modelSelect.val(entries[0].value);
      }
  }

  function repopulateReasoningEfforts(model, selectedEffort){
      const reasoningSelect = $('#reasoning_effort');
      const efforts = OPENAI_REASONING_EFFORTS[model] || [];
      reasoningSelect.empty();
      efforts.forEach(effort => {
          const label = effort === 'xhigh'
              ? 'Extra high'
              : effort.charAt(0).toUpperCase() + effort.slice(1);
          const opt = $('<option></option>').val(effort).text(label);
          if (effort === selectedEffort) opt.attr('selected', 'selected');
          reasoningSelect.append(opt);
      });
      if (!efforts.includes(selectedEffort)) {
          reasoningSelect.val(efforts.includes('high') ? 'high' : efforts[0]);
      }
      $('#reasoning_effort_filter').val(reasoningSelect.val() || '');
  }

  function updateReasoningEffortVisibility(provider){
      const reasoningField = $('#reasoning-effort-field');
      const reasoningSelect = $('#reasoning_effort');
      if (provider === 'openai') {
          reasoningField.show();
          reasoningSelect.prop('disabled', false);
          $('#reasoning_effort_filter').val(reasoningSelect.val());
      } else {
          reasoningField.hide();
          reasoningSelect.prop('disabled', true);
          $('#reasoning_effort_filter').val('');
      }
  }

  function copyToClipboard(text, btn) {
      navigator.clipboard.writeText(text).then(() => {
          const originalHtml = btn.innerHTML;
          btn.innerHTML = '<i class="fa fa-check"></i>';
          setTimeout(() => {
              btn.innerHTML = originalHtml;
          }, 2000);
      });
  }

  function buildChatTranscript(onlySelected) {
      const messages = [];
      const selector = onlySelected
          ? '.conversation-container > .msg-selected'
          : '.conversation-container > div';
      $(selector).each(function() {
          let sender = 'User';
          if ($(this).hasClass('user-message')) {
              sender = CONFIG.username;
          } else if ($(this).hasClass('assistant-message')) {
              const model = $(this).data('model') || CONFIG.selectedModel;
              sender = `Autumn (${model})`;
          }
          const content = $(this).find('.message-content').text().trim();
          if (content) {
              messages.push(`[${sender}]\n${content}`);
          }
      });
      return messages.join('\n\n---\n\n');
  }

  function flashCopied(btn) {
      const originalText = $(btn).html();
      $(btn).html('<i class="fa fa-check"></i> Copied!');
      setTimeout(() => $(btn).html(originalText), 2000);
  }

  function copyFullChat() {
      navigator.clipboard.writeText(buildChatTranscript(false)).then(() => {
          flashCopied(document.getElementById('copy-full-chat-btn'));
      });
  }

  let messageSelectMode = false;

  function updateSelectedCount() {
      const n = document.querySelectorAll('#conversation-container .msg-selected').length;
      const btn = $('#copy-selected-btn');
      btn.html('<i class="fa fa-copy"></i> Copy (' + n + ')');
      btn.prop('disabled', n === 0);
  }

  function toggleSelectMode() {
      messageSelectMode = !messageSelectMode;
      const container = document.getElementById('conversation-container');
      if (container) {
          container.classList.toggle('selecting', messageSelectMode);
          if (!messageSelectMode) {
              container.querySelectorAll('.msg-selected').forEach((m) => m.classList.remove('msg-selected'));
          }
      }
      $('#select-messages-btn').html(
          messageSelectMode
              ? '<i class="fa fa-times"></i> Cancel'
              : '<i class="fa fa-check-square"></i> Select'
      );
      $('#copy-selected-btn').toggle(messageSelectMode);
      updateSelectedCount();
  }

  function copySelectedMessages(btn) {
      const transcript = buildChatTranscript(true);
      if (!transcript) {
          return;
      }
      navigator.clipboard.writeText(transcript).then(() => flashCopied(btn));
  }

  /* `persist` is false when we are only reflecting the current screen rather
     than acting on a click — see the restore block below. */
  function setSidebarCollapsed(collapsed, persist) {
      $('.chat-sidebar').toggleClass('collapsed', collapsed);
      if (persist) {
          localStorage.setItem('chatSidebarCollapsed', collapsed);
      }
      const icon = $('#toggle-sidebar-btn i');
      icon.toggleClass('fa-chevron-right', collapsed);
      icon.toggleClass('fa-chevron-left', !collapsed);
  }

  function toggleSidebar() {
      setSidebarCollapsed(!$('.chat-sidebar').hasClass('collapsed'), true);
  }

  $(document).ready(function(){
      // Restore sidebar state. Below 700px the chat list is a drawer sitting
      // ON TOP of the transcript rather than beside it, so it starts closed
      // whatever the stored preference says — and without overwriting that
      // preference, which belongs to the wide layout.
      const narrow = window.matchMedia('(max-width: 700px)').matches;
      setSidebarCollapsed(
          narrow || localStorage.getItem('chatSidebarCollapsed') === 'true',
          false
      );

      // initial populate
      repopulateModels(CONFIG.selectedProvider, CONFIG.selectedModel);
      repopulateReasoningEfforts(
          CONFIG.selectedModel,
          $('#reasoning_effort').val()
      );
      updateReasoningEffortVisibility(CONFIG.selectedProvider);
      // keep GET filter hidden fields in sync
      $('#provider_filter').val($('#provider').val());
      $('#model_filter').val($('#model').val() || CONFIG.selectedModel);
      $('#reasoning_effort_filter').val(
          $('#reasoning_effort').prop('disabled') ? '' : $('#reasoning_effort').val()
      );

      $('#provider').on('change', function(){
          const newProvider = $(this).val();
          repopulateModels(newProvider,null);
          repopulateReasoningEfforts($('#model').val(), 'high');
          updateReasoningEffortVisibility(newProvider);
          $('#provider_filter').val(newProvider);
          $('#model_filter').val($('#model').val());
      });
      
      $('#model').on('change', function() {
          let selected = $(this).val();
          $('#model_filter').val(selected);
          repopulateReasoningEfforts(selected, $('#reasoning_effort').val());
      });

      $('#reasoning_effort').on('change', function() {
          $('#reasoning_effort_filter').val($(this).prop('disabled') ? '' : $(this).val());
      });

      // Scroll conversation to bottom
      const container = document.getElementById('conversation-container');
      if (container) {
          container.scrollTop = container.scrollHeight;
      }

      // Toggle message selection in select mode (delegated so it also
      // covers messages appended later by the streaming code)
      $(document).on('click', '#conversation-container > .user-message, #conversation-container > .assistant-message', function (e) {
          if (!messageSelectMode) {
              return;
          }
          e.preventDefault();
          $(this).toggleClass('msg-selected');
          updateSelectedCount();
      });

      // Composer: auto-grow textarea, Enter to send (Shift+Enter for newline)
      const promptEl = document.getElementById('prompt');
      const chatForm = document.getElementById('chat-form');
      if (promptEl) {
          const autogrow = () => {
              promptEl.style.height = 'auto';
              promptEl.style.height = Math.min(promptEl.scrollHeight, 176) + 'px';
          };
          promptEl.addEventListener('input', autogrow);
          autogrow();
          // Re-measure once everything (stylesheets included) has loaded,
          // in case autogrow first ran before focus_desk.css applied
          window.addEventListener('load', autogrow);

          promptEl.addEventListener('keydown', (e) => {
              if (e.key === 'Enter' && !e.shiftKey && !promptEl.readOnly) {
                  e.preventDefault();
                  if (chatForm && promptEl.value.trim()) {
                      chatForm.requestSubmit();
                  }
              }
          });

          if (chatForm) {
              // Reset height after the streaming handler clears the prompt
              chatForm.addEventListener('submit', () => setTimeout(autogrow, 0));
          }
      }
  });

  /* insights.html calls these five from inline onclick= attributes, so they
     have to be reachable from global scope. Everything else stays private to
     this module — that is the only reason the IIFE exists. */
  window.copyToClipboard = copyToClipboard;
  window.copyFullChat = copyFullChat;
  window.copySelectedMessages = copySelectedMessages;
  window.toggleSelectMode = toggleSelectMode;
  window.toggleSidebar = toggleSidebar;
  /* deleteChat is NOT exported here — it lives in insights_stream.js, which
     defines it globally and calls it itself. */
})();
