/* Only account verification and text-field preparation. Never submits a form. */
const LiminalSunoPrep = (() => {
  const storageKey = 'liminal-suno-preparation-v1';
  function validate(d, now = Date.now() / 1000) {
    if (!d || d.version !== 1 || d.mode !== 'prepare_only' || d.instrumental !== true ||
        !/^[0-9a-f]{32}$/.test(d.id || '') || typeof d.account_email !== 'string' ||
        !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(d.account_email) || d.account_email.length > 254 ||
        typeof d.title !== 'string' || !d.title.trim() || d.title.length > 120 ||
        typeof d.styles !== 'string' || !d.styles.trim() || d.styles.length > 1000 ||
        !Number.isInteger(d.created) || now - d.created > 1800 || d.created - now > 60) {
      throw new Error('Invalid or expired draft. Prepare a new form from Liminal Factory.');
    }
    return d;
  }
  function decode(hash) {
    const raw = hash.replace(/^#liminal-draft=/, '');
    if (!raw || raw.length > 10000 || !/^[A-Za-z0-9_-]+$/.test(raw)) throw new Error('Invalid preparation link.');
    const bytes = Uint8Array.from(atob(raw.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));
    return validate(JSON.parse(new TextDecoder().decode(bytes)));
  }
  function accountEmail(doc) {
    // The Account details Email row, not a username or a connected account.
    const text = doc.body.innerText || doc.body.textContent || '';
    return text.match(/(?:^|\n)\s*Email\s*\n\s*([^\s@]+@[^\s@]+\.[^\s@]+)(?=\s|$)/i)?.[1]?.toLowerCase() || null;
  }
  function name(doc, el) {
    return el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
      (el.id ? Array.from(doc.querySelectorAll('label')).find(l => l.htmlFor === el.id)?.textContent?.trim() : '') || '';
  }
  function field(doc, names) {
    const all = Array.from(doc.querySelectorAll('input,textarea,[contenteditable="true"]'))
      .filter(el => names.includes(name(doc, el)));
    if (all.length !== 1) throw new Error('Suno form changed or is not ready. Review the page manually; no generation was started.');
    return all[0];
  }
  function value(el) { return 'value' in el ? el.value : el.textContent || ''; }
  function write(doc, el, text) {
    const win = doc.defaultView;
    if (el instanceof win.HTMLTextAreaElement || el instanceof win.HTMLInputElement) {
      const proto = el instanceof win.HTMLTextAreaElement ? win.HTMLTextAreaElement.prototype : win.HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, text);
    } else { throw new Error('Unsupported Suno field; please fill it manually.'); }
    el.dispatchEvent(new win.Event('input', {bubbles: true}));
    el.dispatchEvent(new win.Event('change', {bubbles: true}));
  }
  function prepare(doc, draft, verifiedEmail) {
    validate(draft);
    if (verifiedEmail?.toLowerCase() !== draft.account_email.toLowerCase()) throw new Error('Suno account does not match. Sign in to the requested account and prepare again.');
    const styles = field(doc, ['Styles', 'Style of Music']);
    const title = field(doc, ['Song Title (Optional)', 'Song Title', 'Title']);
    const lyrics = field(doc, ['Lyrics editor', 'Lyrics']);
    if (value(lyrics).trim()) throw new Error('Lyrics are not empty. Clear them yourself for instrumental music, then prepare again.');
    if ((value(styles).trim() && value(styles) !== draft.styles) || (value(title).trim() && value(title) !== draft.title)) {
      throw new Error('The Suno form contains another draft. Clear it yourself or use a new Suno tab, then prepare again.');
    }
    // Validate every field before the first mutation. No click/submit operation.
    write(doc, styles, draft.styles); write(doc, title, draft.title);
    if (value(styles) !== draft.styles || value(title) !== draft.title || value(lyrics).trim()) throw new Error('Could not verify the prepared fields. Review Suno manually.');
    return {title: draft.title, account_email: verifiedEmail, state: 'Prepared'};
  }
  function banner(doc, message, error = false) {
    let el = doc.getElementById('liminal-suno-status');
    if (!el) { el = doc.createElement('div'); el.id = 'liminal-suno-status'; el.setAttribute('role', 'status'); doc.body.append(el); }
    el.textContent = 'Liminal Factory: ' + message;
    Object.assign(el.style, {position:'fixed',zIndex:'2147483647',top:'12px',right:'12px',maxWidth:'480px',padding:'16px',borderRadius:'12px',background:error?'#662222':'#143d32',color:'#fff',font:'14px/1.5 system-ui',boxShadow:'0 4px 20px #0008'});
  }
  async function waitFor(fn, timeout = 45000) {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
      const result = fn(); if (result) return result;
      await new Promise(resolve => setTimeout(resolve, 250));
    }
    throw new Error('Suno is not ready. Sign in if needed, then prepare the form again.');
  }
  async function boot(win) {
    const doc = win.document;
    try {
      if (win.location.hash.startsWith('#liminal-draft=')) {
        const draft = decode(win.location.hash);
        win.sessionStorage.setItem(storageKey, JSON.stringify({draft}));
        win.history.replaceState(null, '', win.location.pathname + win.location.search);
        // Read account identity in the existing authenticated Suno UI. Never read cookies.
        win.location.assign('https://suno.com/settings'); return;
      }
      const saved = win.sessionStorage.getItem(storageKey);
      if (!saved) return;
      const record = JSON.parse(saved); const draft = validate(record.draft);
      if (win.location.pathname === '/settings') {
        banner(doc, 'Checking the Suno account…');
        const email = await waitFor(() => accountEmail(doc));
        if (email !== draft.account_email.toLowerCase()) throw new Error('Wrong Suno account. Switch accounts yourself, then prepare again from Liminal Factory.');
        win.sessionStorage.setItem(storageKey, JSON.stringify({draft,verifiedEmail:email,verifiedAt:Date.now()}));
        win.location.assign('https://suno.com/create'); return;
      }
      if (win.location.pathname !== '/create' || !record.verifiedAt || Date.now()-record.verifiedAt > 120000) throw new Error('Account verification expired. Prepare again from Liminal Factory.');
      banner(doc, 'Waiting for the form…');
      await waitFor(() => doc.querySelector('[role="tablist"]'));
      const advanced = Array.from(doc.querySelectorAll('[role="tab"]')).filter(el => /^(Advanced|Custom)$/.test(el.textContent.trim()));
      if (advanced.length === 1 && advanced[0].getAttribute('aria-selected') !== 'true') advanced[0].click();
      await waitFor(() => {
        try { return field(doc,['Styles','Style of Music']) && field(doc,['Lyrics editor','Lyrics']) && field(doc,['Song Title (Optional)','Song Title','Title']); }
        catch { return false; }
      });
      prepare(doc, draft, record.verifiedEmail);
      await new Promise(resolve => setTimeout(resolve, 600));
      prepare(doc, draft, record.verifiedEmail); // Verify after React has processed input events.
      win.sessionStorage.removeItem(storageKey);
      banner(doc, `Prepared for ${record.verifiedEmail}. Lyrics are empty (instrumental). Review the form and click Create yourself. Nothing was generated or downloaded.`);
    } catch (e) {
      win.sessionStorage.removeItem(storageKey);
      banner(doc, e.message || 'Preparation failed; review Suno manually.', true);
    }
  }
  return {validate,decode,accountEmail,prepare,boot};
})();
if (typeof window !== 'undefined' && !globalThis.LIMINAL_SUNO_TEST) void LiminalSunoPrep.boot(window);
