/* Customer voice agent console (F-15 / F-20).
 * Previously: REST-only "sessions" with no microphone, a hardcoded tenant header and
 * fake transcripts. Now: an authenticated session (SalesApi), a WebSocket stream bound
 * to the signed session token, real microphone capture (AudioWorklet -> PCM16 16 kHz
 * frames), playback of the synthesized WAV reply, and caller OTP over the stream.
 * All text is rendered with textContent. */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var micBtn = $('micBtn'), statusDot = $('statusDot'), sessionStatus = $('sessionStatus');
  var visualizer = $('visualizer'), feed = $('conversationFeed');
  var bargeInBtn = $('bargeInBtn'), handoffBtn = $('handoffBtn');
  var verifyOtpBtn = $('verifyOtpBtn'), requestOtpBtn = $('requestOtpBtn'), otpInput = $('otpInput');
  var verificationStatus = $('verificationStatus');
  var textForm = $('textTurnForm'), textInput = $('textTurnInput'), textBtn = $('textTurnBtn');

  var session = null;      // {session_id, session_token}
  var ws = null;
  var audio = null;        // {ctx, stream, node, source}
  var player = null;       // HTMLAudioElement currently playing
  var playerUrl = null;

  function addMessage(type, text) {
    var div = document.createElement('div');
    div.className = 'msg ' + type;
    div.textContent = text;
    feed.appendChild(div);
    feed.scrollTop = feed.scrollHeight;
  }

  function setStatus(kind, text) {
    statusDot.className = 'status-dot ' + kind;
    sessionStatus.textContent = text;
  }

  function setLive(live) {
    micBtn.classList.toggle('active', live);
    visualizer.classList.toggle('active-animation', live);
    [bargeInBtn, handoffBtn, requestOtpBtn, textInput, textBtn].forEach(function (el) { if (el) { el.disabled = !live; } });
  }

  function sessionHeaders() {
    return { 'Content-Type': 'application/json', 'X-Voice-Session-Token': session.session_token };
  }

  function stopPlayback() {
    if (player) { player.pause(); player = null; }
    if (playerUrl) { URL.revokeObjectURL(playerUrl); playerUrl = null; }
  }

  function playWav(b64) {
    stopPlayback();
    try {
      var bin = atob(b64);
      var bytes = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) { bytes[i] = bin.charCodeAt(i); }
      playerUrl = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }));
      player = new Audio(playerUrl);
      player.addEventListener('ended', stopPlayback);
      player.play().catch(function () { /* autoplay blocked: transcript is still shown */ });
    } catch (e) { /* malformed audio: ignore, text reply already rendered */ }
  }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) { ws.send(JSON.stringify(obj)); return true; }
    return false;
  }

  function onServerMessage(evt) {
    var msg;
    try { msg = JSON.parse(evt.data); } catch (e) { return; }
    switch (msg.type) {
      case 'SESSION_INITIALIZED':
        if (msg.disclosure_text) { addMessage('system', msg.disclosure_text); }
        break;
      case 'VAD_SPEECH_START':
        setStatus('active', 'Le client parle…');
        break;
      case 'VAD_SPEECH_STOP':
        setStatus('active', 'Analyse de la demande…');
        break;
      case 'TURN_COMPLETED':
        if (msg.user_transcript) { addMessage('user', msg.user_transcript); }
        if (msg.agent_response) { addMessage('agent', msg.agent_response); }
        if (msg.audio_base64) { playWav(msg.audio_base64); }
        setStatus('active', 'En écoute');
        break;
      case 'BARGE_IN_TRIGGERED':
      case 'BARGE_IN_CONFIRMED':
        stopPlayback();
        addMessage('system', 'Interruption : la réponse vocale a été coupée.');
        break;
      case 'OTP_SENT':
        verificationStatus.textContent = 'Code envoyé au client. Saisissez-le pour vérifier.';
        break;
      case 'OTP_UNAVAILABLE':
        verificationStatus.textContent = "Envoi de code indisponible : aucun canal SMS n'est configuré.";
        break;
      case 'CALLER_VERIFIED':
        verificationStatus.textContent = msg.verified ? 'Identité vérifiée.' : (msg.message || 'Code invalide ou expiré.');
        verificationStatus.classList.toggle('is-verified', !!msg.verified);
        if (msg.verified) { addMessage('system', 'Client vérifié par code à usage unique.'); }
        break;
      default:
        break;
    }
  }

  async function startMicrophone() {
    if (!navigator.mediaDevices || !window.AudioWorkletNode) {
      addMessage('system', "Ce navigateur ne permet pas la capture audio. Utilisez la saisie texte.");
      return;
    }
    var stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }
    });
    // A 16 kHz context makes the browser resample; the worklet emits 20 ms PCM16 frames.
    var ctx = new AudioContext({ sampleRate: 16000 });
    await ctx.audioWorklet.addModule('js/audio/pcm-capture-worklet.js');
    var source = ctx.createMediaStreamSource(stream);
    var node = new AudioWorkletNode(ctx, 'pcm-capture');
    node.port.onmessage = function (e) {
      if (ws && ws.readyState === WebSocket.OPEN) { ws.send(e.data); }
    };
    source.connect(node);
    audio = { ctx: ctx, stream: stream, node: node, source: source };
  }

  function stopMicrophone() {
    if (!audio) { return; }
    try { audio.source.disconnect(); audio.node.disconnect(); } catch (e) { /* already closed */ }
    audio.stream.getTracks().forEach(function (t) { t.stop(); });
    audio.ctx.close();
    audio = null;
  }

  function openStream() {
    return new Promise(function (resolve, reject) {
      var proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
      var url = proto + location.host + '/api/v1/voice/ws/' + encodeURIComponent(session.session_id) +
        '?token=' + encodeURIComponent(session.session_token);
      ws = new WebSocket(url);
      ws.binaryType = 'arraybuffer';
      ws.addEventListener('open', function () { resolve(); });
      ws.addEventListener('error', function () { reject(new Error('Flux vocal indisponible')); });
      ws.addEventListener('message', onServerMessage);
      ws.addEventListener('close', function () {
        if (session) { setStatus('idle', 'Flux vocal fermé'); }
      });
    });
  }

  async function startSession() {
    micBtn.disabled = true;
    setStatus('idle', 'Connexion…');
    try {
      var res = await window.SalesViews.getJson('/api/v1/voice/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          voice_mode: 'CUSTOMER',
          channel_type: 'WEBRTC',
          caller_identifier: $('callerInput').value.trim() || null,
          language: $('languageSelect').value,
          recording_consent: true
        })
      });
      if (!res.ok) { throw new Error(window.SalesViews.errorText(res)); }
      session = { session_id: res.data.session_id, session_token: res.data.session_token };
      await openStream();
      setLive(true);
      setStatus('active', 'En écoute');
      try {
        await startMicrophone();
      } catch (e) {
        addMessage('system', 'Micro non autorisé : la session continue en saisie texte.');
      }
    } catch (e) {
      addMessage('system', 'Impossible de démarrer la session vocale : ' + e.message);
      session = null;
      setStatus('idle', 'En attente de connexion');
    } finally {
      micBtn.disabled = false;
    }
  }

  async function endSession() {
    var s = session;
    session = null;
    stopMicrophone();
    stopPlayback();
    if (ws) { ws.close(); ws = null; }
    setLive(false);
    setStatus('idle', 'Session terminée');
    if (s) {
      await window.SalesApi.fetch('/api/v1/voice/sessions/' + encodeURIComponent(s.session_id) + '/end', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Voice-Session-Token': s.session_token },
        body: JSON.stringify({ reason: 'USER_COMPLETED' })
      }).catch(function () { /* session expires server-side anyway */ });
    }
    addMessage('system', 'Session vocale terminée.');
  }

  micBtn.addEventListener('click', function () { if (session) { endSession(); } else { startSession(); } });

  bargeInBtn.addEventListener('click', function () { if (session) { send({ type: 'BARGE_IN' }); } });

  if (requestOtpBtn) {
    requestOtpBtn.addEventListener('click', function () {
      if (send({ type: 'REQUEST_OTP' })) { verificationStatus.textContent = 'Envoi du code…'; }
    });
  }

  verifyOtpBtn.addEventListener('click', function () {
    var otp = otpInput.value.trim();
    if (!session) { verificationStatus.textContent = "Démarrez d'abord la session vocale."; return; }
    if (!/^[0-9]{4,8}$/.test(otp)) { verificationStatus.textContent = 'Saisissez le code reçu par le client.'; return; }
    send({ type: 'VERIFY_CALLER', otp_code: otp });
    otpInput.value = '';
  });

  if (textForm) {
    textForm.addEventListener('submit', function (e) {
      e.preventDefault();
      var text = textInput.value.trim();
      if (!text || !session) { return; }
      if (send({ type: 'TEXT_TURN', text: text })) {
        textInput.value = '';
        setStatus('active', 'Analyse de la demande…');
      }
    });
  }

  handoffBtn.addEventListener('click', async function () {
    if (!session) { return; }
    var res = await window.SalesViews.getJson('/api/v1/voice/sessions/' + encodeURIComponent(session.session_id) + '/handoff', {
      method: 'POST',
      headers: sessionHeaders(),
      body: JSON.stringify({ reason: 'Client demande un conseiller', target_department: 'SUPPORT' })
    });
    if (res.ok) {
      addMessage('system', 'Transfert vers la file ' + (res.data.assigned_queue || 'SUPPORT') + '.');
    } else {
      addMessage('system', 'Transfert impossible : ' + window.SalesViews.errorText(res));
    }
  });

  window.addEventListener('beforeunload', function () { stopMicrophone(); if (ws) { ws.close(); } });
})();
