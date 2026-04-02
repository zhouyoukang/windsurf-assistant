// TurnstilePatch - Cloudflare Turnstile Auto-Solver
// Runs at document_start to patch before any CF scripts load

(function() {
  'use strict';

  // 1. Override automation detection signals
  try {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  } catch(e) {}

  // 2. Mask chrome automation properties
  try {
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
  } catch(e) {}

  // 3. Override permissions query to return "granted"
  try {
    const origQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (params) => {
      if (params.name === 'notifications') {
        return Promise.resolve({ state: 'granted', onchange: null });
      }
      return origQuery(params);
    };
  } catch(e) {}

  // 4. Patch Turnstile widget
  let _originalTurnstile = undefined;
  const PATCH_DELAY = 1500;

  function patchTurnstileObject(t) {
    if (!t || t.__patched) return t;
    t.__patched = true;

    const origRender = t.render;
    if (origRender) {
      t.render = function(container, params) {
        const result = origRender.call(this, container, params);
        const cb = params && (params.callback || params['callback']);
        if (cb) {
          setTimeout(function() {
            try {
              if (typeof cb === 'function') {
                cb('turnstile-patched-token-' + Math.random().toString(36).substr(2));
              } else if (typeof cb === 'string' && window[cb]) {
                window[cb]('turnstile-patched-token-' + Math.random().toString(36).substr(2));
              }
            } catch(e) {}
          }, PATCH_DELAY + Math.random() * 500);
        }
        return result;
      };
    }
    return t;
  }

  // 5. Intercept window.turnstile assignment
  let _turnstileValue = undefined;
  try {
    Object.defineProperty(window, 'turnstile', {
      get: function() { return _turnstileValue; },
      set: function(val) {
        _turnstileValue = patchTurnstileObject(val);
      },
      configurable: true
    });
  } catch(e) {}

  // 6. Observe DOM for Turnstile iframes and containers
  function handleTurnstileContainer(el) {
    const sitekey = el.getAttribute('data-sitekey') ||
                    el.getAttribute('data-cf-turnstile-site-key');
    if (!sitekey) return;

    const cb = el.getAttribute('data-callback') ||
               el.getAttribute('data-response-field-name');

    setTimeout(function() {
      try {
        // Try calling callback directly
        if (cb && window[cb]) {
          window[cb]('turnstile-patched-token-' + Date.now());
          return;
        }
        // Try via turnstile API
        if (window.turnstile && window.turnstile.getResponse) {
          return;
        }
        // Set response field
        const respField = document.getElementById('cf-turnstile-response') ||
                          document.querySelector('[name="cf-turnstile-response"]') ||
                          document.querySelector('input[name="g-recaptcha-response"]');
        if (respField) {
          const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
          setter.call(respField, 'turnstile-patched-token-' + Date.now());
          respField.dispatchEvent(new Event('input', { bubbles: true }));
          respField.dispatchEvent(new Event('change', { bubbles: true }));
        }
      } catch(e) {}
    }, PATCH_DELAY + Math.random() * 800);
  }

  const observer = new MutationObserver(function(mutations) {
    mutations.forEach(function(m) {
      m.addedNodes.forEach(function(node) {
        if (node.nodeType !== 1) return;
        // Check if it's a turnstile container
        if (node.getAttribute && (
            node.getAttribute('data-sitekey') ||
            node.classList.contains('cf-turnstile') ||
            node.id === 'cf-turnstile'
        )) {
          handleTurnstileContainer(node);
        }
        // Check children
        const containers = node.querySelectorAll ? node.querySelectorAll(
          '[data-sitekey], .cf-turnstile, #cf-turnstile, [data-cf-turnstile]'
        ) : [];
        containers.forEach(handleTurnstileContainer);
      });
    });
  });

  observer.observe(document.documentElement, { childList: true, subtree: true });

  // 7. Patch on DOMContentLoaded as well
  document.addEventListener('DOMContentLoaded', function() {
    const containers = document.querySelectorAll(
      '[data-sitekey], .cf-turnstile, #cf-turnstile'
    );
    containers.forEach(handleTurnstileContainer);
  });

})();
