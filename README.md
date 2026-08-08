# SquadTurf

Post a match. Fill your squad. Kick off in minutes.

SquadTurf is a Django app for organising pickup sports matches. Hosts post
an open request for players (**Urgent** — playing within the hour — or
**Scheduled** for today/tomorrow), players request to join, hosts accept
or decline, and everyone gets notified in-app *and* via Web Push —
even when SquadTurf isn't open in a tab.

## Features

**Core**
- Passwordless auth — sign up / log in with name + phone number, verified
  by a one-time code (OTP). No passwords to remember or leak.
- Turf-anchored matches with QR-friendly landing links (`/t/<slug>/`).
- Urgent vs Scheduled matches, Free vs Split cost sharing.
- Join requests, accept/decline, auto-fill, cancel/step-down, host cancel.
- Post-match star ratings + a "showed up" reliability signal.
- "My hosted" / "My joined" dashboards that keep **every** match forever
  (greyed out once it's over) so you can always look up a phone number.
- Django admin for turfs, profiles, matches, requests, ratings, and an
  OTP on/off switch for easy multi-account testing.

**This round of additions**
- **Time-left reallocation** — any match kicking off within 4 hours shows
  under "Starting soon" regardless of whether it was hosted as Urgent or
  Scheduled, so nothing imminent gets buried in a "later" list.
- **Player ratings surfaced at accept-time** — a requester's star average
  shows next to their name both in the host's incoming-requests list and
  in the home-page "Requests for your matches" notification, so a host
  has something to go on before accepting.
- **Simple post-match rating** — a clear "✅ Showed up / ❌ No-show" choice
  followed by a tap-to-select 5-star picker, replacing the old dropdown.
- **New matches broadcast to everyone** — the moment a match is posted,
  every user who has "Notify me about new matches" on (Profile page) gets
  an in-app + push notification. This is the main lever for filling a
  squad fast, so it fires immediately rather than waiting on a digest.
- **Exact kickoff time for urgent matches too** — instead of "in 15/30/60
  minutes," hosts now pick the actual clock time from the same half-hour
  picker used for scheduled matches, defaulting to the next available slot.
- OTP login/signup — see "Authentication" below. An admin can flip
  `Site settings → OTP required` off in `/admin/` to skip verification
  entirely while testing.
- Web Push notifications — join requests, acceptances, declines,
  cancellations, new-match broadcasts, and a pre-kickoff reminder are
  pushed to the browser/OS even if no SquadTurf tab is open. Free — no
  paid service required.
- **Home-page notifications persist for 2 hours after kickoff** (not just
  until it starts), so you don't lose track of a request mid-game.
- **Name always shown, phone number only after acceptance** — everywhere
  a player/host appears (home notifications, match page, dashboards).
- **Day-bubble filters** (All / Today / Tomorrow) plus a **turf filter**
  that only appears once two or more turfs currently need players.
- **Refined "host a match" form** — a simple half-hour time picker
  (12:00 AM, 12:30 AM, … in AM/PM) and a Today/Tomorrow day picker for
  scheduled matches, instead of a raw datetime input.
- **Smart dates** — dashboards show "Today"/"Tomorrow"/"Yesterday" for
  anything nearby, and only fall back to a full date once it's older
  than yesterday.
- **Nearest-first / latest-first ordering** — the feed leads with the
  soonest upcoming match; dashboards lead with your most recently
  created entry.
- **30-minute pre-kickoff reminder** to the host, with the confirmed
  headcount, via a small management command (cron-friendly, no Celery).
- **"Recently played" strip** on the feed so it never looks empty, plus
  Full/Over badges once a match fills up or its time passes.

## Getting started

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

python manage.py makemigrations
python manage.py migrate

python manage.py seed_turfs          # a few sample turfs
python manage.py createsuperuser     # for /admin/

python manage.py runserver
```

Visit `http://127.0.0.1:8000/`.

## Authentication — OTP, and how to test it for free

Signup/login ask for name + phone, then a 6-digit code. There's no paid
SMS budget assumed:

- By default, the code is **printed to the `runserver` console** (and, in
  `DEBUG` mode, shown directly on the verification page as a message —
  "Dev mode — your code is 123456") so you can test end-to-end without
  any SMS provider at all.
- To actually deliver SMS in production, open `core/otp.py` and replace
  the body of `_dispatch_otp()` with a call to whichever provider you
  pick — e.g. **Fast2SMS** or **MSG91** (both have an India-friendly free
  tier) or Twilio's trial credits. Nothing else in the app needs to
  change.
- **Admin bypass**: in `/admin/` under "Site settings", switch
  **OTP required** off. Signup/login then skip the code entirely — handy
  for quickly testing multiple accounts yourself.

## Web Push — free, and works without a tab open

1. Generate a VAPID key pair once:
   ```bash
   python manage.py generate_vapid_keys
   ```
2. Put the printed `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` /
   `VAPID_ADMIN_EMAIL` into your environment (a `.env` file, your host's
   env var settings, etc). Push is silently disabled everywhere until
   these are set — nothing else breaks.
3. Serve the site over **HTTPS** (or `localhost`, which browsers treat
   as secure) — the Push API refuses to work over plain HTTP on a real
   domain.
4. Logged-in users get a one-time "Enable notifications" banner (also
   available any time from their Profile page). Once granted, join
   requests, acceptances, declines, cancellations and the 30-minute
   reminder all arrive as real OS/browser notifications.

**Honest limitation:** Web Push needs the browser (or, on Windows/macOS,
the OS's background push relay) to be running and online — it can't wake
a device that's fully powered off, and on some mobile OSes aggressive
battery savers can delay delivery. It does **not** require a SquadTurf
tab to be open, which covers the "closed browser" case in the request.

## The 30-minute pre-match reminder

No Celery/Redis needed — just a cron entry:

```bash
*/5 * * * * cd /path/to/squadturf && /path/to/venv/bin/python manage.py send_match_reminders
```

It's idempotent (each match is only reminded once via `reminder_sent`),
so running it every few minutes is safe.

## Project layout

```
squadturf/
├── manage.py
├── requirements.txt
├── squadturf/                     # project settings, root urls, /sw.js route
└── core/
    ├── models.py                   # Turf, Profile, Match, JoinRequest, Rating,
    │                                # Notification, PushSubscription, SiteSettings, OTP
    ├── forms.py                     # Signup/Login/Otp/Match/ProfileEdit forms
    ├── views.py                     # all views, incl. OTP flow & push endpoints
    ├── otp.py                       # OTP generation/delivery/verification
    ├── notifications.py             # in-app notification + Web Push fan-out
    ├── context_processors.py        # unread notification badge count
    ├── urls.py / squadturf/urls.py
    ├── admin.py
    ├── management/commands/
    │   ├── seed_turfs.py
    │   ├── generate_vapid_keys.py
    │   └── send_match_reminders.py  # run on a cron schedule
    ├── templatetags/core_extras.py  # relative_day, day_bucket, stars_range
    ├── templates/core/              # feed, match detail, dashboards, auth, profile
    └── static/core/                 # custom.css (design system), app.js, push.js, sw.js
```

## Notes on the design

The visual language is a "matchday ticket": each match on the feed
renders as a stadium ticket stub, with a perforated tear-line separating
the match info from its status. Scoreboard-style monospace type
(JetBrains Mono) is used for times, counts, and phone numbers; headings
use Space Grotesk; body copy uses Inter. Colours are turf green +
floodlight amber rather than a generic SaaS palette.

## Extending it

- Swap `/admin/`-only turf management for a self-serve "add my ground" flow.
- Add real SMS delivery in `core/otp.py` when you're ready to go live.
- Add a lightweight geolocation filter so the feed only shows nearby turfs.
- Add a proper task queue (Celery/RQ) if the reminder volume outgrows cron.
