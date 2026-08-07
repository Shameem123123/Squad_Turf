# SquadTurf

Post a match. Fill your squad. Kick off in minutes.

SquadTurf is a Django app for organising pickup sports matches. Hosts post an
open request for players (either **urgent** — playing within the hour — or
**scheduled** for later), players request to join, hosts accept or decline,
and everyone rates each other afterwards.

This is a clean rebuild: same feature set as the original project, new
codebase, new professional UI (a "matchday ticket" design system built on
Tailwind CSS).

## Features

- **Passwordless auth** — sign up / log in with just a name and phone number.
- **Turf-anchored matches** — every match is tied to a turf; turfs can carry
  a QR-friendly slug (`/t/<slug>/`) that deep-links straight into the
  "host a match" form, pre-selecting that turf.
- **Two match types** — Urgent (auto-computed kickoff time, e.g. "in 15
  minutes") and Scheduled (host picks date & time).
- **Cost sharing** — Free (host-sponsored) or Split, with a per-head amount.
- **Join requests** — players request to join; hosts accept/decline from the
  feed or the match page; slot counts update automatically, and a match
  auto-marks itself Filled when it hits zero open spots.
- **Live notification banners** on the home feed — hosts see pending/accepted
  requests for their matches, players see when they've been accepted or
  declined.
- **Withdraw / step down** — players can cancel a pending request or leave an
  accepted spot (which reopens it).
- **Post-match ratings** — 1–5 stars plus a "showed up" flag, one rating per
  match per pair of users.
- **Dashboards** — "My hosted matches" and "My joined requests" views.
- **Django admin** — manage turfs, profiles, matches, requests, and ratings.

## Getting started

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

python manage.py makemigrations
python manage.py migrate

# optional: a few sample turfs so the "Host a match" form isn't empty
python manage.py seed_turfs

# optional: an admin account for /admin/
python manage.py createsuperuser

python manage.py runserver
```

Visit `http://127.0.0.1:8000/`.

## Project layout

```
squadturf/
├── manage.py
├── requirements.txt
├── squadturf/            # project settings, root urls
└── core/                 # the whole app
    ├── models.py          # Turf, Profile, Match, JoinRequest, Rating
    ├── forms.py           # SignupForm, LoginForm, MatchForm
    ├── views.py           # all views
    ├── urls.py
    ├── admin.py
    ├── management/commands/seed_turfs.py
    ├── templates/core/    # feed, match detail, dashboards, auth
    └── static/core/       # custom.css (design system), app.js
```

## Notes on the design

The visual language is a "matchday ticket": each match on the feed renders
as a stadium ticket stub, with a perforated tear-line separating the match
info from its status. Scoreboard-style monospace type (JetBrains Mono) is
used for times, counts, and phone numbers; headings use Space Grotesk; body
copy uses Inter. Colours are turf green + floodlight amber rather than a
generic SaaS palette, to keep it grounded in the actual subject — outdoor
pickup sport, played under lights, coordinated at short notice.

## Extending it

Ideas if you want to keep building:
- Swap `/admin/`-only turf management for a self-serve "add my ground" flow.
- Add real push notifications (the original project's `fcm_token` field is a
  good hook) instead of the in-app banner.
- Add a lightweight geolocation filter so the feed only shows nearby turfs.
- Add OTP verification on phone numbers before login is trusted in production.
