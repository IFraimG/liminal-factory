/* Account verification, text fields and named More Options only. Never submits a form. */
const LiminalSunoPrep = (() => {
  const storageKey = 'liminal-suno-preparation-v2';
  function validate(d, now = Date.now() / 1000) {
    if (!d || d.version !== 2 || d.mode !== 'prepare_only' || d.instrumental !== true ||
        !/^[0-9a-f]{32}$/.test(d.id || '') || typeof d.account_email !== 'string' ||
        !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(d.account_email) || d.account_email.length > 254 ||
        typeof d.title !== 'string' || !d.title.trim() || d.title.length > 120 ||
        typeof d.styles !== 'string' || !d.styles.trim() || d.styles.length > 1000 ||
        !Number.isInteger(d.created) || now - d.created > 1800 || d.created - now > 60) {
      throw new Error('Invalid or expired draft. Prepare a new form from Liminal Factory.');
    }
    const o = d.more_options;
    if (!o || typeof o.exclude_styles !== 'string' || !o.exclude_styles.trim() || o.exclude_styles.length > 1000 ||
      !Number.isInteger(o.weirdness) || o.weirdness < 0 || o.weirdness > 100 ||
      !Number.isInteger(o.style_influence) || o.style_influence < 0 || o.style_influence > 100 ||
      !['off','normal','high','extra','max'].includes(o.variety) ||
      !Number.isInteger(o.duration_seconds) || o.duration_seconds < 30 || o.duration_seconds > 600 ||
      typeof o.max_mode !== 'boolean' || o.personalize !== 'off' || o.vocal_gender !== 'none' ||
      typeof o.rationale !== 'string' || o.rationale.length < 20) throw new Error('Mandatory More Options are missing or invalid. Ask the agent to update the music brief.');
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
    return el.getAttribute('aria-label') || (el.getAttribute('aria-labelledby')||'').split(/\s+/).map(id=>doc.getElementById(id)?.textContent?.trim()||'').join(' ').trim() || el.getAttribute('placeholder') ||
      (el.id ? Array.from(doc.querySelectorAll('label')).find(l => l.htmlFor === el.id)?.textContent?.trim() : '') || '';
  }
  function field(doc, names) {
    const all = Array.from(doc.querySelectorAll('input,textarea,[contenteditable="true"]'))
      .filter(el => names.includes(name(doc, el)) && visible(doc,el));
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
  const frame = doc => new Promise(resolve => doc.defaultView.setTimeout(resolve, 30));
  function visible(doc,el) {
    for(let parent=el;parent;parent=parent.parentElement) {
      if(parent.hidden || parent.getAttribute('aria-hidden')==='true' || parent.hasAttribute('inert')) return false;
      const css=doc.defaultView.getComputedStyle(parent);
      if(css.display==='none' || css.visibility==='hidden') return false;
    }
    return true;
  }
  function slider(doc, label) {
    const candidates=Array.from(doc.querySelectorAll('[role="slider"],input[type="range"]')).filter(el => name(doc,el)===label && visible(doc,el));
    // Slider widgets may include a second hidden/native input for form state.
    const roles=candidates.filter(el=>el.getAttribute('role')==='slider');
    const matches=roles.length?roles:candidates;
    if(matches.length!==1) throw new Error('Cannot identify More Options slider: '+label);
    return matches[0];
  }
  function sliderValue(el) { return Number(el.getAttribute('aria-valuenow') ?? el.value); }
  async function setSlider(doc,label,target) {
    let el=slider(doc,label);
    const lo=Number(el.getAttribute('aria-valuemin') ?? el.min ?? 0), hi=Number(el.getAttribute('aria-valuemax') ?? el.max ?? 100);
    if (!Number.isFinite(lo) || !Number.isFinite(hi) || target<lo || target>hi) throw new Error(label+' is outside the supported Suno range.');
    if (el.tagName==='INPUT') {write(doc,el,String(target));await frame(doc);}
    else {
      for(let n=0;n<202;n++) {
        el=slider(doc,label);const current=sliderValue(el);if(current===target) return;
        if(!Number.isFinite(current)) throw new Error('Unreadable slider: '+label);
        el.focus();
        const key=current<target?'ArrowRight':'ArrowLeft';
        el.dispatchEvent(new doc.defaultView.KeyboardEvent('keydown',{key,code:key,bubbles:true,cancelable:true}));
        await frame(doc);
        if(sliderValue(slider(doc,label))===current) throw new Error('Suno did not accept '+label+'; review manually.');
      }
    }
    if(sliderValue(slider(doc,label))!==target) throw new Error('Could not verify '+label);
  }
  function group(doc,label,choices) {
    const labels=Array.from(doc.querySelectorAll('span,div,label,p')).filter(el =>
      Array.from(el.childNodes).filter(n=>n.nodeType===3).map(n=>n.textContent).join('').trim()===label && visible(doc,el));
    for(const labelEl of labels) {
      let parent=labelEl.parentElement;
      for(let n=0;parent && n<5;n++,parent=parent.parentElement) {
        const buttons=Array.from(parent.querySelectorAll('button,[role=button]')).filter(b=>choices.includes(b.textContent.trim()) && visible(doc,b));
        if(buttons.length===choices.length && choices.every(c=>buttons.some(b=>b.textContent.trim()===c))) return buttons;
      }
    }
    throw new Error('Cannot identify More Options group: '+label);
  }
  function selected(doc,button) {
    for(const attr of ['aria-pressed','aria-selected','aria-checked']) {
      if(button.hasAttribute(attr)) return button.getAttribute(attr)==='true';
    }
    const state=button.getAttribute('data-state');
    if(['on','off','active','inactive','checked','unchecked'].includes(state)) return ['on','active','checked'].includes(state);
    // Suno's HXC pills use explicit standard/tertiary variants; both may
    // have translucent backgrounds, so background opacity alone is ambiguous.
    if(button.classList.contains('hxc-btn-variant-standard-legacy')) return true;
    if(button.classList.contains('hxc-btn-variant-tertiary-legacy')) return false;
    const bg=doc.defaultView.getComputedStyle(button).backgroundColor;
    // Suno v6 visually selects a pill with a nontransparent background.
    return !!bg && bg!=='transparent' && !/rgba\([^)]*,\s*0\s*\)$/.test(bg);
  }
  function safeClick(button) {
    if(button.form && button.type!=='button') throw new Error('Refusing a form submission control.');
    button.click();
  }
  async function setGroup(doc,label,target,choices=['Off','On']) {
    let buttons=group(doc,label,choices);
    if(target===null) {
      const active=buttons.filter(b=>selected(doc,b));
      if(active.length>1) throw new Error('Ambiguous selection: '+label);
      if(active.length) {safeClick(active[0]);await frame(doc);}
    } else {
      const button=buttons.find(b=>b.textContent.trim()===target);
      if(button.disabled || button.getAttribute('aria-disabled')==='true') throw new Error(label+' option is unavailable.');
      if(!selected(doc,button)) {safeClick(button);await frame(doc);}
    }
    buttons=group(doc,label,choices);
    const active=buttons.filter(b=>selected(doc,b));
    if(target===null?active.length!==0:active.length!==1 || active[0].textContent.trim()!==target) throw new Error('Could not verify '+label);
  }
  function verifyOptions(doc,o) {
    if(value(field(doc,['Exclude styles']))!==o.exclude_styles ||
      sliderValue(slider(doc,'Weirdness'))!==o.weirdness || sliderValue(slider(doc,'Style Influence'))!==o.style_influence ||
      sliderValue(slider(doc,'Variety'))!==['off','normal','high','extra','max'].indexOf(o.variety) ||
      sliderValue(slider(doc,'Duration'))!==o.duration_seconds) throw new Error('More Options verification failed; do not treat the form as prepared.');
    for(const [label,target,choices] of [['Max Mode',o.max_mode?'On':'Off',['Off','On']],['Personalize','Off',['Off','On']],['Vocal Gender',null,['Male','Female']]]) {
      const active=group(doc,label,choices).filter(b=>selected(doc,b));
      if(target===null?active.length!==0:active.length!==1 || active[0].textContent.trim()!==target) throw new Error('More Options selection changed: '+label);
    }
  }
  async function configureOptions(doc,o) {
    let excludes;
    try {excludes=field(doc,['Exclude styles']);} catch {
      const controls=Array.from(doc.querySelectorAll('button,[role=button]')).filter(b=>b.textContent.trim().startsWith('More Options') && visible(doc,b));
      if(controls.length!==1) throw new Error('Cannot open More Options.');
      safeClick(controls[0]);excludes=await waitFor(()=>{try{return field(doc,['Exclude styles']);}catch{return false;}},3000);
    }
    try {slider(doc,'Duration');} catch {
      const custom=group(doc,'Duration',['Custom','Auto']).find(b=>b.textContent.trim()==='Custom');
      safeClick(custom);await waitFor(()=>{try{return slider(doc,'Duration');}catch{return false;}},3000);
    }
    write(doc,excludes,o.exclude_styles);await frame(doc);
    await setGroup(doc,'Vocal Gender',null,['Male','Female']);
    await setGroup(doc,'Max Mode',o.max_mode?'On':'Off');
    await setGroup(doc,'Personalize','Off');
    await setSlider(doc,'Weirdness',o.weirdness);
    await setSlider(doc,'Style Influence',o.style_influence);
    await setSlider(doc,'Variety',['off','normal','high','extra','max'].indexOf(o.variety));
    await setSlider(doc,'Duration',o.duration_seconds);
    verifyOptions(doc,o);
  }
  async function prepare(doc, draft, verifiedEmail) {
    validate(draft);
    if (verifiedEmail?.toLowerCase() !== draft.account_email.toLowerCase()) throw new Error('Suno account does not match. Sign in to the requested account and prepare again.');
    const styles = field(doc, ['Styles', 'Style of Music']);
    const title = field(doc, ['Song Title (Optional)', 'Song Title', 'Title']);
    const lyrics = field(doc, ['Lyrics editor', 'Lyrics']);
    if (value(lyrics).trim()) throw new Error('Lyrics are not empty. Clear them yourself for instrumental music, then prepare again.');
    if ((value(styles).trim() && value(styles) !== draft.styles) || (value(title).trim() && value(title) !== draft.title)) {
      throw new Error('The Suno form contains another draft. Clear it yourself or use a new Suno tab, then prepare again.');
    }
    await configureOptions(doc, draft.more_options);
    // Only allowed More Options controls are clicked; never Create/submit.
    write(doc, styles, draft.styles); write(doc, title, draft.title);
    if (value(styles) !== draft.styles || value(title) !== draft.title || value(lyrics).trim()) throw new Error('Could not verify the prepared fields. Review Suno manually.');
    verifyOptions(doc,draft.more_options);
    return {title: draft.title, account_email: verifiedEmail, more_options:draft.more_options, state: 'Prepared'};
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
      await prepare(doc, draft, record.verifiedEmail);
      await new Promise(resolve => setTimeout(resolve, 600));
      await prepare(doc, draft, record.verifiedEmail); // Verify after React has processed input events.
      win.sessionStorage.removeItem(storageKey);
      banner(doc, `Prepared for ${record.verifiedEmail}. More Options verified: Weirdness ${draft.more_options.weirdness}%, Style Influence ${draft.more_options.style_influence}%, Variety ${draft.more_options.variety}, Duration ${draft.more_options.duration_seconds}s. Lyrics are empty (instrumental). Review the form and click Create yourself. Nothing was generated or downloaded.`);
    } catch (e) {
      win.sessionStorage.removeItem(storageKey);
      banner(doc, e.message || 'Preparation failed; review Suno manually.', true);
    }
  }
  return {validate,decode,accountEmail,prepare,verifyOptions,boot};
})();
if (typeof window !== 'undefined' && !globalThis.LIMINAL_SUNO_TEST) void LiminalSunoPrep.boot(window);
