// captcha-client.js (updated for animations, checkmark, tooltip behavior)
const BACKEND_ORIGIN = ''; // keep blank if serving from Flask

function apiPath(path) {
  if (!BACKEND_ORIGIN) return path;
  return BACKEND_ORIGIN + path;
}

async function newCaptcha() {
  const r = await fetch(apiPath('/captcha/new'));
  return await r.json();
}
async function verifyCaptcha(token, answer) {
  const r = await fetch(apiPath('/captcha/verify'), {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ token, answer })
  });
  return await r.json();
}
async function hintRequest(token) {
  const r = await fetch(apiPath('/captcha/hint'), {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ token })
  });
  return await r.json();
}

function el(id){ return document.getElementById(id); }
function showMsg(id, text, isError=true){
  const e = el(id); if(!e) return;
  e.textContent = text; e.style.color = isError ? '#b91c1c' : '#065f46';
}

/* Renders animated hint box (only on explicit request) */
function renderHintBoxAnimated(containerId, hintText, meta, challenge, userAttempt=null){
  const container = el(containerId); if(!container) return;
  container.innerHTML = ''; // clear
  // wrapper with animation class
  const wrapper = document.createElement('div');
  wrapper.className = 'hint-box animated-in';
  // title
  const h = document.createElement('div'); h.className = 'hint-title'; h.textContent = 'Helpful hint';
  wrapper.appendChild(h);
  // text
  const p = document.createElement('div'); p.className = 'hint-text'; p.textContent = hintText || '';
  wrapper.appendChild(p);
  // steps
  const steps = document.createElement('ol'); steps.className = 'hint-steps';
  if (challenge === 'dots') {
    steps.innerHTML = `
      <li>Zoom into a small quadrant and count slowly.</li>
      <li>Scan left→right row-by-row and mark groups of 5.</li>
      <li>Ignore decorative cross-marks; focus on round dot shapes.</li>`;
  } else if (challenge === 'loops'){
    steps.innerHTML = `
      <li>Trace strokes; closed strokes are loops.</li>
      <li>Count nested loops too; track one stroke at a time.</li>
      <li>Follow lines past crossings — crossings aren't loops by themselves.</li>`;
  } else if (challenge === 'squares'){
    steps.innerHTML = `
      <li>Find closed 4-sided enclosures (closed shapes only).</li>
      <li>Nested small squares count separately.</li>
      <li>Trace boundaries to confirm closure.</li>`;
  } else {
    steps.innerHTML = `<li>Break image into parts and count piecewise.</li>`;
  }
  wrapper.appendChild(steps);

  // meta
  if(meta){
    const metaDiv = document.createElement('div'); metaDiv.className='hint-meta';
    metaDiv.innerHTML = `<small class="small-muted">Approx: dots ${meta.dots}, loops ${meta.loops}, squares ${meta.squares}</small>`;
    wrapper.appendChild(metaDiv);
  }
  if(userAttempt !== null){
    const u = document.createElement('div'); u.className='hint-user'; u.innerHTML = `<strong>Your attempt:</strong> ${userAttempt}`;
    wrapper.appendChild(u);
  }
  container.appendChild(wrapper);

  // small entrance stagger for steps
  const liItems = wrapper.querySelectorAll('.hint-steps li');
  liItems.forEach((li, idx) => {
    li.style.opacity = 0;
    li.style.transform = 'translateY(6px)';
    setTimeout(()=>{ li.style.transition = 'all 260ms cubic-bezier(.2,.9,.2,1)'; li.style.opacity=1; li.style.transform='translateY(0)' }, 120 * (idx+1));
  });
}

/* lock UI on success, show check, disable hint/verify/refresh/input and enable submit */
/* lock UI on success, show final message and clear captcha error if present */
function onCaptchaSolved(opts = {}) {
  const {
    inputId='captchaInput',
    refreshId='captchaRefresh',
    verifyBtnId='captchaVerifyBtn',
    hintBtnId='captchaHintBtn',
    hintBoxId='captchaHintBox',
    msgId='captchaMsg',
    checkId='captchaCheck',
    errCaptchaId='errCaptcha',
    submitEnableCallback=null
  } = opts;

  // disable interactive controls
  const input = document.getElementById(inputId);
  const refresh = document.getElementById(refreshId);
  const verify = document.getElementById(verifyBtnId);
  const hint = document.getElementById(hintBtnId);
  [input, refresh, verify, hint].forEach(e => { if (e) { e.disabled = true; e.setAttribute('aria-disabled','true'); }});

  // hide/clear hint box
  const hintBox = document.getElementById(hintBoxId);
  if (hintBox) hintBox.innerHTML = '';

  // hide any visible captcha error message (fix for "Please solve the challenge")
  const errEl = document.getElementById(errCaptchaId);
  if (errEl) errEl.classList.add('hidden');

  // show final success message and the green check
  if (msgId && document.getElementById(msgId)) {
    const msg = document.getElementById(msgId);
    msg.textContent = 'Captcha solved successfully.';
    msg.style.color = '#065f46';
  }
  const chk = document.getElementById(checkId);
  if (chk) chk.classList.add('visible');

  // mark validated/locked
  window._kolam_validated = true;
  window._kolam_locked = true;

  // enable submit (and remove tooltip) via callback if provided
  if (submitEnableCallback) submitEnableCallback(true);
  const submitBtn = document.getElementById('submitBtn');
  if (submitBtn) { submitBtn.disabled = false; submitBtn.removeAttribute('title'); }
}


/* init widget */
async function initKolamWidget(opts = {}){
  const {
    imgId='captchaImg', questionId='captchaQuestion', inputId='captchaInput',
    refreshId='captchaRefresh', msgId='captchaMsg', hintBoxId='captchaHintBox',
    verifyBtnId='captchaVerifyBtn', hintBtnId='captchaHintBtn', checkId='captchaCheck',
    submitEnableCallback=null
  } = opts;

  let token = null, meta=null, challenge=null;

  async function load(){
    window._kolam_locked = false; window._kolam_validated = false;
    showMsg(msgId, 'Loading a fresh Kolam challenge…', false);
    const j = await newCaptcha();
    token = j.token; meta = j.meta || {}; challenge = j.challenge || (j.challenge_text||'').toLowerCase().includes('loop') ? 'loops' : (j.challenge_text||'').toLowerCase().includes('square') ? 'squares' : 'dots';
    const url = j.image_url.startsWith('http') ? j.image_url : (BACKEND_ORIGIN ? (BACKEND_ORIGIN + j.image_url) : j.image_url);
    const img = el(imgId);
    if(img){
      img.classList.remove('loaded');
      img.src = url + '?t=' + Date.now();
      // once loaded, add loaded class for fade-in
      img.onload = () => { img.classList.add('loaded'); };
      img.onerror = () => { img.classList.add('loaded'); /* keep placeholder */ };
    }
    if(el(questionId)) el(questionId).textContent = j.challenge_text || 'Count the requested feature';
    if(el(inputId)) { el(inputId).value=''; el(inputId).disabled=false; }
    [refreshId, verifyBtnId, hintBtnId].forEach(id=>{ const e=el(id); if(e){ e.disabled=false; }});
    if(el(hintBoxId)) el(hintBoxId).innerHTML = '';
    if(el(msgId)) el(msgId).textContent='';
    if(el(checkId)) el(checkId).classList.remove('visible');
    if(submitEnableCallback) submitEnableCallback(false);
    window._kolam_current = { token, meta, challenge };
  }

  // wire refresh (prevent refresh after solved)
  el(refreshId).addEventListener('click', async () => {
    if(window._kolam_locked) return;
    await load();
  });

  // verify
  el(verifyBtnId).addEventListener('click', async () => {
    if(window._kolam_locked) return;
    const raw = (el(inputId).value||'').trim();
    if(!raw){ showMsg(msgId, 'Please enter a numeric answer.'); return; }
    showMsg(msgId, 'Checking your answer…', false);
    const res = await verifyCaptcha(token, raw);
    if(res.success){
      onCaptchaSolved({ inputId, refreshId, verifyBtnId, hintBtnId, hintBoxId, msgId, checkId, submitEnableCallback });
    } else {
      // wrong: short message only
      showMsg(msgId, res.hint || 'Incorrect — try again or press "Give me a hint".');
      if(res.refresh && !window._kolam_locked) await load();
      if(submitEnableCallback) submitEnableCallback(false);
    }
  });

  // hint button (explicit)
  el(hintBtnId).addEventListener('click', async () => {
    if(window._kolam_locked) return;
    showMsg(msgId, 'Preparing a helpful hint…', false);
    const r = await hintRequest(token);
    renderHintBoxAnimated(hintBoxId, r.hint || 'No hint available.', meta, challenge, null);
    showMsg(msgId, r.hint || 'Hint ready.', false);
  });

  // small UX: submit tooltip
  const submitBtn = document.getElementById('submitBtn');
  if(submitBtn){
    submitBtn.setAttribute('title','Complete captcha to enable');
    submitBtn.disabled = true;
  }

  // when submitEnableCallback called (by solved), remove tooltip
  const wrappedSubmitEnable = (ok) => {
    if(submitBtn){
      submitBtn.disabled = !ok;
      if(ok) { submitBtn.removeAttribute('title'); }
      else { submitBtn.setAttribute('title','Complete captcha to enable'); }
    }
  };

  await load();
  return () => token;
}
