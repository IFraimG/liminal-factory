# Liminal Suno Prep

This local Chrome extension prepares a form and stops before Create. It does not generate, spend credits, publish, read/export cookies, or download music. Its content script runs only on `https://suno.com/*`; no cookies/downloads/tabs/debugger permission is requested. It reads the visible Account Email row, then fills the visible Styles and Song Title fields plus all mandatory More Options from the agent: Exclude styles, Weirdness, Style Influence, Variety, Duration, Max Mode, Personalize and instrumental vocal-gender state. Each value is read back before Prepared appears. A nonempty Lyrics field or a different existing draft blocks preparation.

1. In Chrome, open `chrome://extensions` and enable Developer mode.
2. Select Load unpacked and choose this folder (containing manifest.json).
3. Sign in to Suno using your intended account in the same Chrome profile.
4. In Liminal Factory, wait for Music Brief to complete and Music Approval to show Waiting for Approval.
5. In Music studio enter the email shown in Suno Account settings, select a prompt, then click Prepare form in Chrome.
6. The extension verifies the account on Suno Settings, returns to Create, and fills the form. Wait for its green Prepared banner; inspect the fields before clicking Create yourself.

A preparation link expires after 30 minutes. If the account/form cannot be verified, the extension shows an error instead of claiming success. When Suno changes its form, selectors may need an update. Supported visible English labels include Advanced/Custom, Styles, Song Title (Optional), and Lyrics editor. Clear a conflicting draft yourself, then prepare again.

Uninstall through Chrome Extensions. Source is included: manifest.json and prep.js. No connection to the Liminal backend, credentials or account API is used by the extension. Title, prompt and target email are passed in a URL fragment; sessionStorage holds this draft only while verifying/preparing and is cleared on success or error.

More Options are mandatory in handoff version 2. Older briefs must first be enriched using Music studio → Ask agent for More Options. Values are creative recommendations with rationale from the preceding music brief, not measurements or hardcoded defaults. Missing/unavailable controls or a failed read-back produce an error. The extension may click only Advanced/Custom and explicitly named More Options controls; Create, submit and downloads are never invoked.
