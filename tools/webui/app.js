    (function () {
      'use strict';

      // Minimal SVG Icons (Zero-Dependency)
      var ICONS = {
        search: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>',
        sparkles: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"></path></svg>',
        copy: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path></svg>',
        check: '<svg class="ui-icon icon-emerald" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"></polyline></svg>',
        download: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>',
        fileText: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>',
        externalLink: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>',
        alert: '<svg class="ui-icon icon-danger" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>',
        warning: '<svg class="ui-icon icon-amber" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>',
        clock: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>',
        sun: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2"></path><path d="M12 20v2"></path><path d="m4.93 4.93 1.41 1.41"></path><path d="m17.66 17.66 1.41 1.41"></path><path d="M2 12h2"></path><path d="M20 12h2"></path><path d="m6.34 17.66-1.41 1.41"></path><path d="m19.07 4.93-1.41 1.41"></path></svg>',
        moon: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"></path></svg>',
        zap: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>',
        play: '<svg class="ui-icon" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true"><polygon points="6 3 20 12 6 21 6 3"></polygon></svg>',
        image: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="18" height="18" x="3" y="3" rx="2" ry="2"></rect><circle cx="9" cy="9" r="2"></circle><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"></path></svg>'
      };

      function icon(name, extraClass) {
        var svg = ICONS[name] || '';
        if (extraClass && svg) {
          return svg.replace('class="ui-icon"', 'class="ui-icon ' + extraClass + '"');
        }
        return svg;
      }

      var state = {
        mode: 'deep',
        ctxTab: 'markdown',
        lastData: null,
        markdown: '',
        prompt: '',
        jsonStr: '',
        curlStr: '',
        maxTokens: 3000,
        classicCategory: '',
        classicTimeRange: '',
        classicPage: 1,
        classicCount: 10,
        settingsEngines: [],
        settingsCategories: [],
        settingsCurrentCat: '',
        settingsSearch: '',
        togglesModified: false,
        selectedCardIndex: -1
      };

      // AbortController for cancelable requests
      var currentAbortController = null;
      function cancelPendingRequest() {
        if (currentAbortController) {
          try { currentAbortController.abort(); } catch (e) {}
          currentAbortController = null;
        }
      }

      function escapeHtml(str) {
        return String(str == null ? '' : str)
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&#39;');
      }

      function safeHttpUrl(url) {
        var s = String(url == null ? '' : url).trim();
        if (!s) return '#';
        if (!/^https?:\/\//i.test(s)) return '#';
        try {
          var parsed = new URL(s);
          if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
            return parsed.href;
          }
        } catch (e) {}
        return '#';
      }

      function safeImageUrl(url) {
        var s = String(url == null ? '' : url).trim();
        if (!s) return '';
        if (/^data:image\/(?:png|jpeg|jpg|webp|gif);base64,[a-z0-9+/=]+$/i.test(s)) {
          return s;
        }
        var http = safeHttpUrl(s);
        return (http === '#') ? '' : http;
      }

      function escapeShellDoubleQuoted(str) {
        return String(str == null ? '' : str)
          .replace(/[\\$"\\`!]/g, function (ch) { return String.fromCharCode(92) + ch; });
      }

      function showToast(msg, isError) {
        var toast = document.getElementById('toast-notice');
        if (!toast) return;
        toast.innerHTML = (isError ? icon('alert') : icon('check')) + '<span>' + escapeHtml(msg) + '</span>';
        toast.style.background = isError ? 'var(--danger)' : 'var(--accent)';
        toast.classList.add('show');
        setTimeout(function () {
          toast.classList.remove('show');
        }, 2400);
      }

      function addListener(id, event, fn) {
        var el = document.getElementById(id);
        if (el) el.addEventListener(event, fn);
      }

      // Theme initialization
      var savedTheme = localStorage.getItem('sxng_ai_theme') || 'dark';
      document.documentElement.setAttribute('data-theme', savedTheme);
      function updateThemeIcon(t) {
        var btn = document.getElementById('theme-toggle-btn');
        if (!btn) return;
        var isDark = (t === 'dark');
        btn.innerHTML = (isDark ? icon('sun') : icon('moon')) + '<span>' + (isDark ? 'ライト' : 'ダーク') + '</span>';
      }
      updateThemeIcon(savedTheme);

      addListener('theme-toggle-btn', 'click', function () {
        var cur = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
        document.documentElement.setAttribute('data-theme', cur);
        localStorage.setItem('sxng_ai_theme', cur);
        updateThemeIcon(cur);
      });

      // Server status indicator: verify /healthz
      (function checkServerHealth() {
        var dot = document.getElementById('health-dot');
        if (!dot) return;
        fetch('/healthz')
          .then(function (r) {
            var online = r.ok;
            dot.setAttribute('aria-label', online ? 'Server Online' : 'Server Error');
            dot.setAttribute('title', online ? 'Server Online' : 'Server Error');
            if (!online) dot.style.background = 'var(--danger)';
          })
          .catch(function () {
            dot.setAttribute('aria-label', 'Server Offline');
            dot.setAttribute('title', 'Server Offline');
            dot.style.background = 'var(--danger)';
          });
      })();

      function isUrlText(text) {
        var s = (text || '').trim();
        return /^https?:\/\/\S+$/i.test(s);
      }

      function estimateTokens(text) {
        if (!text) return 0;
        var cjk = (text.match(/[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef]/g) || []).length;
        var other = text.length - cjk;
        return Math.round(cjk / 1.5 + other / 4.0);
      }

      function copyWithFeedback(text, btn, label) {
        if (!text) return;
        var orig = btn.innerHTML;
        var done = function () {
          btn.innerHTML = icon('check') + '<span>' + (label || 'コピー完了') + '</span>';
          setTimeout(function () { btn.innerHTML = orig; }, 1600);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done).catch(done);
        } else {
          var ta = document.createElement('textarea');
          ta.value = text;
          document.body.appendChild(ta);
          ta.select();
          try { document.execCommand('copy'); } catch (e) {}
          document.body.removeChild(ta);
          done();
        }
      }

      /* -------------------------------------------------------------
       * URL & Browser History Synchronization (pushState / popstate)
       * ------------------------------------------------------------- */
      function updateUrlState(replace) {
        var params = new URLSearchParams();
        var qVal = document.getElementById('q').value.trim();
        if (qVal) params.set('q', qVal);
        if (state.mode && state.mode !== 'deep') params.set('mode', state.mode);
        if (state.mode === 'deep') {
          var depth = document.getElementById('opt-depth').value;
          if (depth && depth !== 'advanced') params.set('depth', depth);
        } else if (state.mode === 'classic') {
          if (state.classicCategory) params.set('category', state.classicCategory);
          if (state.classicPage > 1) params.set('page', String(state.classicPage));
        }

        var qs = params.toString();
        var targetUrl = qs ? '/?' + qs : '/';
        var currentSearch = window.location.search || '';
        var targetSearch = qs ? '?' + qs : '';

        if (currentSearch !== targetSearch) {
          if (replace) {
            history.replaceState({ q: qVal, mode: state.mode, cat: state.classicCategory, page: state.classicPage }, '', targetUrl);
          } else {
            history.pushState({ q: qVal, mode: state.mode, cat: state.classicCategory, page: state.classicPage }, '', targetUrl);
          }
        }
      }

      window.addEventListener('popstate', function () {
        var p = new URLSearchParams(window.location.search);
        var q = p.get('q') || '';
        var m = p.get('mode') || 'deep';
        var cat = p.get('category') || p.get('categories') || '';
        var pg = parseInt(p.get('page') || '1', 10) || 1;
        var depth = p.get('depth') || 'advanced';

        document.getElementById('q').value = q;
        document.getElementById('opt-depth').value = depth;
        state.classicCategory = cat;
        state.classicPage = pg;

        document.querySelectorAll('#classic-cat-chips .cat-btn').forEach(function (b) {
          var active = (b.dataset.cat === cat);
          b.classList.toggle('active', active);
          b.setAttribute('aria-pressed', active ? 'true' : 'false');
        });

        setMode(m, true);
        if (q) {
          if (isUrlText(q)) runScrapeMode(q);
          else if (m === 'classic') runClassicSearch(q, pg);
          else runUnifiedSearch(q);
        }
      });

      /* -------------------------------------------------------------
       * Search History Management (localStorage)
       * ------------------------------------------------------------- */
      var HISTORY_STORAGE_KEY = 'sxng_query_history';
      function getQueryHistory() {
        try {
          return JSON.parse(localStorage.getItem(HISTORY_STORAGE_KEY) || '[]');
        } catch (e) {
          return [];
        }
      }
      function saveQueryHistory(query) {
        var q = (query || '').trim();
        if (!q || isUrlText(q)) return;
        var hist = getQueryHistory().filter(function (item) { return item !== q; });
        hist.unshift(q);
        if (hist.length > 8) hist = hist.slice(0, 8);
        try { localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(hist)); } catch (e) {}
        renderQueryHistory();
      }
      function renderQueryHistory() {
        var wrap = document.getElementById('recent-searches-wrap');
        if (!wrap) return;
        var hist = getQueryHistory();
        if (!hist.length) {
          wrap.style.display = 'none';
          wrap.innerHTML = '';
          return;
        }
        wrap.style.display = 'flex';
        wrap.innerHTML = '<span class="recent-label">' + icon('clock') + ' 最近の検索:</span>';
        hist.forEach(function (term) {
          var chip = document.createElement('button');
          chip.type = 'button';
          chip.className = 'recent-chip';
          chip.textContent = term;
          chip.addEventListener('click', function () {
            document.getElementById('q').value = term;
            executeCurrentAction();
          });
          wrap.appendChild(chip);
        });
        var clearBtn = document.createElement('button');
        clearBtn.type = 'button';
        clearBtn.className = 'recent-clear-btn';
        clearBtn.textContent = '履歴クリア';
        clearBtn.addEventListener('click', function () {
          localStorage.removeItem(HISTORY_STORAGE_KEY);
          renderQueryHistory();
        });
        wrap.appendChild(clearBtn);
      }
      renderQueryHistory();

      /* -------------------------------------------------------------
       * Autocompleter Suggest Dropdown (/autocompleter)
       * ------------------------------------------------------------- */
      var suggestBox = document.getElementById('suggest-box');
      var suggestDebounceTimer = null;
      var activeSuggestIndex = -1;

      function closeSuggest() {
        suggestBox.classList.remove('show');
        suggestBox.innerHTML = '';
        activeSuggestIndex = -1;
        var qEl = document.getElementById('q');
        if (qEl) {
          qEl.setAttribute('aria-expanded', 'false');
          qEl.removeAttribute('aria-activedescendant');
        }
      }

      function setActiveSuggestAria() {
        var qEl = document.getElementById('q');
        if (!qEl) return;
        qEl.setAttribute('aria-expanded', 'true');
        if (activeSuggestIndex >= 0) {
          var items = suggestBox.querySelectorAll('.suggest-item');
          if (items[activeSuggestIndex]) {
            qEl.setAttribute('aria-activedescendant', items[activeSuggestIndex].id);
          }
        } else {
          qEl.removeAttribute('aria-activedescendant');
        }
      }

      function extractSuggestions(data) {
        if (!data) return [];
        var raw = [];
        if (Array.isArray(data)) {
          // OpenSearch 5-tuple format: [query, [sug1, sug2, ...], ...]
          if (data.length >= 2 && Array.isArray(data[1])) {
            raw = data[1];
          } else {
            // Flat list format: [sug1, sug2, ...]
            raw = data;
          }
        } else if (typeof data === 'object' && Array.isArray(data.suggestions)) {
          raw = data.suggestions;
        }

        var results = [];
        var seen = Object.create(null);
        for (var i = 0; i < raw.length; i++) {
          var item = raw[i];
          if (typeof item === 'string') {
            var trimmed = item.trim();
            if (trimmed && trimmed !== '[object Object]' && !seen[trimmed]) {
              seen[trimmed] = true;
              results.push(trimmed);
            }
          }
        }
        return results;
      }

      function getActiveAutocompleteBackend() {
        var ac = localStorage.getItem('sxng_pref_autocomplete');
        if (ac) return ac;
        var sel = document.getElementById('pref-autocomplete');
        return sel ? sel.value : 'duckduckgo';
      }

      function fetchSuggestions(query) {
        if (!query || query.length < 2 || isUrlText(query) || getActiveAutocompleteBackend() === 'off') {
          closeSuggest();
          return;
        }
        fetch('/autocompleter?q=' + encodeURIComponent(query), {
          headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json'
          }
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            var curQ = document.getElementById('q').value.trim();
            if (!curQ || isUrlText(curQ)) {
              closeSuggest();
              return;
            }
            var list = extractSuggestions(data);
            if (!list.length) {
              closeSuggest();
              return;
            }
            suggestBox.innerHTML = '';
            activeSuggestIndex = -1;
            list.slice(0, 8).forEach(function (item, idx) {
              var div = document.createElement('div');
              div.className = 'suggest-item';
              div.setAttribute('role', 'option');
              div.id = 'suggest-opt-' + idx;
              div.setAttribute('aria-selected', 'false');
              div.innerHTML = icon('search') + '<span>' + escapeHtml(item) + '</span>';
              div.addEventListener('mousedown', function (e) {
                e.preventDefault();
                document.getElementById('q').value = item;
                closeSuggest();
                executeCurrentAction();
              });
              suggestBox.appendChild(div);
            });
            suggestBox.classList.add('show');
            setActiveSuggestAria();
          })
          .catch(function () { closeSuggest(); });
      }

      document.getElementById('q').addEventListener('input', function () {
        var val = this.value.trim();
        syncInputOptionsVisibility();
        clearTimeout(suggestDebounceTimer);
        suggestDebounceTimer = setTimeout(function () {
          fetchSuggestions(val);
        }, 180);
      });

      document.getElementById('q').addEventListener('keydown', function (e) {
        if (e.isComposing || e.keyCode === 229) return;
        var items = suggestBox.querySelectorAll('.suggest-item');
        if (!items.length || !suggestBox.classList.contains('show')) return;

        if (e.key === 'ArrowDown') {
          e.preventDefault();
          activeSuggestIndex = (activeSuggestIndex + 1) % items.length;
          items.forEach(function (el, i) {
            el.classList.toggle('active', i === activeSuggestIndex);
            el.setAttribute('aria-selected', i === activeSuggestIndex ? 'true' : 'false');
          });
          var selText = items[activeSuggestIndex].querySelector('span').textContent;
          document.getElementById('q').value = selText;
          setActiveSuggestAria();
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          activeSuggestIndex = (activeSuggestIndex - 1 + items.length) % items.length;
          items.forEach(function (el, i) {
            el.classList.toggle('active', i === activeSuggestIndex);
            el.setAttribute('aria-selected', i === activeSuggestIndex ? 'true' : 'false');
          });
          var selText2 = items[activeSuggestIndex].querySelector('span').textContent;
          document.getElementById('q').value = selText2;
          setActiveSuggestAria();
        } else if (e.key === 'Enter') {
          if (activeSuggestIndex >= 0 && items[activeSuggestIndex]) {
            e.preventDefault();
            var chosen = items[activeSuggestIndex].querySelector('span').textContent;
            document.getElementById('q').value = chosen;
            closeSuggest();
            executeCurrentAction();
          }
        } else if (e.key === 'Escape') {
          closeSuggest();
        }
      });

      document.addEventListener('click', function (e) {
        if (!document.getElementById('ws-form').contains(e.target)) {
          closeSuggest();
        }
      });

      /* -------------------------------------------------------------
       * UI Mode & Visibility Sync
       * ------------------------------------------------------------- */
      function syncInputOptionsVisibility() {
        if (state.mode === 'agent' || state.mode === 'settings') return;
        var qVal = document.getElementById('q').value.trim();
        var searchOpts = document.getElementById('search-options-row');
        var classicOpts = document.getElementById('classic-options-row');
        var scrapeOpts = document.getElementById('scrape-options-row');
        var runBtn = document.getElementById('run-btn');
        var isUrl = isUrlText(qVal);

        if (isUrl) {
          searchOpts.style.display = 'none';
          classicOpts.style.display = 'none';
          scrapeOpts.style.display = 'flex';
          runBtn.innerHTML = icon('fileText') + '<span>URL 本文抽出</span>';
        } else if (state.mode === 'classic') {
          searchOpts.style.display = 'none';
          classicOpts.style.display = 'flex';
          scrapeOpts.style.display = 'none';
          runBtn.innerHTML = icon('search') + '<span>検索</span>';
        } else {
          searchOpts.style.display = 'flex';
          classicOpts.style.display = 'none';
          scrapeOpts.style.display = 'none';
          var depthVal = document.getElementById('opt-depth').value;
          runBtn.innerHTML = (depthVal === 'fast')
            ? (icon('zap') + '<span>Fast Search</span>')
            : (icon('sparkles') + '<span>Deep Search</span>');
        }
      }

      function setMode(mode) {
        var skipHistory = arguments[1];
        state.mode = mode;
        state.selectedCardIndex = -1;
        document.querySelectorAll('.nav-tab').forEach(function (t) {
          var isSelected = (t.dataset.mode === mode);
          t.classList.toggle('active', isSelected);
          t.setAttribute('aria-selected', isSelected ? 'true' : 'false');
          t.setAttribute('tabindex', isSelected ? '0' : '-1');
        });

        var inputPanel = document.getElementById('input-panel');
        var mainSplit = document.getElementById('main-split-view');
        var classicView = document.getElementById('classic-search-view');
        var agentHub = document.getElementById('agent-hub-view');
        var settingsView = document.getElementById('settings-view');

        inputPanel.style.display = (mode === 'agent' || mode === 'settings') ? 'none' : 'block';
        mainSplit.style.display = (mode === 'deep') ? 'grid' : 'none';
        classicView.style.display = (mode === 'classic') ? 'block' : 'none';
        agentHub.style.display = (mode === 'agent') ? 'block' : 'none';
        settingsView.style.display = (mode === 'settings') ? 'block' : 'none';

        if (mode === 'agent') {
          loadAgentHub();
        } else if (mode === 'settings') {
          loadSettingsDashboard();
        } else {
          syncInputOptionsVisibility();
        }

        if (!skipHistory) {
          updateUrlState(false);
        }
      }

      document.getElementById('opt-depth').addEventListener('change', function () {
        syncInputOptionsVisibility();
        updateUrlState(true);
      });

      var navTabs = Array.prototype.slice.call(document.querySelectorAll('.nav-tab'));
      navTabs.forEach(function (btn, idx) {
        btn.addEventListener('click', function () {
          setMode(btn.dataset.mode);
        });
        btn.addEventListener('keydown', function (e) {
          if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
            e.preventDefault();
            var nextIdx = (idx + (e.key === 'ArrowRight' ? 1 : navTabs.length - 1)) % navTabs.length;
            navTabs[nextIdx].focus();
            setMode(navTabs[nextIdx].dataset.mode);
          }
        });
      });

      // Classic Category buttons
      document.querySelectorAll('#classic-cat-chips .cat-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
          document.querySelectorAll('#classic-cat-chips .cat-btn').forEach(function (b) {
            b.classList.remove('active');
            b.setAttribute('aria-pressed', 'false');
          });
          btn.classList.add('active');
          btn.setAttribute('aria-pressed', 'true');
          state.classicCategory = btn.dataset.cat || '';
          state.classicPage = 1;
          var qVal = document.getElementById('q').value.trim();
          if (qVal) {
            runClassicSearch(qVal, 1);
            updateUrlState(false);
          }
        });
      });

      document.querySelectorAll('.chip[data-preset]').forEach(function (chip) {
        chip.addEventListener('click', function () {
          var p = chip.dataset.preset;
          var siteInput = document.getElementById('opt-site');
          if (p === 'docs') siteInput.value = 'docs.python.org, developer.mozilla.org, react.dev, fastapi.tiangolo.com';
          else if (p === 'github') siteInput.value = 'github.com, stackoverflow.com';
          else if (p === 'academic') siteInput.value = 'arxiv.org, wikipedia.org';
          else if (p === 'clear') siteInput.value = '';
        });
      });

      document.querySelectorAll('.sample-q').forEach(function (chip) {
        chip.addEventListener('click', function () {
          document.getElementById('q').value = chip.dataset.q;
          setMode('deep');
          executeCurrentAction();
        });
      });

      document.querySelectorAll('.sample-classic-q').forEach(function (chip) {
        chip.addEventListener('click', function () {
          document.getElementById('q').value = chip.dataset.q;
          setMode('classic');
          executeCurrentAction();
        });
      });

      /* -------------------------------------------------------------
       * Lightweight Vanilla Markdown Preview Renderer
       * ------------------------------------------------------------- */
      function renderSimpleMarkdown(md) {
        if (!md) return '<p style="color:var(--text-muted);">(コンテキストが空です)</p>';
        var text = escapeHtml(md).replace(/\r\n/g, '\n');

        // 1. Extract fenced code blocks with unique tokens
        var codeBlocks = [];
        text = text.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, function (_, lang, code) {
          var token = '@@CODE_BLOCK_' + codeBlocks.length + '@@';
          codeBlocks.push('<pre><code class="lang-' + lang + '">' + code + '</code></pre>');
          return '\n\n' + token + '\n\n';
        });

        // 2. Extract inline code with tokens
        var inlineCodes = [];
        text = text.replace(/`([^`]+)`/g, function (_, code) {
          var token = '@@INLINE_CODE_' + inlineCodes.length + '@@';
          inlineCodes.push('<code>' + code + '</code>');
          return token;
        });

        // 3. Process blocks (split by double newlines)
        var rawBlocks = text.split(/\n{2,}/);
        var htmlBlocks = [];

        for (var i = 0; i < rawBlocks.length; i++) {
          var block = rawBlocks[i].trim();
          if (!block) continue;

          // Check if block is a preserved code block token
          if (/^@@CODE_BLOCK_\d+@@$/.test(block)) {
            htmlBlocks.push(block);
            continue;
          }

          // Check if block is heading
          if (/^### (.*$)/.test(block)) {
            htmlBlocks.push(block.replace(/^### (.*$)/, '<h3>$1</h3>'));
            continue;
          }
          if (/^## (.*$)/.test(block)) {
            htmlBlocks.push(block.replace(/^## (.*$)/, '<h2>$1</h2>'));
            continue;
          }
          if (/^# (.*$)/.test(block)) {
            htmlBlocks.push(block.replace(/^# (.*$)/, '<h1>$1</h1>'));
            continue;
          }

          // Check if block is blockquote
          if (/^&gt; (.*$)/m.test(block)) {
            var bqLines = block.split(/\n/).map(function (line) {
              return line.replace(/^&gt;\s?/, '');
            });
            htmlBlocks.push('<blockquote>' + bqLines.join('<br>') + '</blockquote>');
            continue;
          }

          // Check if block is an unordered list (lines starting with - or *)
          var lines = block.split(/\n/);
          var isList = lines.length > 0 && lines.every(function (l) { return /^[\-\*]\s+/.test(l.trim()); });
          if (isList) {
            var listItems = lines.map(function (l) {
              return '<li>' + l.trim().replace(/^[\-\*]\s+/, '') + '</li>';
            });
            htmlBlocks.push('<ul>' + listItems.join('') + '</ul>');
            continue;
          }

          // Regular paragraph: replace single newlines with <br>
          htmlBlocks.push('<p>' + block.replace(/\n/g, '<br>') + '</p>');
        }

        var fullHtml = htmlBlocks.join('\n');

        // 4. Bold & Italic (applied outside code blocks)
        fullHtml = fullHtml.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        fullHtml = fullHtml.replace(/\*([^*]+)\*/g, '<em>$1</em>');

        // 5. Links (handles escaped brackets in titles from escape_markdown_link)
        fullHtml = fullHtml.replace(/\[((?:\\\]|[^\]])+)\]\((https?:\/\/[^\s\)\"\']+)\)/g, function (_, label, rawUrl) {
          var cleanUrl = safeHttpUrl(rawUrl.replace(/&amp;/g, '&'));
          var displayLabel = label.replace(/\\([\[\]])/g, '$1');
          if (cleanUrl === '#') {
            return displayLabel;
          }
          return '<a href="' + escapeHtml(cleanUrl) + '" target="_blank" rel="noopener noreferrer">' + displayLabel + '</a>';
        });

        // 6. Restore code blocks and inline code (using function return to prevent $ pattern interpretation)
        for (var k = 0; k < codeBlocks.length; k++) {
          fullHtml = fullHtml.replace('@@CODE_BLOCK_' + k + '@@', function () { return codeBlocks[k]; });
        }
        for (var j = 0; j < inlineCodes.length; j++) {
          fullHtml = fullHtml.replace('@@INLINE_CODE_' + j + '@@', function () { return inlineCodes[j]; });
        }

        return fullHtml;
      }

      function updateContextView() {
        var ta = document.getElementById('ctx-output');
        var prev = document.getElementById('ctx-preview');

        if (state.ctxTab === 'preview') {
          ta.style.display = 'none';
          prev.style.display = 'block';
          prev.innerHTML = renderSimpleMarkdown(state.markdown || state.prompt || '');
        } else {
          prev.style.display = 'none';
          ta.style.display = 'block';
          if (state.ctxTab === 'markdown') ta.value = state.markdown || '';
          else if (state.ctxTab === 'prompt') ta.value = state.prompt || '';
          else if (state.ctxTab === 'json') ta.value = state.jsonStr || '';
          else if (state.ctxTab === 'curl') ta.value = state.curlStr || '';
        }

        var tok = estimateTokens(state.markdown || '');
        var budget = state.maxTokens || 3000;
        var pct = Math.min(100, Math.round((tok / Math.max(budget, 1)) * 100));
        document.getElementById('token-usage-label').textContent = '~' + tok + ' / ' + budget + ' tokens (' + pct + '%)';
        document.getElementById('token-bar-fill').style.width = pct + '%';
      }

      var ctxTabs = Array.prototype.slice.call(document.querySelectorAll('.ctx-tab'));
      function selectCtxTab(ctxName) {
        state.ctxTab = ctxName;
        ctxTabs.forEach(function (t) {
          var isSelected = (t.dataset.ctx === state.ctxTab);
          t.classList.toggle('active', isSelected);
          t.setAttribute('aria-selected', isSelected ? 'true' : 'false');
          t.setAttribute('tabindex', isSelected ? '0' : '-1');
        });
        updateContextView();
      }
      ctxTabs.forEach(function (tab, idx) {
        tab.addEventListener('click', function () {
          selectCtxTab(tab.dataset.ctx);
        });
        tab.addEventListener('keydown', function (e) {
          if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
            e.preventDefault();
            var nextIdx = (idx + (e.key === 'ArrowRight' ? 1 : ctxTabs.length - 1)) % ctxTabs.length;
            ctxTabs[nextIdx].focus();
            selectCtxTab(ctxTabs[nextIdx].dataset.ctx);
          }
        });
      });

      document.getElementById('ctx-copy-btn').addEventListener('click', function () {
        var val = (state.ctxTab === 'preview' || state.ctxTab === 'markdown') ? state.markdown : document.getElementById('ctx-output').value;
        copyWithFeedback(val, this, 'コピー完了');
      });
      document.getElementById('copy-md-main').addEventListener('click', function () {
        copyWithFeedback(state.markdown, this, 'Markdownコピー済');
      });
      document.getElementById('copy-prompt-main').addEventListener('click', function () {
        copyWithFeedback(state.prompt, this, 'プロンプトコピー済');
      });
      document.getElementById('copy-json-main').addEventListener('click', function () {
        copyWithFeedback(state.jsonStr, this, 'JSONコピー済');
      });
      document.getElementById('download-md-btn').addEventListener('click', function () {
        if (!state.markdown) return;
        var blob = new Blob([state.markdown], { type: 'text/markdown;charset=utf-8' });
        var objUrl = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = objUrl;
        a.download = 'searxng-context.md';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(function () { URL.revokeObjectURL(objUrl); }, 1000);
      });

      /* -------------------------------------------------------------
       * Skeleton Loader Renderer
       * ------------------------------------------------------------- */
      function renderSkeletonCards(container, count) {
        container.innerHTML = '';
        container.setAttribute('aria-busy', 'true');
        for (var i = 0; i < (count || 4); i++) {
          var card = document.createElement('div');
          card.className = 'skeleton-card';
          card.innerHTML =
            '<div class="skeleton-line meta"></div>' +
            '<div class="skeleton-line title"></div>' +
            '<div class="skeleton-line body1"></div>' +
            '<div class="skeleton-line body2"></div>';
          container.appendChild(card);
        }
      }

      function renderHighlights(container, highlights, fallbackContent) {
        var list = (highlights && highlights.length) ? highlights : (fallbackContent ? [fallbackContent] : []);
        list.forEach(function (h) {
          if (!h) return;
          if (h.indexOf('```') === 0) {
            var pre = document.createElement('pre');
            pre.className = 'highlight-code';
            pre.textContent = h.replace(/^```[a-zA-Z0-9_-]*\n?/, '').replace(/```$/, '');
            container.appendChild(pre);
          } else {
            var div = document.createElement('div');
            div.className = 'highlight-block';
            div.textContent = h;
            container.appendChild(div);
          }
        });
      }

      /* -------------------------------------------------------------
       * Deep Search Mode Result Cards
       * ------------------------------------------------------------- */
      function renderSearchResults(items, query) {
        var container = document.getElementById('results-container');
        container.innerHTML = '';
        state.selectedCardIndex = -1;

        if (!items || !items.length) {
          var empty = document.createElement('div');
          empty.className = 'empty-state';
          empty.innerHTML = '<h2>検索結果が見つかりませんでした</h2><p>別のキーワードまたはフィルタ条件でお試しください。</p>';
          container.appendChild(empty);
          return;
        }

        items.forEach(function (item, idx) {
          var card = document.createElement('article');
          card.className = 'result-card';
          card.dataset.index = String(idx);

          var top = document.createElement('div');
          top.className = 'card-top';

          var leftMeta = document.createElement('div');
          leftMeta.style.display = 'flex';
          leftMeta.style.alignItems = 'center';
          leftMeta.style.gap = '0.5rem';

          var rankSpan = document.createElement('span');
          rankSpan.className = 'card-rank';
          rankSpan.textContent = '[' + (idx + 1) + ']';

          var domainWrap = document.createElement('span');
          domainWrap.className = 'card-domain-wrap';

          var domain = item.domain || (function () {
            try { return new URL(item.url).hostname.replace(/^www\./, ''); } catch (e) { return ''; }
          })();

          if (domain) {
            var fav = document.createElement('img');
            fav.className = 'card-favicon';
            fav.src = 'https://www.google.com/s2/favicons?domain=' + encodeURIComponent(domain) + '&sz=32';
            fav.alt = '';
            fav.loading = 'lazy';
            fav.onerror = function () { this.style.display = 'none'; };
            domainWrap.appendChild(fav);
          }

          var domSpan = document.createElement('span');
          domSpan.className = 'card-domain';
          domSpan.textContent = domain;
          domainWrap.appendChild(domSpan);

          leftMeta.appendChild(rankSpan);
          leftMeta.appendChild(domainWrap);

          var badges = document.createElement('div');
          badges.className = 'card-badges';

          if (typeof item.score === 'number' && item.score > 0) {
            var scorePill = document.createElement('span');
            scorePill.className = 'pill ' + (item.score >= 1.5 ? 'pill-emerald' : 'pill-accent');
            scorePill.textContent = 'Score ' + item.score.toFixed(2);
            badges.appendChild(scorePill);
          }
          if (item.is_scraped) {
            var scPill = document.createElement('span');
            scPill.className = 'pill pill-emerald';
            scPill.innerHTML = icon('check', 'ui-icon-sm') + '<span>本文抽出済</span>';
            badges.appendChild(scPill);
          } else if (item.source || item.engine) {
            var srcPill = document.createElement('span');
            srcPill.className = 'pill';
            srcPill.textContent = item.source || item.engine;
            badges.appendChild(srcPill);
          }

          top.appendChild(leftMeta);
          top.appendChild(badges);
          card.appendChild(top);

          var titleEl = document.createElement('div');
          titleEl.className = 'card-title';
          var link = document.createElement('a');
          link.href = safeHttpUrl(item.url);
          link.target = '_blank';
          link.rel = 'noopener noreferrer';
          link.textContent = item.title || item.url;
          titleEl.appendChild(link);
          card.appendChild(titleEl);

          var hlWrap = document.createElement('div');
          renderHighlights(hlWrap, item.highlights, item.content);
          card.appendChild(hlWrap);

          var actions = document.createElement('div');
          actions.className = 'card-actions';

          var drawerId = 'deep-scrape-drawer-' + idx;
          var scrapeBtn = document.createElement('button');
          scrapeBtn.type = 'button';
          scrapeBtn.className = 'btn btn-sm';
          scrapeBtn.innerHTML = icon('fileText') + '<span>本文抽出</span>';
          scrapeBtn.setAttribute('aria-expanded', 'false');
          scrapeBtn.setAttribute('aria-controls', drawerId);
          scrapeBtn.addEventListener('click', function () {
            var existing = card.querySelector('.inline-scrape-drawer');
            if (existing) {
              var isHidden = existing.style.display === 'none';
              existing.style.display = isHidden ? 'block' : 'none';
              scrapeBtn.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
              return;
            }
            var drawer = document.createElement('div');
            drawer.className = 'inline-scrape-drawer';
            drawer.id = drawerId;
            drawer.innerHTML = '<span class="ui-spinner"></span> URLから本文を抽出中...';
            card.appendChild(drawer);
            scrapeBtn.setAttribute('aria-expanded', 'true');
            fetch('/api/scrape_analyze?url=' + encodeURIComponent(item.url) + '&q=' + encodeURIComponent(query || ''))
              .then(function (r) { return r.json(); })
              .then(function (res) {
                if (res.error) {
                  drawer.innerHTML = icon('alert') + ' 抽出失敗: ' + escapeHtml(res.error);
                  return;
                }
                drawer.textContent = res.content || '(本文なし)';
              })
              .catch(function (e) {
                drawer.innerHTML = icon('alert') + ' 通信エラー: ' + escapeHtml(e);
              });
          });

          var copyItemBtn = document.createElement('button');
          copyItemBtn.type = 'button';
          copyItemBtn.className = 'btn btn-sm';
          copyItemBtn.setAttribute('aria-label', '引用をコピー');
          copyItemBtn.setAttribute('data-action', 'copy-citation');
          copyItemBtn.innerHTML = icon('copy') + '<span>引用コピー</span>';
          copyItemBtn.addEventListener('click', function () {
            var safeTitle = (item.title || item.url || '').split('[').join('\\[').split(']').join('\\]');
            var safeUrl = (item.url || '').split('(').join('%28').split(')').join('%29');
            var hText = (item.highlights && item.highlights.length) ? item.highlights.join('\n\n') : (item.content || '');
            var citeMd = '### [' + (idx + 1) + '] [' + safeTitle + '](' + safeUrl + ')\n> ' + hText.replace(/\n/g, '\n> ');
            copyWithFeedback(citeMd, copyItemBtn, 'コピー完了');
          });

          actions.appendChild(scrapeBtn);
          actions.appendChild(copyItemBtn);

          if (domain) {
            var filterDomBtn = document.createElement('button');
            filterDomBtn.type = 'button';
            filterDomBtn.className = 'btn btn-sm';
            filterDomBtn.textContent = 'site:' + domain;
            filterDomBtn.addEventListener('click', function () {
              document.getElementById('opt-site').value = domain;
              if (state.mode !== 'deep') setMode('deep');
              executeCurrentAction();
            });
            actions.appendChild(filterDomBtn);
          }

          card.appendChild(actions);
          container.appendChild(card);
        });
      }

      function runUnifiedSearch(query) {
        cancelPendingRequest();
        currentAbortController = new AbortController();
        var signal = currentAbortController.signal;

        var depth = document.getElementById('opt-depth').value;
        var count = document.getElementById('opt-count').value;
        var maxTok = parseInt(document.getElementById('opt-tokens').value, 10) || 3000;
        var siteVal = document.getElementById('opt-site').value.trim();
        state.maxTokens = maxTok;

        var container = document.getElementById('results-container');
        renderSkeletonCards(container, parseInt(count, 10) || 4);

        saveQueryHistory(query);
        closeSuggest();

        var params = new URLSearchParams({
          q: query,
          depth: depth,
          max_results: count,
          max_tokens: String(maxTok)
        });
        if (siteVal) params.set('site', siteVal);

        var url = '/deep_search?' + params.toString();
        var origin = window.location.origin;
        state.curlStr = 'curl -sG "' + origin + '/deep_search" --data-urlencode "q=' + escapeShellDoubleQuoted(query) + '" --data-urlencode "depth=' + escapeShellDoubleQuoted(depth) + '" --data-urlencode "format=markdown"';

        fetch(url, { signal: signal })
          .then(function (r) { return r.json(); })
          .then(function (res) {
            container.setAttribute('aria-busy', 'false');
            var telBar = document.getElementById('telemetry-bar');
            if (res.error && (!res.results || !res.results.length)) {
              if (telBar) telBar.classList.remove('visible');
              container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">' + icon('alert') + ' エラー</h2><p>' + escapeHtml(res.error) + '</p></div>';
              return;
            }
            state.markdown = res.markdown || '';
            state.prompt = res.rag_prompt || '';
            state.jsonStr = JSON.stringify(res, null, 2);

            var badges = document.getElementById('telemetry-badges');
            if (telBar) telBar.classList.add('visible');
            if (badges) {
              badges.innerHTML =
                '<span class="pill pill-accent">' + escapeHtml(res.search_depth || depth) + ' (' + escapeHtml(res.intent || 'general') + ')</span>' +
                '<span class="pill pill-emerald">' + escapeHtml(res.results_count || 0) + '件 (本文抽出: ' + escapeHtml(res.scraped_count || 0) + '件)</span>' +
                '<span class="pill">~' + escapeHtml(res.estimated_tokens || 0) + ' tokens</span>' +
                '<span class="pill">' + escapeHtml(res.elapsed_ms || 0) + ' ms</span>';
            }

            renderSearchResults(res.results || [], query);
            updateContextView();
            updateUrlState(false);
          })
          .catch(function (err) {
            if (err.name === 'AbortError') return;
            container.setAttribute('aria-busy', 'false');
            var telBar = document.getElementById('telemetry-bar');
            if (telBar) telBar.classList.remove('visible');
            container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">' + icon('alert') + ' 通信エラー</h2><p>' + escapeHtml(err) + '</p></div>';
          });
      }

      /* -------------------------------------------------------------
       * Classic Search Mode Implementation (Text & Image Gallery)
       * ------------------------------------------------------------- */
      function updateClassicPagination(page, items) {
        var pagBar = document.getElementById('classic-pagination-bar');
        if (!pagBar) return;
        pagBar.style.display = 'flex';
        var countVal = parseInt((document.getElementById('classic-count') || {}).value || '10', 10);
        if (isNaN(countVal) || countVal < 1) countVal = 10;
        var maxPages = 10;
        var isLastPage = (items.length < countVal);
        var totalPages = isLastPage ? Math.max(page, 1) : Math.max(page, maxPages);

        var indicator = document.getElementById('classic-page-indicator');
        if (indicator) {
          indicator.textContent = 'ページ ' + page + ' / ' + totalPages;
        }

        var prevBtn = document.getElementById('classic-prev-btn');
        if (prevBtn) prevBtn.disabled = (page <= 1);
        var nextBtn = document.getElementById('classic-next-btn');
        if (nextBtn) document.getElementById('classic-next-btn').disabled = (items.length < countVal) || (page >= totalPages);
      }

      function renderClassicSearchResults(items, query, page) {
        var container = document.getElementById('classic-results-container');
        container.innerHTML = '';
        state.selectedCardIndex = -1;

        if (!items || !items.length) {
          container.innerHTML = '<div class="empty-state"><h2>検索結果が見つかりませんでした</h2><p>キーワードを変更するか、カテゴリーフィルターを切り替えてみてください。</p></div>';
          document.getElementById('classic-pagination-bar').style.display = 'none';
          return;
        }

        // Image grid mode
        if (state.classicCategory === 'images') {
          var grid = document.createElement('div');
          grid.className = 'image-results-grid';
          items.forEach(function (item) {
            var card = document.createElement('article');
            card.className = 'image-card';

            var thumbWrap = document.createElement('a');
            thumbWrap.className = 'image-card-thumb-wrap';
            thumbWrap.href = safeHttpUrl(item.url);
            thumbWrap.target = '_blank';
            thumbWrap.rel = 'noopener noreferrer';
            thumbWrap.title = item.title || '';

            var thumbSrc = item.thumbnail_src || item.thumbnail;
            var fullSrc = item.img_src || thumbSrc;
            var displaySrc = thumbSrc || fullSrc;

            if (displaySrc) {
              var safeSrc = safeImageUrl(displaySrc);
              if (safeSrc) {
                var img = document.createElement('img');
                img.className = 'image-card-thumb';
                img.src = safeSrc;
                img.alt = item.title || '';
                img.loading = 'lazy';
                img.referrerPolicy = 'no-referrer';
                img.onerror = function () {
                  if (fullSrc && safeSrc !== safeImageUrl(fullSrc)) {
                    this.src = safeImageUrl(fullSrc);
                  } else {
                    this.style.display = 'none';
                    if (!thumbWrap.querySelector('.image-card-placeholder')) {
                      var ph = document.createElement('div');
                      ph.className = 'image-card-placeholder';
                      ph.innerHTML = icon('image') + '<span>画像を表示できません</span>';
                      thumbWrap.appendChild(ph);
                    }
                  }
                };
                thumbWrap.appendChild(img);
              }
            } else {
              var ph = document.createElement('div');
              ph.className = 'image-card-placeholder';
              ph.innerHTML = icon('image') + '<span>画像プレビューなし</span>';
              thumbWrap.appendChild(ph);
            }

            if (item.resolution) {
              var resBadge = document.createElement('span');
              resBadge.className = 'image-res-badge';
              resBadge.textContent = item.resolution;
              thumbWrap.appendChild(resBadge);
            }

            var body = document.createElement('div');
            body.className = 'image-card-body';

            var a = document.createElement('a');
            a.className = 'image-card-title';
            a.href = safeHttpUrl(item.url);
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
            a.textContent = item.title || item.url;

            var domRow = document.createElement('div');
            domRow.className = 'image-card-meta';

            var dom = document.createElement('span');
            dom.className = 'image-card-domain';
            dom.textContent = item.domain || (function () {
              try { return new URL(item.url).hostname.replace(/^www\./, ''); } catch (e) { return ''; }
            })();

            domRow.appendChild(dom);

            if (item.img_src) {
              var fullLink = document.createElement('a');
              fullLink.className = 'image-full-link';
              fullLink.href = safeHttpUrl(item.img_src);
              fullLink.target = '_blank';
              fullLink.rel = 'noopener noreferrer';
              fullLink.title = '元画像を別タブで開く';
              fullLink.setAttribute('aria-label', '元画像を別タブで開く');
              fullLink.innerHTML = icon('externalLink');
              domRow.appendChild(fullLink);
            }

            body.appendChild(a);
            body.appendChild(domRow);

            card.appendChild(thumbWrap);
            card.appendChild(body);
            grid.appendChild(card);
          });
          container.appendChild(grid);

          updateClassicPagination(page, items);
          return;
        }

        // Dedicated Video list mode
        if (state.classicCategory === 'videos') {
          var vList = document.createElement('div');
          vList.className = 'video-results-list';
          items.forEach(function (item, idx) {
            var card = document.createElement('article');
            card.className = 'video-card';
            card.dataset.index = String(idx);

            var thumbWrap = document.createElement('a');
            thumbWrap.className = 'video-thumb-wrap';
            thumbWrap.href = safeHttpUrl(item.url);
            thumbWrap.target = '_blank';
            thumbWrap.rel = 'noopener noreferrer';
            thumbWrap.title = item.title || '';

            var videoThumb = item.thumbnail || item.thumbnail_src || item.img_src;
            if (!videoThumb) {
              var yt = (item.url || '').match(/(?:youtube\.com\/(?:watch\?v=|shorts\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})/);
              if (yt) videoThumb = 'https://i.ytimg.com/vi/' + yt[1] + '/hqdefault.jpg';
            }

            if (videoThumb) {
              var safeSrc = safeImageUrl(videoThumb);
              if (safeSrc) {
                var img = document.createElement('img');
                img.className = 'video-thumb-img';
                img.src = safeSrc;
                img.alt = item.title || '';
                img.loading = 'lazy';
                img.referrerPolicy = 'no-referrer';
                img.onerror = function () {
                  this.style.display = 'none';
                  if (!thumbWrap.querySelector('.video-thumb-placeholder')) {
                    var ph = document.createElement('div');
                    ph.className = 'video-thumb-placeholder';
                    ph.innerHTML = icon('play') + '<span>動画プレビュー</span>';
                    thumbWrap.appendChild(ph);
                  }
                };
                thumbWrap.appendChild(img);
              }
            } else {
              var ph = document.createElement('div');
              ph.className = 'video-thumb-placeholder';
              ph.innerHTML = icon('play') + '<span>動画</span>';
              thumbWrap.appendChild(ph);
            }

            var playOverlay = document.createElement('div');
            playOverlay.className = 'video-play-overlay';
            playOverlay.innerHTML = icon('play');
            thumbWrap.appendChild(playOverlay);

            if (item.length) {
              var durBadge = document.createElement('span');
              durBadge.className = 'video-duration-badge';
              durBadge.textContent = item.length;
              thumbWrap.appendChild(durBadge);
            }

            var contentDiv = document.createElement('div');
            contentDiv.className = 'video-card-content';

            var metaRow = document.createElement('div');
            metaRow.className = 'classic-meta-row';

            var urlSpan = document.createElement('span');
            urlSpan.className = 'classic-url-tag';
            var domain = item.domain || (function () {
              try { return new URL(item.url).hostname.replace(/^www\./, ''); } catch (e) { return ''; }
            })();
            if (domain) {
              var fav = document.createElement('img');
              fav.className = 'card-favicon';
              fav.src = 'https://www.google.com/s2/favicons?domain=' + encodeURIComponent(domain) + '&sz=32';
              fav.alt = '';
              fav.loading = 'lazy';
              fav.onerror = function () { this.style.display = 'none'; };
              urlSpan.appendChild(fav);
            }
            var dName = document.createElement('span');
            dName.textContent = domain || item.url;
            urlSpan.appendChild(dName);

            var badgeGroup = document.createElement('div');
            badgeGroup.style.display = 'flex';
            badgeGroup.style.gap = '0.35rem';

            var engName = item.engine || item.source;
            if (engName) {
              var engPill = document.createElement('span');
              engPill.className = 'pill pill-accent';
              engPill.textContent = engName;
              badgeGroup.appendChild(engPill);
            }

            metaRow.appendChild(urlSpan);
            metaRow.appendChild(badgeGroup);
            contentDiv.appendChild(metaRow);

            var titleLink = document.createElement('a');
            titleLink.className = 'video-title-link';
            titleLink.href = safeHttpUrl(item.url);
            titleLink.target = '_blank';
            titleLink.rel = 'noopener noreferrer';
            titleLink.textContent = item.title || item.url;
            contentDiv.appendChild(titleLink);

            if (item.content) {
              var descDiv = document.createElement('div');
              descDiv.className = 'video-snippet-text';
              descDiv.textContent = item.content;
              contentDiv.appendChild(descDiv);
            }

            var actRow = document.createElement('div');
            actRow.className = 'classic-actions-row';

            var watchBtn = document.createElement('a');
            watchBtn.className = 'btn btn-sm btn-primary';
            watchBtn.href = safeHttpUrl(item.url);
            watchBtn.target = '_blank';
            watchBtn.rel = 'noopener noreferrer';
            watchBtn.setAttribute('aria-label', '動画を新しいタブで再生');
            watchBtn.innerHTML = icon('play') + '<span>動画を再生</span>';
            actRow.appendChild(watchBtn);

            var copyBtn = document.createElement('button');
            copyBtn.type = 'button';
            copyBtn.className = 'btn btn-sm';
            copyBtn.setAttribute('aria-label', '動画URLをコピー');
            copyBtn.setAttribute('data-action', 'copy-citation');
            copyBtn.innerHTML = icon('copy') + '<span>URLコピー</span>';
            copyBtn.addEventListener('click', function () {
              var safeTitle = (item.title || item.url || '').split('[').join('\\[').split(']').join('\\]');
              var safeUrl = (item.url || '').split('(').join('%28').split(')').join('%29');
              var citeText = '[' + safeTitle + '](' + safeUrl + ')';
              copyWithFeedback(citeText, copyBtn, 'コピー済');
            });
            actRow.appendChild(copyBtn);

            contentDiv.appendChild(actRow);

            card.appendChild(thumbWrap);
            card.appendChild(contentDiv);
            vList.appendChild(card);
          });
          container.appendChild(vList);

          updateClassicPagination(page, items);
          return;
        }

        // Standard 1-column list
        items.forEach(function (item, idx) {
          var card = document.createElement('article');
          card.className = 'classic-card';
          card.dataset.index = String(idx);

          var metaRow = document.createElement('div');
          metaRow.className = 'classic-meta-row';

          var urlSpan = document.createElement('span');
          urlSpan.className = 'classic-url-tag';
          var domain = item.domain || (function () {
            try { return new URL(item.url).hostname.replace(/^www\./, ''); } catch (e) { return ''; }
          })();

          if (domain) {
            var fav = document.createElement('img');
            fav.className = 'card-favicon';
            fav.src = 'https://www.google.com/s2/favicons?domain=' + encodeURIComponent(domain) + '&sz=32';
            fav.alt = '';
            fav.loading = 'lazy';
            fav.onerror = function () { this.style.display = 'none'; };
            urlSpan.appendChild(fav);
          }
          var dName = document.createElement('span');
          dName.textContent = domain || item.url;
          urlSpan.appendChild(dName);

          var badgeGroup = document.createElement('div');
          badgeGroup.style.display = 'flex';
          badgeGroup.style.gap = '0.35rem';

          var engName = item.engine || item.source;
          if (engName) {
            var engPill = document.createElement('span');
            engPill.className = 'pill pill-accent';
            engPill.textContent = engName;
            badgeGroup.appendChild(engPill);
          }

          metaRow.appendChild(urlSpan);
          metaRow.appendChild(badgeGroup);
          card.appendChild(metaRow);

          var titleLink = document.createElement('a');
          titleLink.className = 'classic-title-link';
          titleLink.href = safeHttpUrl(item.url);
          titleLink.target = '_blank';
          titleLink.rel = 'noopener noreferrer';
          titleLink.textContent = item.title || item.url;
          card.appendChild(titleLink);

          var snippetDiv = document.createElement('div');
          snippetDiv.className = 'classic-snippet-text';
          snippetDiv.textContent = item.content || '(スニペットなし)';
          card.appendChild(snippetDiv);

          var actRow = document.createElement('div');
          actRow.className = 'classic-actions-row';

          var scrapeBtn = document.createElement('button');
          scrapeBtn.type = 'button';
          scrapeBtn.className = 'btn btn-sm';
          scrapeBtn.innerHTML = icon('fileText') + '<span>本文抽出</span>';
          var drawerId = 'classic-scrape-drawer-' + idx;
          scrapeBtn.setAttribute('aria-expanded', 'false');
          scrapeBtn.setAttribute('aria-controls', drawerId);
          scrapeBtn.addEventListener('click', function () {
            var ex = card.querySelector('.inline-scrape-drawer');
            if (ex) {
              var isHidden = ex.style.display === 'none';
              ex.style.display = isHidden ? 'block' : 'none';
              scrapeBtn.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
              return;
            }
            var d = document.createElement('div');
            d.className = 'inline-scrape-drawer';
            d.id = drawerId;
            d.innerHTML = '<span class="ui-spinner"></span> URL本文を抽出中...';
            card.appendChild(d);
            scrapeBtn.setAttribute('aria-expanded', 'true');
            fetch('/api/scrape_analyze?url=' + encodeURIComponent(item.url) + '&q=' + encodeURIComponent(query || ''))
              .then(function (r) { return r.json(); })
              .then(function (res) {
                if (res.error) {
                  d.innerHTML = icon('alert') + ' 抽出エラー: ' + escapeHtml(res.error);
                } else {
                  d.textContent = res.content || '(本文なし)';
                }
              })
              .catch(function (e) { d.innerHTML = icon('alert') + ' 抽出エラー: ' + escapeHtml(e); });
          });

          var copyBtn = document.createElement('button');
          copyBtn.type = 'button';
          copyBtn.className = 'btn btn-sm';
          copyBtn.setAttribute('aria-label', '引用をコピー');
          copyBtn.setAttribute('data-action', 'copy-citation');
          copyBtn.innerHTML = icon('copy') + '<span>引用コピー</span>';
          copyBtn.addEventListener('click', function () {
            var safeTitle = (item.title || item.url || '').split('[').join('\\[').split(']').join('\\]');
            var safeUrl = (item.url || '').split('(').join('%28').split(')').join('%29');
            var citeText = '### [' + safeTitle + '](' + safeUrl + ')\n> ' + (item.content || '').replace(/\n/g, '\n> ');
            copyWithFeedback(citeText, copyBtn, 'コピー済');
          });

          actRow.appendChild(scrapeBtn);
          actRow.appendChild(copyBtn);
          card.appendChild(actRow);

          container.appendChild(card);
        });

        // Pagination
        updateClassicPagination(page, items);
      }

      function runClassicSearch(query, page) {
        cancelPendingRequest();
        currentAbortController = new AbortController();
        var signal = currentAbortController.signal;

        page = page || 1;
        state.classicPage = page;
        var cat = state.classicCategory || '';
        var tr = document.getElementById('classic-time-range').value || '';
        var count = document.getElementById('classic-count').value || '10';

        var container = document.getElementById('classic-results-container');
        var telPill = document.getElementById('classic-telemetry-pill');
        renderSkeletonCards(container, parseInt(count, 10) || 5);

        saveQueryHistory(query);
        closeSuggest();

        var params = new URLSearchParams({
          q: query,
          mode: 'classic',
          categories: cat,
          category: cat,
          time_range: tr,
          count: count,
          page: String(page)
        });

        fetch('/deep_search?' + params.toString(), { signal: signal })
          .then(function (r) { return r.json(); })
          .then(function (res) {
            container.setAttribute('aria-busy', 'false');
            var ansContainer = document.getElementById('classic-answers-container');
            var pagBar = document.getElementById('classic-pagination-bar');
            if (res.error && (!res.results || !res.results.length)) {
              if (telPill) telPill.style.display = 'none';
              if (ansContainer) ansContainer.innerHTML = '';
              if (pagBar) pagBar.style.display = 'none';
              container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">' + icon('alert') + ' エラー</h2><p>' + escapeHtml(res.error) + '</p></div>';
              return;
            }
            if (telPill) {
              telPill.style.display = 'block';
              telPill.innerHTML = '取得: ' + escapeHtml(res.results_count || 0) + '件 (' + escapeHtml(res.elapsed_ms || 0) + ' ms)' +
                (cat ? ' &middot; カテゴリー: ' + escapeHtml(cat) : '') +
                (tr ? ' &middot; 期間: ' + escapeHtml(tr) : '');
            }

            // Direct answers box
            if (ansContainer) {
              ansContainer.innerHTML = '';
              if (res.answers && res.answers.length) {
                res.answers.forEach(function (a) {
                  var ansText = '';
                  if (typeof a === 'string') {
                    ansText = a;
                  } else if (a && typeof a === 'object') {
                    ansText = a.answer || a.text || a.content || JSON.stringify(a);
                  } else {
                    ansText = String(a || '');
                  }
                  var abox = document.createElement('div');
                  abox.className = 'classic-answer-box';
                  abox.innerHTML = '<strong>ダイレクトアンサー:</strong><br>' + escapeHtml(ansText);
                  ansContainer.appendChild(abox);
                });
              }
            }

            renderClassicSearchResults(res.results || [], query, page);
            updateUrlState(false);
          })
          .catch(function (err) {
            if (err.name === 'AbortError') return;
            container.setAttribute('aria-busy', 'false');
            if (telPill) telPill.style.display = 'none';
            var ansContainer = document.getElementById('classic-answers-container');
            if (ansContainer) ansContainer.innerHTML = '';
            var pagBar = document.getElementById('classic-pagination-bar');
            if (pagBar) pagBar.style.display = 'none';
            container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">' + icon('alert') + ' 通信エラー</h2><p>' + escapeHtml(err) + '</p></div>';
          });
      }

      addListener('classic-prev-btn', 'click', function () {
        if (state.classicPage > 1) {
          var qVal = document.getElementById('q').value.trim();
          if (qVal) runClassicSearch(qVal, state.classicPage - 1);
        }
      });
      addListener('classic-next-btn', 'click', function () {
        var qVal = document.getElementById('q').value.trim();
        if (qVal) runClassicSearch(qVal, state.classicPage + 1);
      });
      var classicDeepBtn = document.getElementById('classic-deep-btn');
      if (classicDeepBtn) {
        classicDeepBtn.addEventListener('click', function () {
          var qVal = document.getElementById('q').value.trim();
          if (!qVal) {
            showToast('検索キーワードを入力してください');
            document.getElementById('q').focus();
            return;
          }
          setMode('deep');
          runUnifiedSearch(qVal);
        });
      }
      addListener('classic-time-range', 'change', function () {
        var qVal = document.getElementById('q').value.trim();
        if (qVal && state.mode === 'classic') runClassicSearch(qVal, 1);
      });
      addListener('classic-count', 'change', function () {
        var qVal = document.getElementById('q').value.trim();
        if (qVal && state.mode === 'classic') runClassicSearch(qVal, 1);
      });

      /* -------------------------------------------------------------
       * Scrape Mode Implementation
       * ------------------------------------------------------------- */
      function runScrapeMode(targetUrl) {
        cancelPendingRequest();
        currentAbortController = new AbortController();
        var signal = currentAbortController.signal;

        var maxLen = document.getElementById('opt-scrape-len').value || '8000';
        var focusQ = document.getElementById('opt-scrape-query').value.trim();
        var container = document.getElementById('results-container');
        container.innerHTML = '<div class="empty-state"><h2><span class="ui-spinner"></span> URL 本文抽出中...</h2><p>' + escapeHtml(targetUrl) + '</p></div>';

        closeSuggest();

        var api = '/api/scrape_analyze?url=' + encodeURIComponent(targetUrl) + '&max_length=' + encodeURIComponent(maxLen);
        if (focusQ) api += '&q=' + encodeURIComponent(focusQ);
        state.curlStr = 'curl -sG "' + window.location.origin + '/scrape" --data-urlencode "url=' + escapeShellDoubleQuoted(targetUrl) + '"';

        fetch(api, { signal: signal })
          .then(function (r) { return r.json(); })
          .then(function (res) {
            container.setAttribute('aria-busy', 'false');
            var telBar = document.getElementById('telemetry-bar');
            if (res.error) {
              if (telBar) telBar.classList.remove('visible');
              container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">' + icon('alert') + ' 抽出エラー</h2><p>' + escapeHtml(res.error) + '</p></div>';
              return;
            }
            state.markdown = res.markdown || res.content || '';
            state.prompt = res.rag_prompt || ('以下のWebページ抽出本文を根拠として要点を解説してください。\n\nURL: ' + targetUrl + '\n\n' + state.markdown);
            state.jsonStr = JSON.stringify(res, null, 2);

            var badges = document.getElementById('telemetry-badges');
            if (telBar) telBar.classList.add('visible');
            badges.innerHTML =
              '<span class="pill pill-emerald">' + icon('check', 'ui-icon-sm') + ' 本文抽出完了 (' + escapeHtml(res.char_count || 0) + ' 文字)</span>' +
              '<span class="pill pill-accent">~' + escapeHtml(res.estimated_tokens || 0) + ' tokens</span>' +
              '<span class="pill">' + escapeHtml(res.elapsed_ms || 0) + ' ms</span>';

            container.innerHTML = '';
            var card = document.createElement('article');
            card.className = 'result-card';
            var title = document.createElement('div');
            title.className = 'card-title';
            var a = document.createElement('a');
            a.href = safeHttpUrl(res.url);
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
            a.textContent = res.url;
            title.appendChild(a);
            card.appendChild(title);

            if (res.highlights && res.highlights.length) {
              var hlHeader = document.createElement('div');
              hlHeader.style.fontWeight = '700';
              hlHeader.style.fontSize = '0.84rem';
              hlHeader.style.margin = '0.5rem 0 0.3rem';
              hlHeader.textContent = 'BM25 関連ハイライト (' + (res.query || '') + ')';
              card.appendChild(hlHeader);
              renderHighlights(card, res.highlights, '');
            }

            var pre = document.createElement('div');
            pre.className = 'inline-scrape-drawer';
            pre.style.maxHeight = '34rem';
            pre.textContent = res.content || '';
            card.appendChild(pre);
            container.appendChild(card);
            updateContextView();
            updateUrlState(false);
          })
          .catch(function (err) {
            if (err.name === 'AbortError') return;
            var telBar = document.getElementById('telemetry-bar');
            if (telBar) telBar.classList.remove('visible');
            var oldBar = document.querySelector('.telemetry-bar:not(#telemetry-bar)');
            if (oldBar) oldBar.remove();
            container.setAttribute('aria-busy', 'false');
            container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">' + icon('alert') + ' 通信エラー</h2><p>' + escapeHtml(err) + '</p></div>';
          });
      }

      /* -------------------------------------------------------------
       * Settings Dashboard Implementation
       * ------------------------------------------------------------- */
      function setUnsavedChanges(modified) {
        state.togglesModified = modified;
        var bar = document.getElementById('unsaved-bar');
        if (bar) {
          bar.classList.toggle('show', modified);
        }
      }

      window.addEventListener('beforeunload', function (e) {
        if (state.togglesModified) {
          e.preventDefault();
          e.returnValue = '未保存の設定変更があります。ページを離れますか？';
          return e.returnValue;
        }
      });

      addListener('btn-discard-unsaved', 'click', function () {
        loadSettingsDashboard(true);
        setUnsavedChanges(false);
        showToast('変更を破棄しました');
      });

      addListener('btn-save-unsaved', 'click', function () {
        var saveEngBtn = document.getElementById('btn-save-settings-engines');
        if (saveEngBtn) saveEngBtn.click();
        // NOTE: togglesModified is cleared by the save handler's .then() on
        // success. Clearing it here would disable the beforeunload warning
        // even when the POST fails and the changes are actually lost.
      });

      function renderSettingsEngineCards() {
        var grid = document.getElementById('settings-engines-grid');
        grid.innerHTML = '';

        var filter = (state.settingsSearch || '').toLowerCase().trim();
        var cat = state.settingsCurrentCat || '';

        var list = state.settingsEngines.filter(function (e) {
          if (cat && (!e.categories || e.categories.indexOf(cat) === -1)) return false;
          if (filter) {
            var matchName = e.name.toLowerCase().indexOf(filter) !== -1;
            var matchCat = (e.categories || []).some(function (c) { return c.toLowerCase().indexOf(filter) !== -1; });
            var matchBang = (e.shortcut || '').toLowerCase().indexOf(filter) !== -1;
            if (!matchName && !matchCat && !matchBang) return false;
          }
          return true;
        });

        if (!list.length) {
          grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:2rem;color:var(--text-muted);">該当する検索エンジンがありません</div>';
          return;
        }

        list.forEach(function (e) {
          var c = document.createElement('div');
          c.className = 'engine-item-card';

          var top = document.createElement('div');
          top.className = 'engine-item-header';

          var title = document.createElement('div');
          title.className = 'engine-item-title';

          var dot = document.createElement('span');
          dot.style.width = '8px';
          dot.style.height = '8px';
          dot.style.borderRadius = '50%';
          dot.style.display = 'inline-block';
          if (e.status === 'suspended') {
            dot.style.background = 'var(--amber)';
            dot.title = '一時停止 / レート制限中 (' + (e.suspend_remaining_sec || 0) + 's 残り)';
          } else if (e.enabled) {
            dot.style.background = 'var(--emerald)';
            dot.title = '稼働中';
          } else {
            dot.style.background = 'var(--text-muted)';
            dot.title = '無効';
          }

          var nameSpan = document.createElement('span');
          nameSpan.textContent = e.name;

          title.appendChild(dot);
          title.appendChild(nameSpan);

          if (e.shortcut) {
            var bang = document.createElement('span');
            bang.className = 'pill';
            bang.style.fontSize = '0.7rem';
            bang.textContent = '!' + e.shortcut;
            title.appendChild(bang);
          }

          // Toggle switch
          var swLabel = document.createElement('label');
          swLabel.className = 'switch-label';
          var chk = document.createElement('input');
          chk.type = 'checkbox';
          chk.checked = !!e.enabled;
          chk.setAttribute('aria-label', (e.name || '検索エンジン') + ' の有効化/無効化');
          chk.addEventListener('change', function () {
            e.enabled = chk.checked;
            e.status = e.enabled ? 'online' : 'disabled';
            dot.style.background = e.enabled ? 'var(--emerald)' : 'var(--text-muted)';
            setUnsavedChanges(true);
            updateOverviewStats();
          });
          var sld = document.createElement('span');
          sld.className = 'switch-slider';
          swLabel.appendChild(chk);
          swLabel.appendChild(sld);

          top.appendChild(title);
          top.appendChild(swLabel);
          c.appendChild(top);

          // Meta info row with Ping test
          var meta = document.createElement('div');
          meta.className = 'engine-item-meta';

          (e.categories || []).forEach(function (catName) {
            var cp = document.createElement('span');
            cp.className = 'pill';
            cp.textContent = catName;
            meta.appendChild(cp);
          });

          var latPill = document.createElement('span');
          latPill.className = 'pill';
          latPill.textContent = (typeof e.latency_ms === 'number' && e.latency_ms > 0) ? (e.latency_ms + ' ms') : '-- ms';
          meta.appendChild(latPill);

          if (typeof e.reliability === 'number') {
            var relPill = document.createElement('span');
            relPill.className = 'pill ' + (e.reliability >= 90 ? 'pill-emerald' : 'pill-amber');
            relPill.textContent = '信頼性 ' + e.reliability + '%';
            meta.appendChild(relPill);
          }

          // Individual Engine Test (Ping) button
          var testBtn = document.createElement('button');
          testBtn.type = 'button';
          testBtn.className = 'btn btn-sm';
          testBtn.style.marginLeft = 'auto';
          testBtn.textContent = 'テスト';
          testBtn.addEventListener('click', function () {
            testBtn.disabled = true;
            testBtn.innerHTML = '<span class="ui-spinner"></span>';
            var t0 = performance.now();
            fetch('/deep_search?q=test&count=1&engines=' + encodeURIComponent(e.name) + '&mode=classic')
              .then(function (r) { return r.json(); })
              .then(function (res) {
                var elapsed = Math.round(performance.now() - t0);
                testBtn.disabled = false;
                testBtn.textContent = 'テスト';
                if (res.results && res.results.length) {
                  latPill.textContent = elapsed + ' ms';
                  latPill.className = 'pill pill-emerald';
                  showToast(e.name + ': 疎通成功 (' + elapsed + 'ms)');
                } else {
                  showToast(e.name + ': 応答なし / 0件', true);
                }
              })
              .catch(function () {
                testBtn.disabled = false;
                testBtn.textContent = 'テスト';
                showToast(e.name + ': 通信エラー', true);
              });
          });
          meta.appendChild(testBtn);

          c.appendChild(meta);
          grid.appendChild(c);
        });
      }

      function updateOverviewStats() {
        var active = state.settingsEngines.filter(function (e) { return e.enabled; }).length;
        var suspended = state.settingsEngines.filter(function (e) { return e.status === 'suspended'; }).length;
        document.getElementById('stat-active-engines').textContent = active + ' / ' + state.settingsEngines.length;
        document.getElementById('stat-suspended-engines').textContent = suspended;
      }

      function loadSettingsDashboard(forceReload) {
        var grid = document.getElementById('settings-engines-grid');
        if (state.settingsEngines.length && !forceReload) {
          renderSettingsEngineCards();
          return;
        }

        grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:2rem;"><span class="ui-spinner"></span> エンジン稼働状況を取得中...</div>';

        fetch('/api/settings/engines')
          .then(function (r) { return r.json(); })
          .then(function (res) {
            if (!res.success) throw new Error('Failed to load engines');
            state.settingsEngines = res.engines || [];
            state.settingsCategories = res.categories || [];

            document.getElementById('stat-active-engines').textContent = res.active_engines + ' / ' + res.total_engines;
            document.getElementById('stat-suspended-engines').textContent = res.suspended_engines;
            document.getElementById('stat-avg-latency').textContent = res.avg_latency_ms + ' ms';
            document.getElementById('stat-avg-reliability').textContent = res.avg_reliability + '%';

            // Render category chips
            var chipsContainer = document.getElementById('settings-engine-cat-chips');
            chipsContainer.innerHTML = '';
            var allBtn = document.createElement('button');
            allBtn.type = 'button';
            allBtn.className = 'cat-btn active';
            allBtn.setAttribute('aria-pressed', 'true');
            allBtn.textContent = 'すべて (' + res.total_engines + ')';
            allBtn.addEventListener('click', function () {
              chipsContainer.querySelectorAll('.cat-btn').forEach(function (b) {
                b.classList.remove('active');
                b.setAttribute('aria-pressed', 'false');
              });
              allBtn.classList.add('active');
              allBtn.setAttribute('aria-pressed', 'true');
              state.settingsCurrentCat = '';
              renderSettingsEngineCards();
            });
            chipsContainer.appendChild(allBtn);

            (res.categories || []).forEach(function (cat) {
              var count = state.settingsEngines.filter(function (e) { return (e.categories || []).indexOf(cat) !== -1; }).length;
              var b = document.createElement('button');
              b.type = 'button';
              b.className = 'cat-btn';
              b.setAttribute('aria-pressed', 'false');
              b.textContent = cat + ' (' + count + ')';
              b.addEventListener('click', function () {
                chipsContainer.querySelectorAll('.cat-btn').forEach(function (btn) {
                  btn.classList.remove('active');
                  btn.setAttribute('aria-pressed', 'false');
                });
                b.classList.add('active');
                b.setAttribute('aria-pressed', 'true');
                state.settingsCurrentCat = cat;
                renderSettingsEngineCards();
              });
              chipsContainer.appendChild(b);
            });

            renderSettingsEngineCards();
          })
          .catch(function (err) {
            grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:2rem;color:var(--danger);">' + icon('alert') + ' エンジン設定の取得に失敗しました: ' + escapeHtml(err) + '</div>';
          });
      }

      function selectSettingsSubtab(name) {
        var engBtn = document.getElementById('subtab-engines-btn');
        var genBtn = document.getElementById('subtab-general-btn');
        var engSec = document.getElementById('section-settings-engines');
        var genSec = document.getElementById('section-settings-general');
        if (name === 'engines') {
          engBtn.classList.add('active');
          engBtn.setAttribute('aria-selected', 'true');
          engBtn.setAttribute('tabindex', '0');
          genBtn.classList.remove('active');
          genBtn.setAttribute('aria-selected', 'false');
          genBtn.setAttribute('tabindex', '-1');
          engSec.style.display = 'block';
          genSec.style.display = 'none';
        } else if (name === 'general') {
          genBtn.classList.add('active');
          genBtn.setAttribute('aria-selected', 'true');
          genBtn.setAttribute('tabindex', '0');
          engBtn.classList.remove('active');
          engBtn.setAttribute('aria-selected', 'false');
          engBtn.setAttribute('tabindex', '-1');
          engSec.style.display = 'none';
          genSec.style.display = 'block';
        }
      }

      addListener('subtab-engines-btn', 'click', function () {
        selectSettingsSubtab('engines');
      });
      addListener('subtab-general-btn', 'click', function () {
        selectSettingsSubtab('general');
      });

      var subtabBtns = [document.getElementById('subtab-engines-btn'), document.getElementById('subtab-general-btn')].filter(Boolean);
      subtabBtns.forEach(function (btn, idx) {
        btn.addEventListener('keydown', function (e) {
          if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
            e.preventDefault();
            var next = subtabBtns[(idx + 1) % subtabBtns.length];
            next.focus();
            selectSettingsSubtab(next.getAttribute('data-subtab'));
          } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
            e.preventDefault();
            var prev = subtabBtns[(idx - 1 + subtabBtns.length) % subtabBtns.length];
            prev.focus();
            selectSettingsSubtab(prev.getAttribute('data-subtab'));
          }
        });
      });

      addListener('engine-search-input', 'input', function () {
        state.settingsSearch = this.value;
        renderSettingsEngineCards();
      });

      addListener('btn-enable-all-cat', 'click', function () {
        var cat = state.settingsCurrentCat;
        state.settingsEngines.forEach(function (e) {
          if (!cat || (e.categories && e.categories.indexOf(cat) !== -1)) {
            e.enabled = true;
            e.status = 'online';
          }
        });
        updateOverviewStats();
        renderSettingsEngineCards();
        setUnsavedChanges(true);
        showToast('カテゴリー内をすべて有効化しました');
      });

      addListener('btn-disable-all-cat', 'click', function () {
        var cat = state.settingsCurrentCat;
        state.settingsEngines.forEach(function (e) {
          if (!cat || (e.categories && e.categories.indexOf(cat) !== -1)) {
            e.enabled = false;
            e.status = 'disabled';
          }
        });
        updateOverviewStats();
        renderSettingsEngineCards();
        setUnsavedChanges(true);
        showToast('カテゴリー内をすべて無効化しました');
      });

      addListener('btn-reset-engines-def', 'click', function () {
        state.settingsEngines.forEach(function (e) {
          e.enabled = !!e.default_enabled;
          e.status = e.enabled ? 'online' : 'disabled';
        });
        updateOverviewStats();
        renderSettingsEngineCards();
        setUnsavedChanges(true);
        showToast('デフォルト構成を復元しました');
      });

      addListener('btn-save-settings-engines', 'click', function () {
        var disabled = [];
        var enabled = [];
        state.settingsEngines.forEach(function (e) {
          if (e.enabled) enabled.push(e.name);
          else disabled.push(e.name);
        });

        fetch('/api/settings/engines', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ disabled_engines: disabled, enabled_engines: enabled })
        })
          .then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
          })
          .then(function () {
            showToast('検索エンジン構成を保存しました');
            // Clear the dirty flag only after a confirmed save so the
            // beforeunload guard stays active if the POST failed.
            setUnsavedChanges(false);
          })
          .catch(function () {
            showToast('保存に失敗しました', true);
          });
      });

      function loadGeneralPreferences() {
        var mode = localStorage.getItem('sxng_pref_mode');
        var ss = localStorage.getItem('sxng_pref_safesearch');
        var count = localStorage.getItem('sxng_pref_count');
        var tok = localStorage.getItem('sxng_pref_tokens');
        var ac = localStorage.getItem('sxng_pref_autocomplete');

        if (mode && document.getElementById('pref-default-mode')) document.getElementById('pref-default-mode').value = mode;
        if (ss && document.getElementById('pref-safesearch')) document.getElementById('pref-safesearch').value = ss;
        if (count && document.getElementById('pref-default-count')) document.getElementById('pref-default-count').value = count;
        if (tok && document.getElementById('pref-default-tokens')) document.getElementById('pref-default-tokens').value = tok;
        if (ac && document.getElementById('pref-autocomplete')) document.getElementById('pref-autocomplete').value = ac;
      }
      loadGeneralPreferences();

      addListener('btn-save-general-prefs', 'click', function () {
        var mode = document.getElementById('pref-default-mode') ? document.getElementById('pref-default-mode').value : 'deep';
        var ss = document.getElementById('pref-safesearch') ? document.getElementById('pref-safesearch').value : '1';
        var count = document.getElementById('pref-default-count') ? document.getElementById('pref-default-count').value : '10';
        var tok = document.getElementById('pref-default-tokens') ? document.getElementById('pref-default-tokens').value : '3000';
        var ac = document.getElementById('pref-autocomplete') ? document.getElementById('pref-autocomplete').value : 'duckduckgo';

        localStorage.setItem('sxng_pref_mode', mode);
        localStorage.setItem('sxng_pref_safesearch', ss);
        localStorage.setItem('sxng_pref_count', count);
        localStorage.setItem('sxng_pref_tokens', tok);
        localStorage.setItem('sxng_pref_autocomplete', ac);

        fetch('/api/settings/engines', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ safesearch: ss, default_mode: mode, autocomplete: ac })
        })
          .then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
          })
          .then(function () {
            showToast('一般設定を保存しました');
          })
          .catch(function () {
            showToast('一般設定の保存に失敗しました', true);
          });
      });

      addListener('btn-reset-general-prefs', 'click', function () {
        if (document.getElementById('pref-default-mode')) document.getElementById('pref-default-mode').value = 'deep';
        if (document.getElementById('pref-safesearch')) document.getElementById('pref-safesearch').value = '1';
        if (document.getElementById('pref-default-count')) document.getElementById('pref-default-count').value = '10';
        document.getElementById('pref-default-tokens').value = '3000';
        if (document.getElementById('pref-autocomplete')) {
          document.getElementById('pref-autocomplete').value = 'duckduckgo';
        }
        localStorage.removeItem('sxng_pref_mode');
        localStorage.removeItem('sxng_pref_safesearch');
        localStorage.removeItem('sxng_pref_count');
        localStorage.removeItem('sxng_pref_tokens');
        localStorage.removeItem('sxng_pref_autocomplete');
        showToast('初期設定を復元しました');
      });

      /* -------------------------------------------------------------
       * Agent & MCP Hub Implementation
       * ------------------------------------------------------------- */
      function loadAgentHub() {
        var container = document.getElementById('hub-cards-container');
        if (container.dataset.loaded === '1') return;
        container.innerHTML = '<div class="empty-state"><h2><span class="ui-spinner"></span> 連携情報を取得中...</h2></div>';

        fetch('/api/ai_info')
          .then(function (r) { return r.json(); })
          .then(function (info) {
            container.dataset.loaded = '1';
            container.innerHTML = '';
            var items = [
              {
                title: 'GenAI Retrieval API (/api/retrieval)',
                desc: 'GenAIモデル・自律エージェント向けの構造化グラウンディングAPI (schema_version: 1.0)。根拠パッセージ・検証メタデータ・BM25スコアを返します。',
                code: info.snippets.curl_retrieval + '\n\n# PowerShell:\n' + info.snippets.pwsh_retrieval
              },
              {
                title: 'HTTP Deep Search API (/deep_search)',
                desc: '1回のHTTPリクエストで検索・並列スクレイピング・BM25ハイライト抽出を実行し、MarkdownまたはJSONを返します。',
                code: info.snippets.curl_deep_md + '\n\n# PowerShell:\n' + info.snippets.pwsh_deep
              },
              {
                title: 'Claude Code (MCP 登録コマンド)',
                desc: 'ターミナルで1行実行するだけで、Claude Code に searxng_deep_search / searxng_search / searxng_scrape を追加します。',
                code: info.snippets.claude_code
              },
              {
                title: 'Cursor / Windsurf / Claude Desktop (mcp.json)',
                desc: '.cursor/mcp.json 等に貼り付けるだけでローカルMCPサーバーとして連携できます。',
                code: info.snippets.cursor_mcp
              },
              {
                title: 'OpenCode (opencode.json)',
                desc: 'プロジェクトルートの opencode.json に設定してネイティブ検索ツールとして利用できます。',
                code: info.snippets.opencode_json
              },
              {
                title: 'ターミナル CLI (searxng_cli.py)',
                desc: 'MCP非対応のエージェント（Codex CLI, Aider等）やスクリプトから直接ワンパス深層検索を実行できます。',
                code: info.snippets.cli_deep
              }
            ];
            items.forEach(function (it) {
              var card = document.createElement('div');
              card.className = 'hub-card';
              var h3 = document.createElement('h3');
              var span = document.createElement('span');
              span.textContent = it.title;
              var copyBtn = document.createElement('button');
              copyBtn.type = 'button';
              copyBtn.className = 'btn btn-sm';
              copyBtn.setAttribute('aria-label', it.title + ' の設定コードをコピー');
              copyBtn.innerHTML = icon('copy') + '<span>コピー</span>';
              copyBtn.addEventListener('click', function () {
                copyWithFeedback(it.code, copyBtn, 'コピー済');
              });
              h3.appendChild(span);
              h3.appendChild(copyBtn);

              var p = document.createElement('p');
              p.textContent = it.desc;

              var pre = document.createElement('pre');
              pre.className = 'hub-pre';
              pre.textContent = it.code;

              card.appendChild(h3);
              card.appendChild(p);
              card.appendChild(pre);
              container.appendChild(card);
            });
          })
          .catch(function (err) {
            container.innerHTML = '<div class="empty-state"><p style="color:var(--danger);">' + icon('alert') + ' エラー: ' + escapeHtml(err) + '</p></div>';
          });
      }

      function executeCurrentAction() {
        var qVal = document.getElementById('q').value.trim();
        if (!qVal) {
          showToast('検索キーワードまたはURLを入力してください');
          document.getElementById('q').focus();
          return;
        }

        closeSuggest();

        if (isUrlText(qVal)) {
          if (state.mode !== 'deep') {
            setMode('deep', true);
          }
          syncInputOptionsVisibility();
          runScrapeMode(qVal);
        } else if (state.mode === 'classic') {
          syncInputOptionsVisibility();
          runClassicSearch(qVal, 1);
        } else {
          syncInputOptionsVisibility();
          runUnifiedSearch(qVal);
        }
      }

      addListener('ws-form', 'submit', function (e) {
        e.preventDefault();
        executeCurrentAction();
      });

      /* -------------------------------------------------------------
       * Keyboard Navigation & Global Shortcuts (j/k, c, s, Alt+1..4)
       * ------------------------------------------------------------- */
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
          closeSuggest();
          var toast = document.getElementById('toast-notice');
          if (toast && toast.classList.contains('show')) {
            toast.classList.remove('show');
          }
          document.querySelectorAll('.inline-scrape-drawer').forEach(function (d) {
            d.style.display = 'none';
          });
          document.querySelectorAll('button[aria-expanded="true"]').forEach(function (b) {
            b.setAttribute('aria-expanded', 'false');
          });
          return;
        }

        var active = document.activeElement;
        var qInput = document.getElementById('q');
        var isEditing = active && (['INPUT', 'TEXTAREA', 'SELECT'].indexOf(active.tagName) !== -1 || active.isContentEditable);

        // Alt + 1..4 Mode Switching
        if (e.altKey && !e.ctrlKey && !e.metaKey) {
          if (e.key === '1') { e.preventDefault(); setMode('deep'); return; }
          if (e.key === '2') { e.preventDefault(); setMode('classic'); return; }
          if (e.key === '3') { e.preventDefault(); setMode('agent'); return; }
          if (e.key === '4') { e.preventDefault(); setMode('settings'); return; }
        }

        if ((e.key === '/' && active !== qInput && !isEditing) ||
            ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k')) {
          e.preventDefault();
          if (state.mode === 'agent' || state.mode === 'settings') {
            setMode('deep');
          }
          qInput.focus();
          qInput.select();
          return;
        }

        // Power user j/k card navigation when not editing
        if (!isEditing && (state.mode === 'deep' || state.mode === 'classic')) {
          var containerId = (state.mode === 'deep') ? 'results-container' : 'classic-results-container';
          var cards = Array.prototype.slice.call(document.querySelectorAll('#' + containerId + ' article'));
          if (!cards.length) return;

          function activateCard(targetIdx) {
            state.selectedCardIndex = targetIdx;
            cards.forEach(function (c, idx) {
              var isSel = (idx === state.selectedCardIndex);
              c.classList.toggle('selected-card', isSel);
              c.setAttribute('aria-selected', isSel ? 'true' : 'false');
            });
            var targetCard = cards[state.selectedCardIndex];
            if (targetCard) {
              targetCard.setAttribute('tabindex', '-1');
              targetCard.focus({ preventScroll: true });
              targetCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
          }

          if (e.key === 'j') {
            e.preventDefault();
            activateCard(Math.min(cards.length - 1, state.selectedCardIndex + 1));
          } else if (e.key === 'k') {
            e.preventDefault();
            activateCard(Math.max(0, state.selectedCardIndex - 1));
          } else if (e.key === 'c' && state.selectedCardIndex >= 0 && state.selectedCardIndex < cards.length) {
            e.preventDefault();
            var copyBtn = cards[state.selectedCardIndex].querySelector('button[data-action="copy-citation"], button[aria-label*="コピー"]');
            if (copyBtn) copyBtn.click();
          } else if (e.key === 'Enter' && state.selectedCardIndex >= 0 && state.selectedCardIndex < cards.length && active === cards[state.selectedCardIndex]) {
            var link = cards[state.selectedCardIndex].querySelector('a');
            if (link) window.open(link.href, '_blank', 'noopener,noreferrer');
          }
        }
      });

      // Restore user preferences from localStorage
      var savedMode = localStorage.getItem('sxng_pref_mode');
      if (savedMode && ['deep', 'classic', 'balanced'].indexOf(savedMode) !== -1) {
        document.getElementById('pref-default-mode').value = savedMode;
        if (!window.location.search) {
          setMode(savedMode === 'balanced' ? 'deep' : savedMode, true);
        }
      }
      var savedCount = localStorage.getItem('sxng_pref_count');
      if (savedCount) {
        document.getElementById('pref-default-count').value = savedCount;
        document.getElementById('classic-count').value = savedCount;
      }
      var savedTok = localStorage.getItem('sxng_pref_tokens');
      if (savedTok) {
        document.getElementById('pref-default-tokens').value = savedTok;
        document.getElementById('opt-tokens').value = savedTok;
      }

      // Parse initial URL parameters
      var urlParams = new URLSearchParams(window.location.search);
      var initMode = urlParams.get('mode');
      var initDepth = urlParams.get('depth');
      var initCat = urlParams.get('category') || urlParams.get('categories');
      var initPage = parseInt(urlParams.get('page') || urlParams.get('pageno'), 10) || 1;
      var initQ = urlParams.get('q') || urlParams.get('url');

      if (initDepth && ['advanced', 'code', 'basic', 'fast'].indexOf(initDepth) !== -1) {
        document.getElementById('opt-depth').value = initDepth;
      }
      if (initCat) {
        state.classicCategory = initCat;
        document.querySelectorAll('#classic-cat-chips .cat-btn').forEach(function (b) {
          var isCurrent = (b.dataset.cat === initCat);
          b.classList.toggle('active', isCurrent);
          b.setAttribute('aria-pressed', isCurrent ? 'true' : 'false');
        });
      }
      if (initPage > 1) {
        state.classicPage = initPage;
      }
      if (initMode && ['deep', 'classic', 'agent', 'settings'].indexOf(initMode) !== -1) {
        setMode(initMode, true);
      }
      if (initQ) {
        document.getElementById('q').value = initQ;
        syncInputOptionsVisibility();
        if (state.mode === 'classic' && initPage > 1) {
          runClassicSearch(initQ, initPage);
        } else {
          executeCurrentAction();
        }
      }
    })();
