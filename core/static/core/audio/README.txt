SquadTurf notification sounds — how to swap in your own audio
================================================================

Each match event plays its own whistle file. To try a different sound
(including a real recorded referee whistle you send me, or any clip you
find yourself), just overwrite the matching file below — keep the exact
filename, drop your file in, refresh the page. No code changes needed.

  new_match.wav          -> a new match is posted nearby
  join_request.wav       -> someone asks to join your hosted match
  request_accepted.wav   -> your join request was accepted
  request_declined.wav   -> your join request was declined
  player_left.wav        -> a player dropped out of your match
  match_filled.wav       -> your match just got its last player
  match_cancelled.wav    -> a match you're in was cancelled
  reminder.wav           -> the 30-minutes-before-kickoff reminder
  default.wav            -> fallback for any other/unknown event
  whistle.wav            -> last-resort fallback if a file above is missing

Format tips:
  - .wav, .mp3, .ogg, or .m4a all work — just keep the same filename
    shown above (extension included). If you use a different extension,
    also update AUDIO_FILES in static/core/js/push.js to match.
  - Keep clips short: 0.2-1.5 seconds. Longer clips still play, but they
    can feel laggy stacked against other UI sounds.
  - Normalize loudness so no single event is jarringly louder than the
    rest (any free audio editor like Audacity can do this in one click).

Where these sounds actually play:
  - If a SquadTurf tab/PWA is open ANYWHERE on the device (foreground,
    or backgrounded — e.g. you're in Instagram but the tab is still
    alive), the matching file above plays for real, out loud.
  - If the site/app is fully closed or the tab was killed, the OS/browser
    shows the system push notification (status-bar banner, slides down
    like WhatsApp) using ITS OWN default notification tone. This is a
    hard platform limitation, not a bug: Web Push / the Notification API
    has never supported a custom sound file for that system-level alert
    on any browser (Chrome, Safari, Firefox all dropped/never shipped
    it). Only the phone's vibration pattern can be customized per event
    type in that fully-closed case, which is already wired up in sw.js.
  - On iPhone, background push at all (even with the OS default tone)
    only works if SquadTurf was added to the Home Screen (Settings >
    Share > Add to Home Screen) and iOS is 16.4+.

Note on "real FIFA whistle" audio: the files here are original synthesized
whistle sounds, not a sampled/licensed FIFA or broadcast recording — using
an actual FIFA-branded or broadcast whistle clip would be copyrighted
audio I can't reproduce. If you have your own royalty-free or personally
recorded whistle sounds, drop them in using the filenames above and
they'll be used automatically.
