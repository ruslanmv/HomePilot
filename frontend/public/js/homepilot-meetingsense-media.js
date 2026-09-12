/**
 * MeetingSense media-routing and source-health contract.
 *
 * Loaded immediately after homepilot-meetingsense.js. The proven recorder continues to own
 * its Web Audio graph, VAD, socket, and keyframe sampler; this layer owns browser device
 * acquisition so preflight choices and Audio & Video preferences are authoritative. It also
 * exposes the already-granted display stream to the Meeting Workspace — never a second share.
 */
(function () {
    'use strict';

    var recorder = window.hpMeetingSense;
    if (!recorder || recorder.__homepilotMediaRoutingV1) return;

    var STORAGE_KEY = 'homepilot_media_preferences_v1';
    var SIGNAL_RMS = 0.003;
    var NO_SIGNAL_MS = 2500;
    var originalStartWithStreams =
        typeof recorder.startWithStreams === 'function' ? recorder.startWithStreams.bind(recorder) : null;
    var originalMediaClock =
        typeof recorder._mediaClockMs === 'function' ? recorder._mediaClockMs.bind(recorder) : null;
    var originalOnAudio =
        typeof recorder._onAudio === 'function' ? recorder._onAudio.bind(recorder) : null;
    var originalStop = typeof recorder.stop === 'function' ? recorder.stop.bind(recorder) : null;
    var sourceCache = Object.create(null);
    var lastSignal = { meeting_audio: 0, microphone: 0 };

    function nowMs() {
        return typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now();
    }

    function dispatch(name, detail) {
        try { window.dispatchEvent(new CustomEvent(name, { detail: detail })); } catch (_) { /* no DOM */ }
    }

    function stopStream(stream) {
        if (!stream || !stream.getTracks) return;
        stream.getTracks().forEach(function (track) {
            try { track.stop(); } catch (_) { /* already stopped */ }
        });
    }

    function sourceEvent(source, requested, state, label, level, error) {
        var detail = {
            source: source,
            requested: !!requested,
            state: state,
            label: label || null,
            level: typeof level === 'number' ? level : 0,
            error: error || null,
            lastSignalAt: lastSignal[source] || null,
        };
        var previous = sourceCache[source];
        var signature = [detail.requested, detail.state, detail.label || '', detail.error || ''].join('|');
        if (previous === signature) return;
        sourceCache[source] = signature;
        dispatch('ms:source_changed', detail);
    }

    function screenEvent(stream, requested, state, error) {
        var label = trackLabel(stream);
        sourceEvent('screen', requested, state, label, 0, error);
        dispatch('ms:screen_source', {
            stream: stream || null,
            requested: !!requested,
            state: state,
            label: label || null,
            error: error || null,
        });
    }

    function readPreferences() {
        var raw = {};
        try {
            raw = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '{}') || {};
        } catch (_) {
            raw = {};
        }
        return {
            microphoneDeviceId: typeof raw.microphoneDeviceId === 'string' ? raw.microphoneDeviceId : '',
            echoCancellation: typeof raw.echoCancellation === 'boolean' ? raw.echoCancellation : true,
            noiseSuppression: typeof raw.noiseSuppression === 'boolean' ? raw.noiseSuppression : true,
            autoGainControl: typeof raw.autoGainControl === 'boolean' ? raw.autoGainControl : true,
        };
    }

    function capturePlan(options) {
        var opts = options || {};
        return {
            meetingAudio: opts.audio !== false,
            microphone: opts.mic !== false,
            screen: !!opts.watch,
        };
    }

    function microphoneConstraints(options) {
        var opts = options || {};
        var saved = readPreferences();
        var constraints = {
            echoCancellation:
                typeof opts.echoCancellation === 'boolean' ? opts.echoCancellation : saved.echoCancellation,
            noiseSuppression:
                typeof opts.noiseSuppression === 'boolean' ? opts.noiseSuppression : saved.noiseSuppression,
            autoGainControl:
                typeof opts.autoGainControl === 'boolean' ? opts.autoGainControl : saved.autoGainControl,
        };
        var deviceId =
            typeof opts.microphoneDeviceId === 'string' ? opts.microphoneDeviceId : saved.microphoneDeviceId;
        if (deviceId) constraints.deviceId = { exact: deviceId };
        return constraints;
    }

    function errorText(source, error) {
        var name = error && error.name ? String(error.name) : 'CaptureError';
        var message = error && error.message ? String(error.message) : '';
        var suffix = message && message !== name ? ': ' + message : '';
        return source + ' could not be opened (' + name + ')' + suffix;
    }

    function errorState(error) {
        var name = error && error.name ? String(error.name) : '';
        return name === 'NotAllowedError' || name === 'PermissionDeniedError' ? 'blocked' : 'error';
    }

    function trackLabel(stream, kind) {
        try {
            if (!stream) return '';
            if (!kind && recorder.internals && typeof recorder.internals.trackLabel === 'function') {
                return recorder.internals.trackLabel(stream);
            }
            var tracks = kind === 'audio'
                ? (stream.getAudioTracks ? stream.getAudioTracks() : [])
                : (stream.getVideoTracks ? stream.getVideoTracks() : []);
            var track = tracks[0];
            return (track && track.label ? track.label : '').trim();
        } catch (_) {
            return '';
        }
    }

    function onEnded(track, fn) {
        if (track && typeof track.addEventListener === 'function') track.addEventListener('ended', fn);
    }

    function announcePlan(plan) {
        sourceEvent('meeting_audio', plan.meetingAudio, plan.meetingAudio ? 'connecting' : 'off', null, 0, null);
        sourceEvent('microphone', plan.microphone, plan.microphone ? 'connecting' : 'off', null, 0, null);
        screenEvent(null, plan.screen, plan.screen ? 'connecting' : 'off', null);
    }

    async function acquire(options) {
        var opts = options || {};
        var plan = capturePlan(opts);
        var display = null;
        var mic = null;
        announcePlan(plan);

        if ((plan.meetingAudio || plan.screen) &&
            (!navigator.mediaDevices || typeof navigator.mediaDevices.getDisplayMedia !== 'function')) {
            var displayUnsupported = 'Screen / meeting-audio capture is not supported by this browser.';
            if (plan.meetingAudio) sourceEvent('meeting_audio', true, 'error', null, 0, displayUnsupported);
            if (plan.screen) screenEvent(null, true, 'error', displayUnsupported);
            return { ok: false, error: displayUnsupported };
        }
        if (plan.microphone &&
            (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== 'function')) {
            var micUnsupported = 'Microphone capture is not supported by this browser.';
            sourceEvent('microphone', true, 'error', null, 0, micUnsupported);
            return { ok: false, error: micUnsupported };
        }

        if (plan.meetingAudio || plan.screen) {
            try {
                display = await navigator.mediaDevices.getDisplayMedia({
                    video: true,
                    audio: plan.meetingAudio,
                });
            } catch (error) {
                var displayError = errorText(plan.meetingAudio ? 'Meeting audio / screen share' : 'Screen share', error);
                var displayState = errorState(error);
                if (plan.meetingAudio) sourceEvent('meeting_audio', true, displayState, null, 0, displayError);
                if (plan.screen) screenEvent(null, true, displayState, displayError);
                return { ok: false, error: displayError };
            }

            if (plan.meetingAudio && !display.getAudioTracks().length) {
                var noAudio = 'Meeting audio was enabled, but the shared source has no audio track. Share a browser tab and enable “Share audio”, or turn Meeting audio off.';
                sourceEvent('meeting_audio', true, 'error', null, 0, noAudio);
                if (plan.screen) screenEvent(display, true, 'receiving', null);
                stopStream(display);
                return { ok: false, error: noAudio };
            }
        }

        if (plan.microphone) {
            try {
                mic = await navigator.mediaDevices.getUserMedia({
                    audio: microphoneConstraints(opts),
                    video: false,
                });
            } catch (error) {
                var micError = errorText('Selected microphone', error);
                sourceEvent('microphone', true, errorState(error), null, 0, micError);
                stopStream(display);
                return { ok: false, error: micError };
            }
        }

        return { ok: true, display: display, mic: mic, plan: plan };
    }

    function rememberStreams(display, mic, plan) {
        recorder._homepilotDisplayStream = display || null;
        recorder._homepilotMicStream = mic || null;
        recorder._homepilotCapturePlan = plan || null;

        var systemTrack = display && display.getAudioTracks ? display.getAudioTracks()[0] : null;
        var micTrack = mic && mic.getAudioTracks ? mic.getAudioTracks()[0] : null;
        var videoTrack = display && display.getVideoTracks ? display.getVideoTracks()[0] : null;

        if (plan.meetingAudio && systemTrack) {
            sourceEvent('meeting_audio', true, 'no_signal', systemTrack.label || null, 0, null);
            onEnded(systemTrack, function () {
                sourceEvent('meeting_audio', true, 'lost', systemTrack.label || null, 0, 'Meeting audio source disconnected.');
            });
        }
        if (plan.microphone && micTrack) {
            sourceEvent('microphone', true, 'no_signal', micTrack.label || null, 0, null);
            onEnded(micTrack, function () {
                sourceEvent('microphone', true, 'lost', micTrack.label || null, 0, 'Microphone source disconnected.');
            });
        }
        if (plan.screen && videoTrack) {
            screenEvent(display, true, 'receiving', null);
            onEnded(videoTrack, function () {
                screenEvent(display, true, 'lost', 'Screen sharing stopped.');
            });
        }
    }

    async function startScreenOnly(screen, options) {
        var opts = options || {};
        var plan = capturePlan(opts);
        if (!screen || !screen.getVideoTracks || !screen.getVideoTracks().length) {
            stopStream(screen);
            var missing = 'Screen & slides is enabled, but no live screen track was returned.';
            screenEvent(null, true, 'error', missing);
            return { ok: false, error: missing };
        }
        if (typeof recorder._connect !== 'function' || typeof recorder._startWatching !== 'function') {
            stopStream(screen);
            var unsupported = 'This MeetingSense build cannot start a screen-only meeting.';
            screenEvent(null, true, 'error', unsupported);
            return { ok: false, error: unsupported };
        }

        recorder._windowTitle = opts.windowTitle || trackLabel(screen);
        recorder.audioMode = 'none';
        recorder._channels = 1;
        recorder._opts = opts;
        recorder._elapsedSamples = 0;
        recorder._screenOnlyStartedAt = nowMs();
        recorder._tracks = recorder._tracks || [];
        screen.getTracks().forEach(function (track) { recorder._tracks.push(track); });
        rememberStreams(screen, null, plan);

        var opened = await recorder._connect(opts);
        if (!opened || !opened.ok) {
            if (typeof recorder._teardown === 'function') recorder._teardown();
            else stopStream(screen);
            return opened || { ok: false, error: 'The meeting session could not start.' };
        }

        recorder.recording = true;
        var watching = recorder._startWatching(screen, opts);
        return {
            ok: true,
            meetingId: recorder.meetingId,
            audioMode: 'none',
            watching: watching,
        };
    }

    if (originalMediaClock) {
        recorder._mediaClockMs = function () {
            if (this.audioMode === 'none' && this._screenOnlyStartedAt != null) {
                return Math.max(0, Math.round(nowMs() - this._screenOnlyStartedAt));
            }
            return originalMediaClock();
        };
    }

    function updateAudioHealth() {
        var plan = recorder._homepilotCapturePlan || {};
        var levels = Array.isArray(recorder.levels) ? recorder.levels : [];
        var mode = recorder.audioMode;
        var systemLevel = mode === 'system+mic' || mode === 'system' ? Number(levels[0] || 0) : 0;
        var micIndex = mode === 'system+mic' ? 1 : 0;
        var micLevel = mode === 'system+mic' || mode === 'mic' ? Number(levels[micIndex] || 0) : 0;
        var t = nowMs();

        function update(source, requested, level, stream) {
            if (!requested) return;
            var label = trackLabel(stream, 'audio') || null;
            if (level > SIGNAL_RMS) {
                lastSignal[source] = t;
                sourceEvent(source, true, 'receiving', label, level, null);
                return;
            }
            var last = lastSignal[source] || 0;
            if (!last || t - last >= NO_SIGNAL_MS) {
                sourceEvent(source, true, 'no_signal', label, level, null);
            }
        }

        update('meeting_audio', !!plan.meetingAudio, systemLevel, recorder._homepilotDisplayStream);
        update('microphone', !!plan.microphone, micLevel, recorder._homepilotMicStream);
    }

    if (originalOnAudio) {
        recorder._onAudio = function (chunk) {
            var result = originalOnAudio(chunk);
            updateAudioHealth();
            return result;
        };
    }

    recorder.getScreenPreviewStream = function () {
        var plan = this._homepilotCapturePlan || {};
        return plan.screen ? (this._homepilotDisplayStream || null) : null;
    };

    recorder.resumeScreenCapture = async function () {
        var plan = this._homepilotCapturePlan || {};
        if (!this.recording || !plan.screen) return { ok: false, error: 'No live meeting is waiting for screen capture.' };
        if (!navigator.mediaDevices || typeof navigator.mediaDevices.getDisplayMedia !== 'function') {
            return { ok: false, error: 'Screen sharing is not supported by this browser.' };
        }
        screenEvent(null, true, 'connecting', null);
        var stream;
        try {
            stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
        } catch (error) {
            var message = errorText('Screen share', error);
            screenEvent(null, true, errorState(error), message);
            return { ok: false, error: message };
        }
        var track = stream.getVideoTracks && stream.getVideoTracks()[0];
        if (!track) {
            stopStream(stream);
            var missing = 'No live screen track was returned.';
            screenEvent(null, true, 'error', missing);
            return { ok: false, error: missing };
        }
        if (typeof this._stopWatching === 'function') this._stopWatching();
        this._homepilotDisplayStream = stream;
        this._tracks = this._tracks || [];
        stream.getTracks().forEach(function (item) { recorder._tracks.push(item); });
        onEnded(track, function () { screenEvent(stream, true, 'lost', 'Screen sharing stopped.'); });
        var watching = typeof this._startWatching === 'function' ? this._startWatching(stream, this._opts || {}) : false;
        screenEvent(stream, true, watching ? 'receiving' : 'error', watching ? null : 'Screen preview could not start.');
        return watching ? { ok: true, stream: stream } : { ok: false, error: 'Screen preview could not start.' };
    };

    recorder.start = async function (options) {
        var opts = options || {};
        if (this.recording) return { ok: false, error: 'already recording' };
        if (!opts.conversationId) return { ok: false, error: 'conversationId is required' };

        sourceCache = Object.create(null);
        lastSignal = { meeting_audio: 0, microphone: 0 };
        var acquired = await acquire(opts);
        if (!acquired.ok) return acquired;

        var display = acquired.display;
        var mic = acquired.mic;
        var plan = acquired.plan;
        var hasSystemAudio = !!(display && display.getAudioTracks && display.getAudioTracks().length);

        if (!hasSystemAudio && !mic) {
            if (plan.screen && display) return startScreenOnly(display, opts);
            stopStream(display);
            return {
                ok: false,
                error: 'Choose at least one capture source: Meeting audio, My microphone, or Screen & slides.',
                audioMode: 'none',
            };
        }

        if (!originalStartWithStreams) {
            stopStream(display);
            stopStream(mic);
            return { ok: false, error: 'This MeetingSense build cannot accept routed media streams.' };
        }

        rememberStreams(display, mic, plan);
        var result = await originalStartWithStreams({ screen: display, mic: mic }, opts);
        if (!result || !result.ok) {
            stopStream(display);
            stopStream(mic);
        }
        return result;
    };

    if (originalStop) {
        recorder.stop = async function () {
            var result;
            try {
                result = await originalStop();
            } finally {
                var plan = this._homepilotCapturePlan || {};
                sourceEvent('meeting_audio', !!plan.meetingAudio, 'off', null, 0, null);
                sourceEvent('microphone', !!plan.microphone, 'off', null, 0, null);
                screenEvent(null, !!plan.screen, 'off', null);
                this._homepilotDisplayStream = null;
                this._homepilotMicStream = null;
                this._homepilotCapturePlan = null;
            }
            return result;
        };
    }

    recorder.__homepilotMediaRoutingV1 = true;
    recorder.mediaRouting = {
        capturePlan: capturePlan,
        microphoneConstraints: microphoneConstraints,
        readPreferences: readPreferences,
        errorText: errorText,
        acquire: acquire,
    };
})();
