# SquadTurf

Post a match. Fill your squad. Kick off in minutes.

SquadTurf is a Django app with two jobs:

1. **Book a turf** (primary) — browse turfs, pick a slot, get a ticket with a
   QR code. Turf managers scan it at the gate.
2. **Find players** (secondary) — host a game or request to join one. Hosts
   post an **Urgent** (within ~2.5 h) or **Scheduled** (today/tomorrow) game,
   players request to join, hosts accept or decline.

Everyone is notified in-app *and* via Web Push, even when SquadTurf isn't open
in a tab.

## App map

| Who | Tabs | Notes |
|---|---|---|
| Player | **Home** · **Book** · **Players** · **Profile** | Home has two buttons: *Book a turf* and *Find players*. **My bookings** lives inside the Book tab. Hosted / Joined games live inside the Players tab. |
| Turf manager | **Schedule** · **Bookings** · **Scan** · **Settings** | No play ratings, attendance stats or match features. They never get match alerts. |

**Design:** one stylesheet (`core/static/core/css/app.css`), system fonts, no CDN
and no build step. Turf green is the brand colour and marks everything about
booking; indigo marks finding players; amber and red are only for status
(due, cancelled). Each turf cover gets its own hue. Loading feedback is a thin
top progress bar, button spinners and skeleton placeholders.

**Tickets and scanning:** a ticket's QR holds `SQT1.<reference>.<signature>`,
signed with `SECRET_KEY`, so a code can't be forged from a guessed reference.
The manager's **Scan** tab reads it with the phone camera (needs HTTPS, and a
browser with `BarcodeDetector` such as Chrome on Android) and also accepts a
typed reference in any browser. Only the first scan admits a ticket; the
manager can also tick off cash payment at the gate. The QR encoder is a small
dependency-free module (`core/qr.py`).

**Notifications:** kept for 7 days, then deleted (opportunistically about once
an hour; `python manage.py purge_notifications` is an optional cron). Push is
sent from a small thread pool so a request never waits on it
(`PUSH_ASYNC=False` to send inline) and is retried by the push service for an
hour if a phone is asleep.

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
    ├── qr.py                        # dependency-free QR encoder (SVG)
    ├── booking_logic.py / booking_views.py   # slots, tickets, scanning, console
    ├── templatetags/                # core_extras, booking_tags
    ├── templates/core/              # home, players, match, auth, profile, booking/
    └── static/core/                 # css/app.css (the design system)
                                     # js/app.js (progress, spinners, push prompt)
                                     # js/booking.js, scanner.js, live.js, push.js, sw.js
```

## Notes on the design

Apple-style restraint with a clear colour identity: translucent top and tab
bars, large rounded cards, spring-like transitions that respect *reduce
motion*. Colours live as tokens at the top of `app.css` (`--brand`,
`--players`, `--deep`), so re-theming is a one-place change.

## Settings worth knowing

| Env var | Purpose |
|---|---|
| `DJANGO_DEBUG` | `False` in production (also turns on secure cookies + HSTS) |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hosts, e.g. `squadturf.onrender.com` (default `*`) |
| `PUSH_ASYNC` | `True` (default) sends push from a thread pool |

## Extending it

- Swap `/admin/`-only turf management for a self-serve "add my ground" flow.
- Add real SMS delivery in `core/otp.py` when you're ready to go live.
- Add a lightweight geolocation filter so the feed only shows nearby turfs.
- Add a proper task queue (Celery/RQ) if the reminder volume outgrows cron.

---

## Update notes (this revision)

**Auth** — Signup now collects name + phone + password, still OTP-verified.
Login is phone + password (no OTP), so day-to-day sign-in no longer costs an
SMS. Existing accounts from before this change have no password set — have
those users use "Forgot password" via `/admin/` (reset from the Django
admin) once, or re-signup.

**OTP delivery** — wire a real provider via env vars so codes actually
arrive on a phone:
```
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_NUMBER=+1XXXXXXXXXX        # for SMS
# or
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886   # for WhatsApp-based OTP
```
With none of these set, codes still just log to the console (dev mode), which
is why "OTP not received" happens on an unconfigured deployment.

**Persistent storage (users vanishing)** — SQLite is a single file on local
disk; most free hosts wipe it on redeploy. Set `DATABASE_URL` to a persistent
Postgres instance (Render/Railway/Supabase/Neon all offer a free tier) and
the app switches automatically — no other code changes needed. Without it,
you're back to ephemeral SQLite.

**Push notifications** — a working default VAPID key pair now ships so
"Enable" works out of the box; generate your own for a real deployment with
`python manage.py generate_vapid_keys`. For notifications to arrive even
when the browser is fully closed on mobile, the site should be "Added to
Home Screen" (a `manifest.webmanifest` is now served for this). This is the
practical ceiling for background push from a website — a native app store
app is the only way to fully match WhatsApp/Instagram-style delivery.

**Live updates** — `/api/live/` is polled every ~8s client-side; the feed,
notification badge and request lists refresh in place without a manual
reload or a websocket server.

**Match timing** — "Starting soon" window tightened from 4h to 2h. Urgent
matches can only be booked up to 2.5h out; a "Scheduled" match landing
inside that window is automatically posted as Urgent instead.

**Header** — condensed to Home / Hosted / Requested / bell / profile circle
(initials only — logout lives inside that dropdown) + a "≡" overflow menu
for Turfs, to stop the header overflowing on mobile.


---

## 🏟️ Turf slot booking (BookMyShow-style)

Players can book real time slots at turfs; turf owners get their own console. It is purely additive — matches, join requests, ratings and notifications work exactly as before.

### How it goes live (all manual, by you)
1. **Add the turf** in `/admin/` → *Turfs*. Fill in *Listing details*, *Booking setup* (hours, slot length, limits) and *Pricing*.
2. **Create the turf admin account** → *Turf admin accounts → Add* (or the button on the turf's page). Enter the turf, the contact's name, a **login phone number** and a password; share these with the turf yourself. There is no self-signup for this role, and a number that already belongs to a player can't be reused.
3. **Tick "Booking enabled"** on the turf. Only now does it appear under **Book** for players.

> Fast try-out: `python manage.py migrate && python manage.py seed_booking_demo --manager` enables booking on the sample turfs and prints a demo turf-admin login. Delete that account before going live.

### Two account types
| | Player | Turf admin |
|---|---|---|
| Created by | Sign-up | You, in `/admin/` |
| Lands on | Home | `/manage/` console |
| Can | Browse, book, cancel (within window), host/join matches | See live schedule, add walk-ins, block slots / close a day, cancel bookings, mark paid, edit price & details, pause bookings |

### Player flow
`/book/` → pick a turf → pick a date → tap slots (tap the next slot to extend, up to the turf's limit) → confirm → ticket with QR code, calendar file, directions, share, and "find players for this game" (hands off to the host-a-game flow). Availability is **live**: the grid refreshes every few seconds (cheap conditional requests that answer `304` when nothing changed), and a slot someone else just took is released from your selection with a heads-up. Payment is **pay at the turf** for now; the turf admin marks bookings paid.

### Rules enforced by the server
* A slot can never be double-booked — checked in a locked transaction **and** by a database unique constraint.
* Slots only within opening hours, inside the advance window, and not already started.
* Free cancellation until *N* hours before the start (per turf); after that the player is pointed to call the turf.
* Max 6 upcoming online bookings per player (anti-hoarding).
* Opening hours / slot length can't be changed while upcoming bookings exist.

### Reminders (optional, same pattern as match reminders)
```
*/5 * * * * cd /path/to/squadturf && python manage.py send_booking_reminders
```

### Tests
`python manage.py test core`

Covers bookings, QR ticket signing, the scanner (valid / early / used /
cancelled / wrong turf / forged), notification expiry, and the new flow.
