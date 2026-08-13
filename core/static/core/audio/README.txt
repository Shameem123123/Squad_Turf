SquadTurf notification sounds — how it works now
================================================================

By design, every event now plays the SAME single sound — like a normal
phone's default notification tone, not a distinct jingle per event type.
This changed from an earlier version that had a different whistle sound
per event; that made a match get its own sound, a join request its own
sound, etc. That's been intentionally simplified to one generic tone.

  default.wav   -> the one sound used for every event, in the one case
                   where it's needed: see "Where this sound actually
                   plays" below.

The old per-event files (new_match.wav, join_request.wav,
request_accepted.wav, request_declined.wav, player_left.wav,
match_filled.wav, match_cancelled.wav, reminder.wav, whistle.wav) are no
longer referenced by any code and can be deleted — they're left in place
only in case you want to repurpose one as the new default.wav.

To try a different default sound, just overwrite default.wav — keep the
exact filename, drop your file in, refresh the page. No code changes
needed.

Format tips:
  - .wav, .mp3, .ogg, or .m4a all work — just keep the filename
    "default.wav" (extension included). If you use a different
    extension, also update DEFAULT_AUDIO_SRC in static/core/js/push.js
    to match.
  - Keep the clip short: 0.2-1.0 seconds.

Where this sound actually plays:
  - If the site/app is fully closed, or a tab is open but not focused
    (backgrounded, minimized, or you're in another app), the OS/browser
    shows the system push notification (status-bar banner, slides down
    like WhatsApp) using ITS OWN default notification tone. default.wav
    is NOT played in this case — the system's own sound is the only one,
    so you never hear two sounds for one push.
  - If a SquadTurf tab is open AND focused, most browsers mute the system
    notification's own sound (a browser/OS limitation, not a SquadTurf
    bug). default.wav plays instead, as a stand-in, so a push you're
    actively looking at still makes a sound.
  - A short cooldown also prevents the push relay and the home-page
    unread-badge check from both playing a sound for the same event.
  - Only the phone's vibration pattern can be customized for the fully
    closed/background case (system-level limitation of Web Push); this
    is set once in sw.js as a single generic pattern, matching the
    "same feel every time" approach above.
  - On iPhone, background push at all (even with the OS default tone)
    only works if SquadTurf was added to the Home Screen (Settings >
    Share > Add to Home Screen) and iOS is 16.4+.
