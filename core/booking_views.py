"""Views for turf slot booking: the player flow (browse -> pick -> ticket) and
the turf-admin console (schedule, walk-ins, blocks, bookings, settings)."""
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
from django.views.decorators.http import require_POST

from . import booking_logic as bl
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
    cards = []
    for t in turfs:
        if sport and sport.lower() not in [s.lower() for s in t.sport_list]:
            continue
        cards.append({'turf': t, 'free_today': bl.free_slots_today(t), 'open_now': bl.is_open_now(t)})
    return render(request, 'core/booking/directory.html', {
        'cards': cards, 'q': q, 'sport': sport, 'all_sports': all_sports,
    })


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
    resp = JsonResponse(bl.availability_payload(turf, day, user=request.user))
    resp['Cache-Control'] = 'no-store'
    return resp


@login_required
@require_POST
def book_confirm(request, slug):
    turf = _bookable_turf_or_404(slug)
    day = bl.parse_day(request.POST.get('date'), bl.local_today())
    back = f"{reverse('book_turf', args=[turf.slug])}?date={day.isoformat()}"
    if bl.is_turf_admin(request.user):
        messages.error(request, "Turf admin accounts manage turfs — use a player account to book.")
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
        'upcoming_count': upcoming.count(),
    })


def _own_booking_or_404(request, ref):
    booking = get_object_or_404(Booking.objects.select_related('turf'), reference=ref.upper())
    if booking.user_id != request.user.id and not request.user.is_superuser:
        raise Http404
    return booking


@login_required
def booking_detail(request, ref):
    booking = _own_booking_or_404(request, ref)
    share = (f"I've booked {booking.turf.name} — {bl.human_when(booking.start_at, booking.end_at)}. "
             f"Join me! 🏟️⚽ {request.build_absolute_uri(reverse('book_turf', args=[booking.turf.slug]))}")
    return render(request, 'core/booking/ticket.html', {
        'b': booking, 'turf': booking.turf, 'is_new': request.GET.get('new') == '1', 'share_text': share,
        'host_url': f"{reverse('create_match')}?turf={booking.turf_id}",
    })


@login_required
@require_POST
def booking_cancel(request, ref):
    booking = _own_booking_or_404(request, ref)
    if not booking.player_can_cancel:
        messages.error(request, "The free-cancellation window has closed — please call the turf.")
    else:
        bl.cancel_booking(booking, Booking.CancelledBy.PLAYER)
        bl.notify_booking_cancelled(booking, Booking.CancelledBy.PLAYER)
        messages.success(request, "Booking cancelled. The slot is open for others again.")
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
def manage_slots_api(request, turf):
    day = bl.parse_day(request.GET.get('date'))
    today = bl.local_today()
    if day is None or not (today - timedelta(days=bl.CONSOLE_DAYS_BACK) <= day <= today + timedelta(days=turf.advance_days)):
        return JsonResponse({'error': 'bad date'}, status=400)
    resp = JsonResponse(bl.availability_payload(turf, day, admin=True))
    resp['Cache-Control'] = 'no-store'
    return resp


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
                messages.success(request, "Turf details saved.")
                return redirect('manage_settings', slug=turf.slug)
    for f in pw_form.fields.values():
        f.widget.attrs['class'] = 'bk-input'
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
        messages.error(request, "Add a name for the walk-in booking.")
        return _back_to_schedule(turf, day)
    try:
        b = bl.create_booking(
            turf, day, request.POST.get('start', ''), request.POST.get('count', 1),
            source=Booking.Source.WALKIN, guest_name=name, guest_phone=request.POST.get('phone', ''),
            paid=request.POST.get('paid') == 'on',
        )
        messages.success(request, f"Walk-in booked for {name} · {bl.fmt_range(b.start_at, b.end_at)}.")
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
        messages.error(request, f"{skipped} slot{'s' if skipped != 1 else ''} couldn't be blocked (already taken).")
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
    messages.success(request, f"Closed {bl.fmt_day(day)} — {done} open slot{'s' if done != 1 else ''} blocked.")
    return _back_to_schedule(turf, day)


@console_view
@require_POST
def manage_reopen_day(request, turf):
    day = _post_day(request)
    count = bl.reopen_day(turf, day)
    messages.success(request, f"Reopened {bl.fmt_day(day)} — {count} slot{'s' if count != 1 else ''} released.")
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
