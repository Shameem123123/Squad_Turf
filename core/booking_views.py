"""Views for turf slot booking: the player flow (browse -> pick -> ticket) and
the turf-admin console (schedule, walk-ins, blocks, bookings, settings)."""
import hashlib
import json
from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from . import booking_logic as bl
from . import qr
from .booking_forms import TurfSettingsForm
from .models import Booking, Turf


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _bookable_turf_or_404(slug):
    return get_object_or_404(Turf, slug=slug, is_active=True, booking_enabled=True)


def _date_cards(days, today):
    return [{
        'date': d.isoformat(), 'dow': 'Today' if d == today else f"{d:%a}",
        'dom': d.day, 'mon': f"{d:%b}",
    } for d in days]


def _player_cfg(request, turf, day):
    today = bl.local_today()
    next_url = f"{reverse('book_turf', args=[turf.slug])}?date={day.isoformat()}"
    return {
        'mode': 'player',
        'apiUrl': reverse('book_slots_api', args=[turf.slug]),
        'confirmUrl': reverse('book_confirm', args=[turf.slug]),
        'date': day.isoformat(),
        'dates': _date_cards(bl.bookable_dates(turf), today),
        'maxSlots': turf.max_slots_per_booking,
        'loggedIn': request.user.is_authenticated,
        'isTurfAdmin': bl.is_turf_admin(request.user),
        'loginUrl': f"{reverse('login')}?next={next_url}",
        'signupUrl': reverse('signup'),
        'cancelHours': turf.cancel_before_hours,
        'payload': bl.availability_payload(turf, day, user=request.user),
    }


def _console_cfg(turf, day):
    today = bl.local_today()
    return {
        'mode': 'admin',
        'apiUrl': reverse('manage_slots_api', args=[turf.slug]),
        'date': day.isoformat(),
        'dates': _date_cards(bl.bookable_dates(turf, admin=True), today),
        'maxSlots': turf.max_slots_per_booking,
        'actions': {
            'walkin': reverse('manage_walkin', args=[turf.slug]),
            'block': reverse('manage_block', args=[turf.slug]),
            'unblock': reverse('manage_unblock', args=[turf.slug]),
            'closeDay': reverse('manage_close_day', args=[turf.slug]),
            'reopenDay': reverse('manage_reopen_day', args=[turf.slug]),
            'cancel': reverse('manage_booking_cancel', args=[turf.slug, 'REF']),
            'paid': reverse('manage_booking_paid', args=[turf.slug, 'REF']),
        },
        'payload': bl.availability_payload(turf, day, admin=True),
    }


def console_view(view):
    """Login + must manage this turf (superusers may peek at any turf)."""
    @wraps(view)
    @login_required
    def wrapper(request, slug, *args, **kwargs):
        turf = get_object_or_404(Turf, slug=slug, is_active=True)
        if not bl.can_manage(request.user, turf):
            raise PermissionDenied
        return view(request, turf, *args, **kwargs)
    return wrapper


def _json_with_etag(request, payload):
    """JSON that browsers revalidate cheaply: an unchanged day answers 304 with no body.
    `server_time` is left out of the hash because it changes every second."""
    stable = {k: v for k, v in payload.items() if k != 'server_time'}
    digest = hashlib.md5(
        json.dumps(stable, sort_keys=True, separators=(',', ':')).encode(), usedforsecurity=False
    ).hexdigest()[:20]
    etag = f'"{digest}"'
    if request.headers.get('If-None-Match') == etag:
        resp = HttpResponse(status=304)
    else:
        resp = JsonResponse(payload)
    resp['ETag'] = etag
    resp['Cache-Control'] = 'no-cache'
    return resp


def _back_to_schedule(turf, day):
    return redirect(f"{reverse('manage_schedule', args=[turf.slug])}?date={day.isoformat()}")


# ---------------------------------------------------------------------------
# players
# ---------------------------------------------------------------------------

def book_directory(request):
    q = (request.GET.get('q') or '').strip()
    sport = (request.GET.get('sport') or '').strip()
    turfs = Turf.objects.filter(is_active=True, booking_enabled=True)
    all_sports = sorted({s for t in turfs for s in t.sport_list})
    if q:
        turfs = turfs.filter(Q(name__icontains=q) | Q(location_name__icontains=q) | Q(address__icontains=q))
    shown = [
        t for t in turfs
        if not sport or sport.lower() in [x.lower() for x in t.sport_list]
    ]
    free = bl.free_slots_today_many(shown)
    cards = [
        {'turf': t, 'free_today': free.get(t.pk, 0), 'open_now': bl.is_open_now(t)}
        for t in shown
    ]
    return render(request, 'core/booking/directory.html', {
        'cards': cards, 'q': q, 'sport': sport, 'all_sports': all_sports,
        'section': 'turfs', 'upcoming_count': _upcoming_count(request.user),
    })


def _upcoming_count(user):
    if not user.is_authenticated:
        return 0
    return Booking.objects.filter(
        user=user, source=Booking.Source.ONLINE,
        status=Booking.Status.CONFIRMED, end_at__gt=timezone.now(),
    ).count()


def book_turf(request, slug):
    turf = _bookable_turf_or_404(slug)
    today = bl.local_today()
    day = bl.parse_day(request.GET.get('date'), None)
    if day is None or not (today <= day <= today + timedelta(days=turf.advance_days)):
        day = bl.default_day(turf)
    return render(request, 'core/booking/turf.html', {
        'turf': turf, 'cfg': _player_cfg(request, turf, day), 'open_now': bl.is_open_now(turf),
    })


def book_slots_api(request, slug):
    turf = _bookable_turf_or_404(slug)
    today = bl.local_today()
    day = bl.parse_day(request.GET.get('date'))
    if day is None or not (today <= day <= today + timedelta(days=turf.advance_days)):
        return JsonResponse({'error': 'bad date'}, status=400)
    return _json_with_etag(request, bl.availability_payload(turf, day, user=request.user))


@login_required
@require_POST
def book_confirm(request, slug):
    turf = _bookable_turf_or_404(slug)
    day = bl.parse_day(request.POST.get('date'), bl.local_today())
    back = f"{reverse('book_turf', args=[turf.slug])}?date={day.isoformat()}"
    if bl.is_turf_admin(request.user):
        messages.error(request, "Turf accounts manage turfs. Use a player account to book.")
        return redirect(back)
    try:
        booking = bl.create_booking(
            turf, day, request.POST.get('start', ''), request.POST.get('count', 1),
            user=request.user, note=request.POST.get('note', ''),
        )
    except bl.BookingError as exc:
        messages.error(request, str(exc))
        return redirect(back)
    bl.notify_booking_created(booking)
    return redirect(f"{reverse('booking_detail', args=[booking.reference])}?new=1")


@login_required
def my_bookings(request):
    tab = 'past' if request.GET.get('tab') == 'past' else 'upcoming'
    mine = Booking.objects.filter(user=request.user, source=Booking.Source.ONLINE).select_related('turf')
    now = timezone.now()
    upcoming = mine.filter(status=Booking.Status.CONFIRMED, end_at__gt=now).order_by('start_at')
    past = mine.exclude(status=Booking.Status.CONFIRMED, end_at__gt=now).order_by('-start_at')
    return render(request, 'core/booking/my_bookings.html', {
        'tab': tab, 'bookings': upcoming if tab == 'upcoming' else past[:50],
        'upcoming_count': upcoming.count(), 'section': 'mine',
    })


def _own_booking_or_404(request, ref):
    booking = get_object_or_404(Booking.objects.select_related('turf'), reference=ref.upper())
    if booking.user_id != request.user.id and not request.user.is_superuser:
        raise Http404
    return booking


@login_required
def booking_detail(request, ref):
    booking = _own_booking_or_404(request, ref)
    link = request.build_absolute_uri(reverse('book_turf', args=[booking.turf.slug]))
    share = (
        f"I've booked {booking.turf.name}, {bl.human_when(booking.start_at, booking.end_at)}. "
        f"Join me: {link}"
    )
    # Only a live ticket gets a code; cancelled or finished bookings have nothing to scan.
    code = None
    if booking.is_upcoming and booking.source == Booking.Source.ONLINE:
        code = mark_safe(qr.svg(bl.ticket_token(booking), label=f"Ticket {booking.reference}"))
    return render(request, 'core/booking/ticket.html', {
        'b': booking, 'turf': booking.turf, 'is_new': request.GET.get('new') == '1',
        'share_text': share, 'qr': code,
        'host_url': f"{reverse('create_match')}?turf={booking.turf_id}",
    })


@login_required
@require_POST
def booking_cancel(request, ref):
    booking = _own_booking_or_404(request, ref)
    if not booking.player_can_cancel:
        messages.error(request, "Free cancellation has closed. Please call the turf.")
    else:
        bl.cancel_booking(booking, Booking.CancelledBy.PLAYER)
        bl.notify_booking_cancelled(booking, Booking.CancelledBy.PLAYER)
        messages.success(request, "Booking cancelled.")
    return redirect('booking_detail', ref=booking.reference)


@login_required
def booking_ics(request, ref):
    booking = _own_booking_or_404(request, ref)
    resp = HttpResponse(bl.build_ics(booking), content_type='text/calendar; charset=utf-8')
    resp['Content-Disposition'] = f'attachment; filename="{booking.reference}.ics"'
    return resp


# ---------------------------------------------------------------------------
# turf admin console
# ---------------------------------------------------------------------------

@login_required
def manage_home(request):
    if request.user.is_superuser:
        turfs = list(Turf.objects.filter(is_active=True, booking_enabled=True))
    else:
        turfs = bl.managed_turfs(request.user)
    if len(turfs) == 1:
        return redirect('manage_schedule', slug=turfs[0].slug)
    if not turfs and not request.user.is_superuser:
        raise PermissionDenied
    return render(request, 'core/booking/manage_pick.html', {'turfs': turfs})


@console_view
def manage_schedule(request, turf):
    today = bl.local_today()
    day = bl.parse_day(request.GET.get('date'), today)
    lo, hi = today - timedelta(days=bl.CONSOLE_DAYS_BACK), today + timedelta(days=turf.advance_days)
    if not lo <= day <= hi:
        day = today
    return render(request, 'core/booking/manage_schedule.html', {
        'turf': turf, 'day': day, 'tab': 'schedule', 'cfg': _console_cfg(turf, day),
        'stats': bl.day_stats(turf, day), 'next_up': bl.next_up(turf),
    })


@console_view
def manage_scan(request, turf):
    cfg = {
        'verifyUrl': reverse('manage_scan_api', args=[turf.slug]),
        'admitUrl': reverse('manage_scan_admit', args=[turf.slug]),
    }
    return render(request, 'core/booking/manage_scan.html', {
        'turf': turf, 'tab': 'scan', 'cfg': cfg,
    })


@console_view
@require_POST
def manage_scan_api(request, turf):
    """Look a ticket up. Accepts a scanned QR payload, or a typed reference (manual=1)."""
    booking, state = bl.find_ticket(
        turf, request.POST.get('code', ''), manual=request.POST.get('manual') == '1'
    )
    if state == 'ok':
        state = bl.scan_state(booking)
    resp = JsonResponse(bl.scan_payload(booking, state))
    resp['Cache-Control'] = 'no-store'
    return resp


@console_view
@require_POST
def manage_scan_admit(request, turf):
    """Let a ticket holder in. Only the first scan succeeds."""
    booking = get_object_or_404(
        Booking, turf=turf, reference=request.POST.get('ref', '').upper(),
        source__in=[Booking.Source.ONLINE, Booking.Source.WALKIN],
    )
    collect = request.POST.get('collect') == '1'
    if bl.scan_state(booking) == 'ok' and bl.admit_booking(booking, collect):
        return JsonResponse({'ok': True, 'message': 'Admitted'})
    booking.refresh_from_db()
    state = bl.scan_state(booking)
    if state == 'ok':          # another phone admitted it a moment before this one
        state = 'used'
        booking.scanned_at = booking.scanned_at or timezone.now()
    return JsonResponse({'ok': False, **bl.scan_payload(booking, state)}, status=409)


@console_view
def manage_slots_api(request, turf):
    day = bl.parse_day(request.GET.get('date'))
    today = bl.local_today()
    if day is None or not (today - timedelta(days=bl.CONSOLE_DAYS_BACK) <= day <= today + timedelta(days=turf.advance_days)):
        return JsonResponse({'error': 'bad date'}, status=400)
    return _json_with_etag(request, bl.availability_payload(turf, day, admin=True))


@console_view
def manage_bookings(request, turf):
    tab = request.GET.get('tab', 'upcoming')
    q = (request.GET.get('q') or '').strip()
    now = timezone.now()
    qs = Booking.objects.filter(turf=turf).exclude(source=Booking.Source.BLOCKED).select_related('user', 'user__profile')
    if tab == 'cancelled':
        qs = qs.filter(status=Booking.Status.CANCELLED).order_by('-cancelled_at')
    elif tab == 'past':
        qs = qs.filter(status=Booking.Status.CONFIRMED, end_at__lte=now).order_by('-start_at')
    else:
        tab = 'upcoming'
        qs = qs.filter(status=Booking.Status.CONFIRMED, end_at__gt=now).order_by('start_at')
    if q:
        qs = qs.filter(
            Q(reference__icontains=q) | Q(guest_name__icontains=q) | Q(guest_phone__icontains=q)
            | Q(user__first_name__icontains=q) | Q(user__profile__phone__icontains=q)
        )
    return render(request, 'core/booking/manage_bookings.html', {
        'turf': turf, 'tab': 'bookings', 'sub': tab, 'q': q, 'bookings': qs[:100],
    })


@console_view
def manage_settings(request, turf):
    form = TurfSettingsForm(instance=turf)
    pw_form = PasswordChangeForm(request.user)
    if request.method == 'POST':
        if request.POST.get('action') == 'password':
            pw_form = PasswordChangeForm(request.user, request.POST)
            if pw_form.is_valid():
                user = pw_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Password updated.")
                return redirect('manage_settings', slug=turf.slug)
        else:
            form = TurfSettingsForm(request.POST, instance=turf)
            if form.is_valid():
                form.save()
                messages.success(request, "Saved.")
                return redirect('manage_settings', slug=turf.slug)
    for f in pw_form.fields.values():
        f.widget.attrs['class'] = 'st-input'
        f.help_text = ''
    return render(request, 'core/booking/manage_settings.html', {
        'turf': turf, 'tab': 'settings', 'form': form, 'pw_form': pw_form,
    })


def _post_day(request):
    return bl.parse_day(request.POST.get('date'), bl.local_today())


@console_view
@require_POST
def manage_walkin(request, turf):
    day = _post_day(request)
    name = (request.POST.get('name') or '').strip()
    if not name:
        messages.error(request, "Add a name for the walk-in.")
        return _back_to_schedule(turf, day)
    try:
        b = bl.create_booking(
            turf, day, request.POST.get('start', ''), request.POST.get('count', 1),
            source=Booking.Source.WALKIN, guest_name=name, guest_phone=request.POST.get('phone', ''),
            paid=request.POST.get('paid') == 'on',
        )
        messages.success(request, f"Walk-in added: {name}, {bl.fmt_range(b.start_at, b.end_at)}.")
    except bl.BookingError as exc:
        messages.error(request, str(exc))
    return _back_to_schedule(turf, day)


@console_view
@require_POST
def manage_block(request, turf):
    day = _post_day(request)
    done, skipped = bl.block_slots(turf, day, request.POST.getlist('start'), (request.POST.get('reason') or '').strip())
    if done:
        messages.success(request, f"Blocked {done} slot{'s' if done != 1 else ''}.")
    if skipped:
        messages.error(request, f"{skipped} slot{'s' if skipped != 1 else ''} already taken.")
    return _back_to_schedule(turf, day)


@console_view
@require_POST
def manage_unblock(request, turf):
    b = get_object_or_404(Booking, turf=turf, reference=request.POST.get('ref', ''), source=Booking.Source.BLOCKED)
    day = timezone.localtime(b.start_at).date()
    b.delete()
    messages.success(request, "Slot reopened.")
    return _back_to_schedule(turf, day)


@console_view
@require_POST
def manage_close_day(request, turf):
    day = _post_day(request)
    done, _ = bl.close_day(turf, day)
    messages.success(request, f"{bl.fmt_day(day)} closed ({done} slot{'s' if done != 1 else ''}).")
    return _back_to_schedule(turf, day)


@console_view
@require_POST
def manage_reopen_day(request, turf):
    day = _post_day(request)
    count = bl.reopen_day(turf, day)
    messages.success(request, f"{bl.fmt_day(day)} reopened ({count} slot{'s' if count != 1 else ''}).")
    return _back_to_schedule(turf, day)


@console_view
@require_POST
def manage_booking_cancel(request, turf, ref):
    b = get_object_or_404(Booking, turf=turf, reference=ref.upper(), source__in=[Booking.Source.ONLINE, Booking.Source.WALKIN])
    reason = (request.POST.get('reason') or '').strip()
    day = timezone.localtime(b.start_at).date()
    if b.status == Booking.Status.CONFIRMED:
        bl.cancel_booking(b, Booking.CancelledBy.TURF, reason)
        bl.notify_booking_cancelled(b, Booking.CancelledBy.TURF, reason)
        messages.success(request, f"Booking {b.reference} cancelled.")
    return _back_to_schedule(turf, day)


@console_view
@require_POST
def manage_booking_paid(request, turf, ref):
    b = get_object_or_404(Booking, turf=turf, reference=ref.upper(), status=Booking.Status.CONFIRMED)
    b.payment_status = (Booking.Payment.PENDING if b.payment_status == Booking.Payment.PAID else Booking.Payment.PAID)
    b.save(update_fields=['payment_status'])
    messages.success(request, f"{b.reference} marked {'paid' if b.payment_status == Booking.Payment.PAID else 'unpaid'}.")
    return _back_to_schedule(turf, timezone.localtime(b.start_at).date())
