"""Turf slot-booking engine.

Everything that decides *what is bookable* lives here so the player pages,
the turf-admin console, the JSON availability API, the Django admin and the
tests all agree on one set of rules:

* ``build_grid``      – the day's slot grid for a turf (hours + slot length)
* ``slot_states``     – live state of each slot (free / booked / mine / ...)
* ``create_booking``  – atomic, race-safe booking (also used for walk-ins & blocks)
* ``cancel_booking``  – frees the slots again and tells the other side
* ``day_stats``       – the numbers on the turf-admin dashboard

Times are always handled as aware datetimes in the project time zone
(Asia/Kolkata). A slot's identity on the wire is its local ``HH:MM`` start.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from .models import Booking, BookingSlot, Notification, Turf, TurfManager
from .notifications import notify

MAX_ACTIVE_ONLINE_BOOKINGS = 6   # slot-hoarding guard: upcoming online bookings per player
CONSOLE_DAYS_BACK = 3            # how far back the turf admin can browse the schedule
SCAN_EARLY_MINUTES = 60          # tickets can be admitted from this long before the start
TICKET_PREFIX = 'SQT1'


class BookingError(Exception):
    """A problem the person can fix; the message is safe to show as-is."""


class SlotTakenError(BookingError):
    pass


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def local_today():
    return timezone.localdate()


def fmt_time(dt):
    return timezone.localtime(dt).strftime('%I:%M %p').lstrip('0')


def fmt_range(start, end):
    s, e = timezone.localtime(start), timezone.localtime(end)
    if s.strftime('%p') == e.strftime('%p'):
        return f"{s.strftime('%I:%M').lstrip('0')}–{fmt_time(e)}"
    return f"{fmt_time(s)}–{fmt_time(e)}"


def fmt_day(dt_or_date, long=False):
    d = timezone.localtime(dt_or_date).date() if isinstance(dt_or_date, datetime) else dt_or_date
    delta = (d - local_today()).days
    if delta == 0:
        return 'Today'
    if delta == 1:
        return 'Tomorrow'
    if long:
        return f"{d:%A}, {d.day} {d:%b}"
    return f"{d:%a}, {d.day} {d:%b}"


def human_when(start, end):
    return f"{fmt_day(start)}, {fmt_range(start, end)}"


def group_of(dt):
    hour = timezone.localtime(dt).hour
    if hour < 12:
        return 'morning'
    if hour < 16:
        return 'afternoon'
    if hour < 20:
        return 'evening'
    return 'night'


def num(value):
    """Decimal -> int when whole (₹1200), else float (₹1200.5) — JSON friendly."""
    value = Decimal(value)
    return int(value) if value == value.to_integral_value() else float(value)


# ---------------------------------------------------------------------------
# Who may manage what
# ---------------------------------------------------------------------------

def managed_turfs(user):
    """Turfs this account runs. Cached on the user object for the request, so the
    navigation, the views and the templates share one query."""
    if not user.is_authenticated:
        return []
    cached = getattr(user, '_managed_turfs', None)
    if cached is None:
        cached = [
            link.turf for link in TurfManager.objects.filter(user=user).select_related('turf')
            if link.turf.is_active
        ]
        user._managed_turfs = cached
    return cached


def can_manage(user, turf):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return TurfManager.objects.filter(user=user, turf=turf).exists()


def is_turf_admin(user):
    return bool(managed_turfs(user))


# ---------------------------------------------------------------------------
# The slot grid
# ---------------------------------------------------------------------------

def day_bounds(turf, day):
    tz = timezone.get_current_timezone()
    open_dt = timezone.make_aware(datetime.combine(day, turf.opens_at), tz)
    if turf.closes_at == time(0, 0) or turf.closes_at <= turf.opens_at:
        close_dt = timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min), tz)
    else:
        close_dt = timezone.make_aware(datetime.combine(day, turf.closes_at), tz)
    return open_dt, close_dt


def build_grid(turf, day):
    """[(start, end), ...] for every slot of `day`, in order."""
    open_dt, close_dt = day_bounds(turf, day)
    step = timedelta(minutes=turf.slot_minutes)
    grid, start = [], open_dt
    while start + step <= close_dt:
        grid.append((start, start + step))
        start += step
    return grid


def bookable_dates(turf, admin=False):
    today = local_today()
    first = today - timedelta(days=CONSOLE_DAYS_BACK) if admin else today
    last = today + timedelta(days=turf.advance_days)
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def parse_day(value, default=None):
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return default


def default_day(turf):
    """Today if anything is still bookable today, otherwise tomorrow."""
    today = local_today()
    now = timezone.now()
    if any(s > now for s, _ in build_grid(turf, today)):
        return today
    return today + timedelta(days=1)


def _active_bookings(turf, start, end):
    return list(
        Booking.objects.filter(
            turf=turf, status=Booking.Status.CONFIRMED, start_at__lt=end, end_at__gt=start
        ).select_related('user', 'user__profile')
    )


def _overlapping(bookings, s, e):
    for b in bookings:
        if b.start_at < e and b.end_at > s:
            return b
    return None


def _booking_payload(b):
    return {
        'ref': b.reference,
        'name': b.customer_name,
        'phone': b.customer_phone,
        'source': b.source,
        'paid': b.payment_status == Booking.Payment.PAID,
        'amount': num(b.amount),
        'slots': b.slot_count,
        'start': timezone.localtime(b.start_at).strftime('%H:%M'),
        'range': fmt_range(b.start_at, b.end_at),
        'note': b.note,
        'scanned': b.is_scanned,
    }


def slot_states(turf, day, user=None, admin=False):
    """Live state of every slot on `day`.

    Player view  -> free / booked / mine / blocked / past
    Admin view   -> free / booked / walkin / blocked / past  (+ booking details)
    A slot is "past" for players once it has *started*; the turf admin can
    still act on a slot until it has *ended* (a walk-in may turn up mid-slot).
    """
    now = timezone.now()
    grid = build_grid(turf, day)
    if not grid:
        return []
    bookings = _active_bookings(turf, grid[0][0], grid[-1][1])
    out = []
    for s, e in grid:
        b = _overlapping(bookings, s, e)
        mine = bool(b and user is not None and user.is_authenticated
                    and b.user_id == user.id and b.source == Booking.Source.ONLINE)
        if admin:
            if b:
                state = 'blocked' if b.is_blocked else ('walkin' if b.source == Booking.Source.WALKIN else 'booked')
            else:
                state = 'past' if e <= now else 'free'
        else:
            if mine:
                state = 'mine'
            elif s <= now:
                state = 'past'
            elif b:
                state = 'blocked' if b.is_blocked else 'booked'
            else:
                state = 'free'
        item = {
            'start': timezone.localtime(s).strftime('%H:%M'),
            'end': timezone.localtime(e).strftime('%H:%M'),
            'label': fmt_time(s),
            'end_label': fmt_time(e),
            'price': num(turf.price_for(s)),
            'state': state,
            'group': group_of(s),
        }
        if b and (admin or mine):
            item['booking'] = _booking_payload(b)
        out.append(item)
    return out


def day_summaries(turf, days, admin=False):
    """Per-day {free, total} so the date strip can hint "filling up" / "full"."""
    if not days:
        return []
    now = timezone.now()
    grids = {d: build_grid(turf, d) for d in days}
    spans = [g for g in grids.values() if g]
    bookings = _active_bookings(turf, spans[0][0][0], spans[-1][-1][1]) if spans else []
    out = []
    for d in days:
        free = total = 0
        for s, e in grids[d]:
            if (e if admin else s) <= now:
                continue
            b = _overlapping(bookings, s, e)
            if b and b.is_blocked:
                continue          # a closed slot isn't "capacity"
            total += 1
            if not b:
                free += 1
        out.append({'date': d.isoformat(), 'free': free, 'total': total})
    return out


def availability_payload(turf, day, user=None, admin=False):
    days = bookable_dates(turf, admin=admin)
    payload = {
        'turf': turf.slug,
        'date': day.isoformat(),
        'can_book': turf.accepts_bookings,
        'paused': turf.bookings_paused,
        'slots': slot_states(turf, day, user=user, admin=admin),
        'days': day_summaries(turf, days, admin=admin),
        'server_time': timezone.localtime().strftime('%I:%M:%S %p').lstrip('0'),
    }
    if admin:
        payload['stats'] = day_stats(turf, day)
    return payload


def free_slots_today(turf, now=None):
    now = now or timezone.now()
    grid = [(s, e) for s, e in build_grid(turf, local_today()) if s > now]
    if not grid:
        return 0
    bookings = _active_bookings(turf, grid[0][0], grid[-1][1])
    return sum(1 for s, e in grid if not _overlapping(bookings, s, e))


def free_slots_today_many(turfs, now=None):
    """{turf.pk: free slots left today} for many turfs with a single query."""
    now = now or timezone.now()
    today = local_today()
    grids = {t.pk: [(s, e) for s, e in build_grid(t, today) if s > now] for t in turfs}
    spans = [g for g in grids.values() if g]
    if not spans:
        return {t.pk: 0 for t in turfs}
    low, high = min(g[0][0] for g in spans), max(g[-1][1] for g in spans)
    by_turf = defaultdict(list)
    for b in Booking.objects.filter(
        turf__in=list(turfs), status=Booking.Status.CONFIRMED, start_at__lt=high, end_at__gt=low
    ):
        by_turf[b.turf_id].append(b)
    return {
        pk: sum(1 for s, e in grid if not _overlapping(by_turf[pk], s, e))
        for pk, grid in grids.items()
    }


def is_open_now(turf):
    now = timezone.now()
    open_dt, close_dt = day_bounds(turf, local_today())
    return open_dt <= now < close_dt


# ---------------------------------------------------------------------------
# Creating / cancelling
# ---------------------------------------------------------------------------

@transaction.atomic
def create_booking(turf, day, start_hhmm, count=1, *, user=None, source=Booking.Source.ONLINE,
                   guest_name='', guest_phone='', note='', paid=False):
    """Book `count` consecutive slots starting at local `start_hhmm` on `day`.

    The turf row is locked for the duration so concurrent requests queue up
    (Postgres), and the unique BookingSlot rows are a hard backstop (any DB).
    Raises BookingError / SlotTakenError with a human-friendly message.
    """
    turf = Turf.objects.select_for_update().get(pk=turf.pk)
    online = source == Booking.Source.ONLINE

    if online and not turf.accepts_bookings:
        raise BookingError("This turf isn't taking online bookings right now.")
    if not turf.is_active:
        raise BookingError("This turf isn't available.")

    today, now = local_today(), timezone.now()
    if day < today:
        raise BookingError("That date has already passed.")
    if online and day > today + timedelta(days=turf.advance_days):
        raise BookingError(f"You can book up to {turf.advance_days} days ahead.")

    try:
        count = int(count)
    except (TypeError, ValueError):
        raise BookingError("Pick at least one slot.")
    if online and not 1 <= count <= turf.max_slots_per_booking:
        raise BookingError(f"You can book 1–{turf.max_slots_per_booking} slots at a time.")
    if count < 1:
        raise BookingError("Pick at least one slot.")

    grid = build_grid(turf, day)
    idx = next((i for i, (s, _) in enumerate(grid)
                if timezone.localtime(s).strftime('%H:%M') == start_hhmm), None)
    if idx is None:
        raise BookingError("That slot doesn't exist.")
    chosen = grid[idx:idx + count]
    if len(chosen) != count:
        raise BookingError("That booking would run past closing time.")
    for s, e in chosen:
        if (online and s <= now) or e <= now:
            raise BookingError("That time has already started — pick a later slot.")

    start_at, end_at = chosen[0][0], chosen[-1][1]
    if Booking.objects.filter(
        turf=turf, status=Booking.Status.CONFIRMED, start_at__lt=end_at, end_at__gt=start_at
    ).exists():
        raise SlotTakenError("Sorry — someone just took that slot. Pick another.")

    if online and user is not None:
        active = Booking.objects.filter(
            user=user, source=Booking.Source.ONLINE, status=Booking.Status.CONFIRMED, end_at__gt=now
        ).count()
        if active >= MAX_ACTIVE_ONLINE_BOOKINGS:
            raise BookingError(
                f"You already have {MAX_ACTIVE_ONLINE_BOOKINGS} upcoming bookings. "
                "Play a few (or cancel one) before booking more."
            )

    blocked = source == Booking.Source.BLOCKED
    amount = Decimal(0) if blocked else sum((turf.price_for(s) for s, _ in chosen), Decimal(0))
    booking = Booking.objects.create(
        turf=turf, user=user if online else None,
        guest_name=guest_name.strip()[:120], guest_phone=guest_phone.strip()[:15],
        source=source, start_at=start_at, end_at=end_at, slot_count=count,
        amount=amount, note=note.strip()[:255],
        payment_status=Booking.Payment.PAID if (paid and not blocked) else Booking.Payment.PENDING,
    )
    try:
        with transaction.atomic():
            BookingSlot.objects.bulk_create(
                [BookingSlot(booking=booking, turf=turf, start_at=s) for s, _ in chosen]
            )
    except IntegrityError:
        raise SlotTakenError("Sorry — someone just took that slot. Pick another.")
    return booking


@transaction.atomic
def cancel_booking(booking, by, reason=''):
    """Cancel a confirmed booking and free its slots. `by` is 'PLAYER' or 'TURF'."""
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    if booking.status != Booking.Status.CONFIRMED:
        return booking
    booking.status = Booking.Status.CANCELLED
    booking.cancelled_by = by
    booking.cancel_reason = (reason or '').strip()[:255]
    booking.cancelled_at = timezone.now()
    booking.save(update_fields=['status', 'cancelled_by', 'cancel_reason', 'cancelled_at'])
    booking.slots.all().delete()
    return booking


def block_slots(turf, day, starts, reason=''):
    """Block each slot in `starts` (list of HH:MM). Returns (blocked, skipped)."""
    blocked = skipped = 0
    for start in starts:
        try:
            create_booking(turf, day, start, 1, source=Booking.Source.BLOCKED,
                           guest_name=reason or 'Closed')
            blocked += 1
        except BookingError:
            skipped += 1
    return blocked, skipped


def close_day(turf, day, reason='Closed for the day'):
    """Block every slot of `day` that is still free (and hasn't ended)."""
    free = [s['start'] for s in slot_states(turf, day, admin=True) if s['state'] == 'free']
    return block_slots(turf, day, free, reason)


def reopen_day(turf, day):
    open_dt, close_dt = day_bounds(turf, day)
    qs = Booking.objects.filter(
        turf=turf, source=Booking.Source.BLOCKED, status=Booking.Status.CONFIRMED,
        start_at__gte=open_dt, start_at__lt=close_dt,
    )
    count = qs.count()
    qs.delete()           # BookingSlot rows cascade -> slots free up
    return count


# ---------------------------------------------------------------------------
# Dashboard numbers
# ---------------------------------------------------------------------------

def day_stats(turf, day):
    grid = build_grid(turf, day)
    if not grid:
        return {'bookings': 0, 'booked_slots': 0, 'capacity': 0, 'occupancy': 0,
                'revenue': 0, 'to_collect': 0, 'blocked_slots': 0}
    qs = Booking.objects.filter(
        turf=turf, status=Booking.Status.CONFIRMED,
        start_at__gte=grid[0][0], start_at__lt=grid[-1][1],
    )
    real = [b for b in qs if not b.is_blocked]
    booked_slots = sum(b.slot_count for b in real)
    blocked_slots = sum(b.slot_count for b in qs if b.is_blocked)
    capacity = max(len(grid) - blocked_slots, 0)
    revenue = sum((b.amount for b in real), Decimal(0))
    to_collect = sum((b.amount for b in real if b.payment_status == Booking.Payment.PENDING), Decimal(0))
    return {
        'bookings': len(real),
        'booked_slots': booked_slots,
        'capacity': capacity,
        'blocked_slots': blocked_slots,
        'occupancy': round(booked_slots / capacity * 100) if capacity else 0,
        'revenue': num(revenue),
        'to_collect': num(to_collect),
    }


def next_up(turf):
    return Booking.objects.filter(
        turf=turf, status=Booking.Status.CONFIRMED, end_at__gt=timezone.now()
    ).exclude(source=Booking.Source.BLOCKED).select_related('user', 'user__profile').order_by('start_at').first()


# ---------------------------------------------------------------------------
# Notifications (kept here so views, admin actions and cron share one wording)
# ---------------------------------------------------------------------------

def _inr(value):
    value = Decimal(value)
    return f"₹{int(value):,}" if value == value.to_integral_value() else f"₹{value:,.2f}"


def _manager_users(turf):
    return [link.user for link in TurfManager.objects.filter(turf=turf).select_related('user')]


def _console_url(turf, booking=None):
    url = reverse('manage_schedule', args=[turf.slug])
    if booking:
        url += f"?date={timezone.localtime(booking.start_at).date().isoformat()}"
    return url


def notify_booking_created(booking):
    when = human_when(booking.start_at, booking.end_at)
    notify(
        booking.user, Notification.Verb.BOOKING_CONFIRMED,
        f"Booked: {booking.turf.name} · {when}.",
        booking=booking, url=reverse('booking_detail', args=[booking.reference]),
    )
    for manager in _manager_users(booking.turf):
        notify(
            manager, Notification.Verb.NEW_BOOKING,
            f"New booking: {booking.customer_name} · {when} · {_inr(booking.amount)}.",
            booking=booking, url=_console_url(booking.turf, booking),
        )


def notify_booking_cancelled(booking, by, reason=''):
    when = human_when(booking.start_at, booking.end_at)
    if by == Booking.CancelledBy.TURF:
        if booking.user_id:
            extra = f" Reason: {reason}." if reason else ""
            notify(
                booking.user, Notification.Verb.BOOKING_CANCELLED,
                f"{booking.turf.name} cancelled your booking for {when}.{extra}",
                booking=booking, url=reverse('booking_detail', args=[booking.reference]),
            )
    else:
        for manager in _manager_users(booking.turf):
            notify(
                manager, Notification.Verb.BOOKING_CANCELLED,
                f"{booking.customer_name} cancelled {when}. The slot is open again.",
                booking=booking, url=_console_url(booking.turf, booking),
            )


# ---------------------------------------------------------------------------
# Tickets: signed QR payload + gate scanning
# ---------------------------------------------------------------------------

def _ticket_sig(reference):
    return salted_hmac('squadturf.ticket', reference).hexdigest()[:10]


def ticket_token(booking):
    """What the QR code on a ticket holds. The signature means a code can't be
    forged from a guessed reference."""
    return f"{TICKET_PREFIX}.{booking.reference}.{_ticket_sig(booking.reference)}"


def parse_ticket_token(raw):
    """Booking reference from a scanned QR payload, or None if it isn't ours / is forged."""
    parts = (raw or '').strip().split('.')
    if len(parts) != 3 or parts[0] != TICKET_PREFIX:
        return None
    ref = parts[1].upper()
    return ref if constant_time_compare(parts[2].lower(), _ticket_sig(ref)) else None


def find_ticket(turf, raw, manual=False):
    """Resolve a scanned payload (or, for manual entry, a typed reference) to a
    booking at `turf`. Returns (booking | None, state) — state is 'ok' or an error."""
    if manual:
        ref = (raw or '').strip().upper().replace(' ', '')
        if ref.startswith(TICKET_PREFIX + '.'):      # the whole code was pasted
            ref = ref.split('.')[1]
    else:
        ref = parse_ticket_token(raw)
    if not ref:
        return None, 'invalid'
    booking = (
        Booking.objects.filter(reference=ref)
        .select_related('turf', 'user', 'user__profile').first()
    )
    if booking is None or booking.is_blocked:
        return None, 'invalid'
    if booking.turf_id != turf.pk:
        return booking, 'wrong_turf'
    return booking, 'ok'


def scan_state(booking, now=None):
    """Can this ticket be admitted right now? One of: ok, used, cancelled, ended, early."""
    now = now or timezone.now()
    if booking.is_cancelled:
        return 'cancelled'
    if booking.is_scanned:
        return 'used'
    if booking.end_at <= now:
        return 'ended'
    if booking.start_at - timedelta(minutes=SCAN_EARLY_MINUTES) > now:
        return 'early'
    return 'ok'


SCAN_MESSAGES = {
    'ok': "Valid ticket",
    'used': "Already scanned",
    'cancelled': "Booking was cancelled",
    'ended': "This slot has ended",
    'early': "Too early",
    'wrong_turf': "Ticket is for another turf",
    'invalid': "Not a valid ticket",
}


def scan_payload(booking, state, now=None):
    """JSON the scanner screen renders for a looked-up ticket."""
    out = {'state': state, 'message': SCAN_MESSAGES[state], 'admit': state == 'ok'}
    if booking is None or state == 'wrong_turf':
        return out
    out['booking'] = {
        'ref': booking.reference,
        'name': booking.customer_name,
        'phone': booking.customer_phone,
        'day': fmt_day(booking.start_at),
        'range': fmt_range(booking.start_at, booking.end_at),
        'slots': booking.slot_count,
        'amount': num(booking.amount),
        'paid': booking.payment_status == Booking.Payment.PAID,
    }
    if state == 'used':
        out['message'] = f"Already scanned at {fmt_time(booking.scanned_at)}"
    elif state == 'early':
        out['message'] = f"Too early · starts {fmt_time(booking.start_at)}"
    return out


def admit_booking(booking, collect_payment=False):
    """Mark a ticket as scanned. Atomic: two phones scanning the same ticket at once
    can't both succeed. Returns True if this call admitted it."""
    now = timezone.now()
    changed = Booking.objects.filter(
        pk=booking.pk, status=Booking.Status.CONFIRMED, scanned_at__isnull=True
    ).update(scanned_at=now)
    if changed and collect_payment:
        Booking.objects.filter(pk=booking.pk).update(payment_status=Booking.Payment.PAID)
    return bool(changed)


# ---------------------------------------------------------------------------
# Calendar export
# ---------------------------------------------------------------------------

def _ics_escape(text):
    return (text or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')


def build_ics(booking):
    utc = dt_timezone.utc
    stamp = timezone.now().astimezone(utc).strftime('%Y%m%dT%H%M%SZ')
    start = booking.start_at.astimezone(utc).strftime('%Y%m%dT%H%M%SZ')
    end = booking.end_at.astimezone(utc).strftime('%Y%m%dT%H%M%SZ')
    turf = booking.turf
    lines = [
        'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//SquadTurf//Booking//EN', 'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH', 'BEGIN:VEVENT',
        f'UID:{booking.reference}@squadturf', f'DTSTAMP:{stamp}', f'DTSTART:{start}', f'DTEND:{end}',
        f'SUMMARY:{_ics_escape("Turf: " + turf.name)}',
        f'LOCATION:{_ics_escape(turf.address or turf.location_name)}',
        f'DESCRIPTION:{_ics_escape("Booking ref " + booking.reference + ". Pay at the turf: " + _inr(booking.amount))}',
        'BEGIN:VALARM', 'TRIGGER:-PT60M', 'ACTION:DISPLAY', 'DESCRIPTION:Turf booking in 1 hour', 'END:VALARM',
        'END:VEVENT', 'END:VCALENDAR',
    ]
    return '\r\n'.join(lines) + '\r\n'
