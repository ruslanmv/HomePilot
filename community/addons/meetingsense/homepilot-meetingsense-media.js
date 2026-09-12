/**
 * MeetingSense media-routing contract.
 *
 * Loaded immediately after homepilot-meetingsense.js. It keeps the recorder's proven audio
 * graph/socket implementation, but owns device acquisition so the meeting preflight and the
 * Audio & Video settings are actually authoritative.
 */
(function () {
    'use strict';

    var recorder = window.hpMeetingSense;
    if (!recorder || recorder.__homepilotMediaRoutingV1) return;

    var STORAGE_KEY = 'homepilot_media_preferences_v1';
    var originalStartWithStreams =
        typeof recorder.startWithStreams === 'function' ? recorder.startWithStreams.bind(recorder) : null;
    var originalMediaClock =
        typeof recorder._mediaClockMs === 'function' ? recorder._mediaClockMs.bind(recorder) : null;

    function stopStream(stream) {
        if (!stream || !stream.getTracks) return;
        stream.getTracks().forEach(function (track) {
            try { track.stop(); } catch (_) { /* already stopped */ }
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

    function trackLabel(stream) {
        try {
            if (recorder.internals && typeof recorder.internals.trackLabel === 'function') {
                return recorder.internals.trackLabel(stream);
            }
            var track = stream && stream.getVideoTracks && stream.getVideoTracks()[0];
            return (track && track.label ? track.label : '').trim();
        } catch (_) {
            return '';
        }
    }

    async function acquire(options) {
        var opts = options || {};
        var plan = capturePlan(opts);
        var display = null;
        var mic = null;

        if ((plan.meetingAudio || plan.screen) &&
            (!navigator.mediaDevices || typeof navigator.mediaDevices.getDisplayMedia !== 'function')) {
            return { ok: false, error: 'Screen / meeting-audio capture is not supported by this browser.' };
        }
        if (plan.microphone &&
            (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== 'function')) {
            return { ok: false, error: 'Microphone capture is not supported by this browser.' };
        }

        if (plan.meetingAudio || plan.screen) {
            try {
                display = await navigator.mediaDevices.getDisplayMedia({
                    video: true,
                    audio: plan.meetingAudio,
                });
            } catch (error) {
                return {
                    ok: false,
                    error: errorText(plan.meetingAudio ? 'Meeting audio / screen share' : 'Screen share', error),
                };
            }

            if (plan.meetingAudio && !display.getAudioTracks().length) {
                stopStream(display);
                return {
                    ok: false,
                    error: 'Meeting audio was enabled, but the shared source has no audio track. Share a browser tab and enable “Share audio”, or turn Meeting audio off.',
                };
            }
        }

        if (plan.microphone) {
            try {
                mic = await navigator.mediaDevices.getUserMedia({
                    audio: microphoneConstraints(opts),
                    video: false,
                });
            } catch (error) {
                stopStream(display);
                return { ok: false, error: errorText('Selected microphone', error) };
            }
        }

        return { ok: true, display: display, mic: mic, plan: plan };
    }

    async function startScreenOnly(screen, options) {
        var opts = options || {};
        if (!screen || !screen.getVideoTracks || !screen.getVideoTracks().length) {
            stopStream(screen);
            return { ok: false, error: 'Screen & slides is enabled, but no live screen track was returned.' };
        }
        if (typeof recorder._connect !== 'function' || typeof recorder._startWatching !== 'function') {
            stopStream(screen);
            return { ok: false, error: 'This MeetingSense build cannot start a screen-only meeting.' };
        }

        recorder._windowTitle = opts.windowTitle || trackLabel(screen);
        recorder.audioMode = 'none';
        recorder._channels = 1;
        recorder._opts = opts;
        recorder._elapsedSamples = 0;
        recorder._screenOnlyStartedAt = typeof performance !== 'undefined' ? performance.now() : Date.now();
        recorder._tracks = recorder._tracks || [];
        screen.getTracks().forEach(function (track) {
            recorder._tracks.push(track);
        });

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

    // A screen-only meeting has no audio sample clock. Keep slide timestamps meaningful by
    // using elapsed wall time only while audioMode is explicitly `none`.
    if (originalMediaClock) {
        recorder._mediaClockMs = function () {
            if (this.audioMode === 'none' && this._screenOnlyStartedAt != null) {
                var now = typeof performance !== 'undefined' ? performance.now() : Date.now();
                return Math.max(0, Math.round(now - this._screenOnlyStartedAt));
            }
            return originalMediaClock();
        };
    }

    recorder.start = async function (options) {
        var opts = options || {};
        if (this.recording) return { ok: false, error: 'already recording' };
        if (!opts.conversationId) return { ok: false, error: 'conversationId is required' };

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

        var result = await originalStartWithStreams({ screen: display, mic: mic }, opts);
        if (!result || !result.ok) {
            // startWithStreams normally tears down what it accepted on failure. This is a
            // second idempotent stop so an older recorder cannot leave a granted device open.
            stopStream(display);
            stopStream(mic);
        }
        return result;
    };

    recorder.__homepilotMediaRoutingV1 = true;
    recorder.mediaRouting = {
        capturePlan: capturePlan,
        microphoneConstraints: microphoneConstraints,
        readPreferences: readPreferences,
        errorText: errorText,
        acquire: acquire,
    };
})();
