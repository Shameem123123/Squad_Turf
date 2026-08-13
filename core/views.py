import json
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import LoginForm, MatchForm, OtpForm, ProfileEditForm, SignupForm
from .models import JoinRequest, Match, Notification, Profile, PushSubscription, Rating, Turf
from .notifications import notify
from . import otp as otp_service

FEED_LOOKBACK = timedelta(hours=1)      # how long an OPEN match stays live on the feed after kickoff
NOTIF_LOOKBACK = timedelta(hours=2)     # how long home-page notifications stay visible after kickoff
PAST_CUTOFF = timedelta(hours=1)        # when a match is considered "over" in dashboards
RECENT_PLAYED_WINDOW = timedelta(hours=4)
IMMINENT_WINDOW = timedelta(hours=2)    # a match this close to kickoff is treated as urgent, whatever it was hosted as
URGENT_MAX_WINDOW = timedelta(hours=2, minutes=30)  # urgent matches can only be booked up to this far out


# ---------------------------------------------------------------------------
# Auth — signup needs name + phone + OTP (proves the number is real).
# Login only needs phone + password afterwards, so day-to-day sign-in
# doesn't cost an OTP/SMS every time.
# ---------------------------------------------------------------------------

def signup(request):
    if request.user.is_authenticated:
        return redirect('feed')

    form = SignupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        name = form.cleaned_data['name']
        phone = form.cleaned_data['phone']
        password = form.cleaned_data['password']

        if Profile.objects.filter(phone=phone).exists():
            messages.error(request, "That mobile number is already registered. Please log in instead.")
            return redirect('login')

        if not otp_service.otp_required():
            _create_and_login(request, name, phone, password)
            messages.success(request, f"Welcome to SquadTurf, {name}! 🎉")
            return redirect('feed')

        otp, debug_code = otp_service.issue_otp(phone, 'SIGNUP')
        request.session['pending_auth'] = {'flow': 'signup', 'name': name, 'phone': phone, 'password': password}
        if debug_code:
            messages.info(request, f"Dev mode — no SMS provider configured. Your code is {debug_code}.")
        else:
            messages.success(request, f"We've sent a 6-digit code to {phone}.")
        return redirect('verify_otp')

    return render(request, 'core/signup.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('feed')

    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        phone = form.cleaned_data['phone']
        password = form.cleaned_data['password']
        try:
            profile = Profile.objects.select_related('user').get(phone=phone)
        except Profile.DoesNotExist:
            messages.error(request, "No account found with that number. Please sign up first.")
            return redirect('signup')

        user = authenticate(request, username=profile.user.username, password=password)
        if user is None:
            form.add_error('password', "Incorrect password.")
            return render(request, 'core/login.html', {'form': form})

        login(request, user)
        messages.success(request, f"Welcome back, {profile.display_name}! 👋")
        return redirect('feed')

    return render(request, 'core/login.html', {'form': form})


def verify_otp(request):
    pending = request.session.get('pending_auth')
    if not pending:
        messages.error(request, "That verification link expired. Please start again.")
        return redirect('login')

    phone = pending['phone']

    form = OtpForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        ok, error = otp_service.verify_otp(phone, 'SIGNUP', form.cleaned_data['code'])
        if ok:
            del request.session['pending_auth']
            _create_and_login(request, pending['name'], phone, pending['password'])
            messages.success(request, f"Welcome to SquadTurf, {pending['name']}! 🎉")
            return redirect('feed')
        messages.error(request, error)

    masked = phone[:2] + '••••••' + phone[-2:]
    return render(request, 'core/verify_otp.html', {'form': form, 'masked_phone': masked})


def resend_otp(request):
    pending = request.session.get('pending_auth')
    if not pending:
        messages.error(request, "That verification link expired. Please start again.")
        return redirect('login')

    phone = pending['phone']
    purpose = 'SIGNUP'

    if not otp_service.can_resend(phone, purpose):
        messages.error(request, f"Please wait a few seconds before requesting another code.")
        return redirect('verify_otp')

    otp, debug_code = otp_service.issue_otp(phone, purpose)
    if debug_code:
        messages.info(request, f"Dev mode — your new code is {debug_code}.")
    else:
        messages.success(request, "A new code is on its way.")
    return redirect('verify_otp')


def _create_and_login(request, name, phone, password):
    base_username = name.lower().replace(' ', '_') or 'player'
    username = base_username
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f"{base_username}_{counter}"
        counter += 1

    user = User.objects.create_user(username=username, first_name=name, password=password)
    Profile.objects.create(user=user, phone=phone)
    login(request, user)


@login_required
def logout_view(request):
    logout(request)
    messages.info(request, "You've been logged out. See you on the pitch!")
    return redirect('login')


# ---------------------------------------------------------------------------
# Feed & discovery
# ---------------------------------------------------------------------------

def feed(request):
    now = timezone.now()
    local_today = timezone.localtime(now).date()
    local_tomorrow = local_today + timedelta(days=1)

    live_cutoff = now - FEED_LOOKBACK
    notif_cutoff = now - NOTIF_LOOKBACK

    day_filter = request.GET.get('day', 'all')
    turf_filter = request.GET.get('turf', '').strip()

    base_qs = Match.objects.filter(status=Match.Status.OPEN, match_time__gte=live_cutoff) \
        .select_related('turf', 'host')

    # distinct turfs among *currently open* matches — drives whether the
    # turf filter is worth showing at all (spec: only when 2+ turfs need players)
    open_turf_ids = set(base_qs.values_list('turf_id', flat=True))
    show_turf_filter = len(open_turf_ids) > 1
    filter_turfs = Turf.objects.filter(id__in=open_turf_ids)

    if turf_filter:
        base_qs = base_qs.filter(turf_id=turf_filter)
    if day_filter == 'today':
        base_qs = base_qs.filter(match_time__date=local_today)
    elif day_filter == 'tomorrow':
        base_qs = base_qs.filter(match_time__date=local_tomorrow)

    # Reallocate by time-to-kickoff, not just how it was hosted: a
    # "Scheduled" match within IMMINENT_WINDOW is just as urgent to a
    # player scrolling the feed as one hosted as "Urgent".
    imminent_cutoff = now + IMMINENT_WINDOW
    all_matches = list(base_qs.order_by('match_time'))
    urgent_matches = [m for m in all_matches if m.match_time <= imminent_cutoff]
    scheduled_matches = [m for m in all_matches if m.match_time > imminent_cutoff]
    for m in urgent_matches:
        m.is_imminent = True
    for m in scheduled_matches:
        m.is_imminent = False

    # "Recently played" — a handful of just-finished matches so the feed
    # never looks dead, greyed out, never counted in the live sections.
    recent_played = list(
        Match.objects.filter(
            status__in=[Match.Status.OPEN, Match.Status.FILLED],
            match_time__lt=live_cutoff,
            match_time__gte=now - RECENT_PLAYED_WINDOW,
        ).select_related('turf', 'host').order_by('-match_time')[:5]
    )

    host_notifications = []
    joinee_notifications = []
    user_request_map = {}

    if request.user.is_authenticated:
        host_notifications = JoinRequest.objects.filter(
            match__host=request.user,
            status__in=[JoinRequest.Status.PENDING, JoinRequest.Status.ACCEPTED],
            match__match_time__gte=notif_cutoff,
        ).select_related('player', 'player__profile', 'match', 'match__turf').order_by('-created_at')

        joinee_notifications = JoinRequest.objects.filter(
            player=request.user,
            status__in=[JoinRequest.Status.ACCEPTED, JoinRequest.Status.REJECTED],
            match__match_time__gte=notif_cutoff,
        ).select_related(
            'match', 'match__turf', 'match__host', 'match__host__profile'
        ).order_by('-created_at')

        user_request_map = dict(
            JoinRequest.objects.filter(player=request.user).values_list('match_id', 'status')
        )

    for match in urgent_matches + scheduled_matches + recent_played:
        match.user_req_status = user_request_map.get(match.id)

    context = {
        'urgent_matches': urgent_matches,
        'scheduled_matches': scheduled_matches,
        'recent_played': recent_played,
        'host_notifications': host_notifications,
        'joinee_notifications': joinee_notifications,
        'show_turf_filter': show_turf_filter,
        'filter_turfs': filter_turfs,
        'day_filter': day_filter,
        'turf_filter': turf_filter,
        # Tomorrow can never contain an "urgent" (<=2h to kickoff) match, so
        # don't show an always-empty "Starting soon" section for that view.
        'show_urgent_section': day_filter != 'tomorrow',
    }
    return render(request, 'core/feed.html', context)


def turf_landing(request, slug):
    turf = get_object_or_404(Turf, slug=slug, is_active=True)
    return redirect(f"/match/create/?turf={turf.id}")


def turf_directory(request):
    search = request.GET.get('q', '').strip()
    turfs = Turf.objects.filter(is_active=True)
    if search:
        turfs = turfs.filter(Q(name__icontains=search) | Q(location_name__icontains=search))

    open_counts = {}
    for m in Match.objects.filter(status=Match.Status.OPEN, match_time__gte=timezone.now() - FEED_LOOKBACK):
        open_counts[m.turf_id] = open_counts.get(m.turf_id, 0) + 1

    turfs = list(turfs)
    for t in turfs:
        t.open_match_count = open_counts.get(t.id, 0)

    return render(request, 'core/turfs.html', {'turfs': turfs, 'search': search})


def turf_detail(request, slug):
    """A single turf's page: live match count + every currently open match
    there (a filtered view of the feed, scoped to this ground), plus a
    shortcut to host a new match at the same turf."""
    turf = get_object_or_404(Turf, slug=slug, is_active=True)
    now = timezone.now()
    live_cutoff = now - FEED_LOOKBACK
    imminent_cutoff = now + IMMINENT_WINDOW

    matches = list(
        Match.objects.filter(turf=turf, status=Match.Status.OPEN, match_time__gte=live_cutoff)
        .select_related('turf', 'host').order_by('match_time')
    )

    user_request_map = {}
    if request.user.is_authenticated:
        user_request_map = dict(
            JoinRequest.objects.filter(player=request.user).values_list('match_id', 'status')
        )

    for m in matches:
        m.is_imminent = m.match_time <= imminent_cutoff
        m.user_req_status = user_request_map.get(m.id)

    return render(request, 'core/turf_detail.html', {'turf': turf, 'matches': matches})


# ---------------------------------------------------------------------------
# Match lifecycle
# ---------------------------------------------------------------------------

@login_required
def create_match(request):
    preselected_turf_id = request.GET.get('turf')

    if request.method == 'POST':
        form = MatchForm(request.POST)
        if form.is_valid():
            match = form.save(commit=False)
            match.host = request.user
            match.status = Match.Status.OPEN

            now = timezone.now()
            local_today = timezone.localtime(now).date()
            if match.match_type == Match.MatchType.URGENT:
                chosen_date = local_today
            else:
                date_choice = form.cleaned_data.get('match_date_choice') or 'TODAY'
                chosen_date = local_today if date_choice == 'TODAY' else local_today + timedelta(days=1)

            slot = form.cleaned_data.get('match_time_slot') or '18:00'
            hour, minute = (int(x) for x in slot.split(':'))
            naive_dt = datetime.combine(chosen_date, datetime.min.time().replace(hour=hour, minute=minute))
            match.match_time = timezone.make_aware(naive_dt) if timezone.is_naive(naive_dt) else naive_dt

            urgent_cutoff = now + URGENT_MAX_WINDOW

            # No one can play "now" or in the past — if today was chosen (or
            # implied, for urgent matches), the kickoff must be strictly
            # after the current moment. This applies regardless of whether
            # the host picked "Right now" or "Plan ahead" -> "Today".
            if chosen_date == local_today and match.match_time <= now:
                form.add_error(
                    None,
                    "That time is already here or has passed — pick an upcoming slot, "
                    "or choose Tomorrow."
                )
                return render(request, 'core/create_match.html', {'form': form})

            if match.match_type == Match.MatchType.URGENT:
                if match.match_time > urgent_cutoff:
                    form.add_error(
                        None,
                        "Urgent matches can only be booked up to 2.5 hours from now. "
                        "Choose 'Plan ahead' to schedule further out."
                    )
                    return render(request, 'core/create_match.html', {'form': form})
            else:
                # A "scheduled" match that actually lands inside the urgent
                # window (today, within the next 2.5h) collides with the
                # urgent bucket — host it as urgent instead, automatically.
                if chosen_date == local_today and now <= match.match_time <= urgent_cutoff:
                    match.match_type = Match.MatchType.URGENT

            if match.cost_model == Match.CostModel.FREE:
                match.per_head_amount = 0

            match.save()
            messages.success(request, "Match request posted! Players nearby will see it now.")
            _broadcast_new_match(match)
            return redirect('feed')
    else:
        initial = {}
        if preselected_turf_id:
            try:
                initial['turf'] = int(preselected_turf_id)
            except ValueError:
                pass
        form = MatchForm(initial=initial)

    return render(request, 'core/create_match.html', {'form': form})


def _broadcast_new_match(match):
    """The pillar feature: tell everyone (who's opted in) the moment a
    match goes up, so there's always a fast route to a full squad."""
    recipients = Profile.objects.filter(is_available_for_alerts=True) \
        .exclude(user_id=match.host_id).select_related('user')

    message = (
        f"New {match.get_match_type_display().split(' /')[0].lower()} match at {match.turf.name}: "
        f"{match.players_needed} player{'s' if match.players_needed != 1 else ''} needed, "
        f"{match.match_time.strftime('%I:%M %p').lstrip('0')} kickoff."
    )
    for profile in recipients:
        notify(profile.user, Notification.Verb.NEW_MATCH, message, match=match)


def match_detail(request, match_id):
    match = get_object_or_404(Match.objects.select_related('turf', 'host', 'host__profile'), id=match_id)
    is_host = request.user.is_authenticated and request.user == match.host
    is_past = match.match_time < (timezone.now() - PAST_CUTOFF)

    join_requests = None
    user_request = None
    is_accepted_player = False
    existing_rating = None      # a non-host accepted player's rating of the host
    rateable_players = []       # host-only: one rating slot per accepted player

    if is_host:
        join_requests = match.requests.select_related('player', 'player__profile').order_by('-created_at')
    elif request.user.is_authenticated:
        user_request = JoinRequest.objects.filter(match=match, player=request.user).first()
        is_accepted_player = bool(user_request and user_request.status == JoinRequest.Status.ACCEPTED)

    # Rating only makes sense for people who were actually part of the match:
    # the host (rating each player who showed up) or a player the host
    # actually accepted (rating the host). Anyone else viewing a past match
    # — a rejected/pending applicant, a random visitor — never sees the form.
    if request.user.is_authenticated and is_past:
        if is_host:
            accepted_reqs = match.requests.filter(
                status=JoinRequest.Status.ACCEPTED
            ).select_related('player', 'player__profile')
            given = {
                r.rated_user_id: r
                for r in Rating.objects.filter(match=match, rater=request.user)
            }
            for req in accepted_reqs:
                rateable_players.append({
                    'player': req.player,
                    'existing_rating': given.get(req.player_id),
                })
        elif is_accepted_player:
            existing_rating = Rating.objects.filter(
                match=match, rater=request.user, rated_user=match.host
            ).first()

    context = {
        'match': match,
        'is_host': is_host,
        'join_requests': join_requests,
        'user_request': user_request,
        'is_past': is_past,
        'is_accepted_player': is_accepted_player,
        'existing_rating': existing_rating,
        'rateable_players': rateable_players,
    }
    return render(request, 'core/match_detail.html', context)


@login_required
@transaction.atomic
def join_match(request, match_id):
    match = get_object_or_404(Match.objects.select_for_update(), id=match_id)

    if match.host_id == request.user.id:
        messages.error(request, "You can't request to join your own match.")
        return redirect('match_detail', match_id=match.id)

    if match.status != Match.Status.OPEN:
        messages.error(request, "This match is no longer open for new players.")
        return redirect('match_detail', match_id=match.id)

    join_req, created = JoinRequest.objects.get_or_create(
        match=match, player=request.user,
        defaults={'status': JoinRequest.Status.PENDING},
    )

    if created:
        messages.success(request, "Request sent! The host will review it shortly.")
        notify(
            match.host, Notification.Verb.JOIN_REQUEST,
            f"{request.user.first_name or request.user.username} wants to join your match at {match.turf.name}.",
            match=match,
        )
    elif join_req.status == JoinRequest.Status.CANCELLED:
        join_req.status = JoinRequest.Status.PENDING
        join_req.save(update_fields=['status'])
        messages.success(request, "Your request to join has been re-submitted.")
        notify(
            match.host, Notification.Verb.JOIN_REQUEST,
            f"{request.user.first_name or request.user.username} re-requested to join your match at {match.turf.name}.",
            match=match,
        )
    else:
        messages.info(request, "You've already requested to join this match.")

    return redirect('match_detail', match_id=match.id)


@login_required
@transaction.atomic
def cancel_join_request(request, match_id):
    join_req = get_object_or_404(
        JoinRequest.objects.select_for_update(),
        match_id=match_id, player=request.user, status=JoinRequest.Status.PENDING,
    )
    join_req.status = JoinRequest.Status.CANCELLED
    join_req.save(update_fields=['status'])
    messages.info(request, "Your request has been withdrawn.")
    return redirect('match_detail', match_id=match_id)


@login_required
@transaction.atomic
def leave_match(request, match_id):
    join_req = get_object_or_404(
        JoinRequest.objects.select_for_update(),
        match_id=match_id, player=request.user, status=JoinRequest.Status.ACCEPTED,
    )
    match = get_object_or_404(Match.objects.select_for_update(), id=match_id)

    join_req.status = JoinRequest.Status.CANCELLED
    join_req.save(update_fields=['status'])

    match.players_needed += 1
    if match.status == Match.Status.FILLED:
        match.status = Match.Status.OPEN
    match.save(update_fields=['players_needed', 'status'])

    messages.info(request, "You've stepped down. The open spot has been restored.")
    notify(
        match.host, Notification.Verb.PLAYER_LEFT,
        f"{request.user.first_name or request.user.username} stepped down from your match at {match.turf.name}. "
        f"You may want to find a replacement.",
        match=match,
    )
    return redirect('match_detail', match_id=match_id)


@login_required
@transaction.atomic
def cancel_match(request, match_id):
    match = get_object_or_404(Match.objects.select_for_update(), id=match_id, host=request.user)

    if match.status == Match.Status.CANCELLED:
        messages.info(request, "This match is already cancelled.")
        return redirect('match_detail', match_id=match_id)

    accepted_players = list(
        JoinRequest.objects.filter(match=match, status=JoinRequest.Status.ACCEPTED).select_related('player')
    )

    match.status = Match.Status.CANCELLED
    match.save(update_fields=['status'])

    for req in accepted_players:
        notify(
            req.player, Notification.Verb.MATCH_CANCELLED,
            f"The match at {match.turf.name} ({match.match_time:%d %b, %I:%M %p}) was cancelled by the host.",
            match=match,
        )

    messages.info(request, "Match cancelled. Everyone who'd joined has been notified.")
    return redirect('my_hosted')


@login_required
@transaction.atomic
def respond_request(request, request_id, action):
    join_req = get_object_or_404(JoinRequest.objects.select_for_update(), id=request_id)
    match = get_object_or_404(Match.objects.select_for_update(), id=join_req.match_id)

    if match.host_id != request.user.id:
        messages.error(request, "You're not authorized to manage this request.")
        return redirect('feed')

    player_name = join_req.player.first_name or join_req.player.username

    if action == 'accept':
        if match.status == Match.Status.FILLED or match.players_needed <= 0:
            messages.error(request, "Can't accept — this match is already full.")
            return redirect(request.META.get('HTTP_REFERER', '/'))

        join_req.status = JoinRequest.Status.ACCEPTED
        join_req.save(update_fields=['status'])

        match.players_needed -= 1
        if match.players_needed <= 0:
            match.status = Match.Status.FILLED
        match.save(update_fields=['players_needed', 'status'])
        messages.success(request, f"Accepted {player_name} for the match.")
        notify(
            join_req.player, Notification.Verb.REQUEST_ACCEPTED,
            f"You're in! Your host accepted your request for {match.turf.name}.",
            match=match,
        )

    elif action == 'reject':
        if join_req.status == JoinRequest.Status.ACCEPTED:
            match.players_needed += 1
            if match.status == Match.Status.FILLED:
                match.status = Match.Status.OPEN
            match.save(update_fields=['players_needed', 'status'])

        join_req.status = JoinRequest.Status.REJECTED
        join_req.save(update_fields=['status'])
        messages.info(request, f"Declined request from {player_name}.")
        notify(
            join_req.player, Notification.Verb.REQUEST_DECLINED,
            f"Your request to join the match at {match.turf.name} was declined.",
            match=match,
        )

    return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required
def submit_rating(request, match_id):
    """Each accepted player is rated separately — a host with three
    accepted players submits three independent ratings, one per player,
    instead of one rating standing in for the whole match. Only the host
    and players the host actually accepted are allowed to rate anyone."""
    match = get_object_or_404(Match, id=match_id)

    if request.method == 'POST':
        stars = max(1, min(5, int(request.POST.get('stars', 5))))
        showed_up = request.POST.get('showed_up') == 'on'

        rated_user = None
        if request.user.id == match.host_id:
            # Host rates one specific accepted player per submission.
            accepted_players = {
                r.player_id: r.player
                for r in match.requests.filter(
                    status=JoinRequest.Status.ACCEPTED
                ).select_related('player')
            }
            try:
                rated_user_id = int(request.POST.get('rated_user_id', ''))
            except (TypeError, ValueError):
                rated_user_id = None
            rated_user = accepted_players.get(rated_user_id)
        else:
            # Only a player the host actually accepted may rate the host.
            was_accepted = JoinRequest.objects.filter(
                match=match, player=request.user, status=JoinRequest.Status.ACCEPTED
            ).exists()
            if was_accepted:
                rated_user = match.host

        if rated_user:
            Rating.objects.update_or_create(
                match=match, rater=request.user, rated_user=rated_user,
                defaults={'stars': stars, 'showed_up': showed_up},
            )
            messages.success(request, "Thanks! Your feedback has been recorded.")
        else:
            messages.error(request, "There's no one to rate for this match yet.")

    return redirect('match_detail', match_id=match_id)


# ---------------------------------------------------------------------------
# Dashboards — matches/requests stay here forever (greyed out once over)
# so a host or player can always look up who played and their number.
# ---------------------------------------------------------------------------

@login_required
def my_hosted(request):
    now_cutoff = timezone.now() - PAST_CUTOFF
    hosted = Match.objects.filter(host=request.user).select_related('turf') \
        .prefetch_related('requests__player__profile').order_by('-created_at')

    matches_data = []
    for match in hosted:
        accepted_count = sum(1 for r in match.requests.all() if r.status == JoinRequest.Status.ACCEPTED)
        matches_data.append({
            'match': match,
            'is_past': match.match_time < now_cutoff,
            'accepted_count': accepted_count,
            'target_players': match.players_needed + accepted_count,
        })

    return render(request, 'core/my_hosted.html', {'matches_data': matches_data})


@login_required
def my_joined(request):
    now_cutoff = timezone.now() - PAST_CUTOFF
    reqs = JoinRequest.objects.filter(player=request.user).select_related(
        'match', 'match__turf', 'match__host', 'match__host__profile'
    ).order_by('-created_at')

    requests_data = [
        {'req': r, 'is_past': r.match.match_time < now_cutoff}
        for r in reqs
    ]
    return render(request, 'core/my_joined.html', {'requests_data': requests_data})


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@login_required
def profile(request):
    prof = request.user.profile

    if request.method == 'POST':
        form = ProfileEditForm(request.POST)
        if form.is_valid():
            request.user.first_name = form.cleaned_data['name']
            request.user.save(update_fields=['first_name'])
            prof.is_available_for_alerts = form.cleaned_data['is_available_for_alerts']
            prof.save(update_fields=['is_available_for_alerts'])
            messages.success(request, "Profile updated.")
            return redirect('profile')
    else:
        form = ProfileEditForm(initial={
            'name': request.user.first_name,
            'is_available_for_alerts': prof.is_available_for_alerts,
        })

    stats = {
        'hosted_count': Match.objects.filter(host=request.user).count(),
        # "Played" only counts matches actually completed — i.e. the user
        # was rated (showed-up/star review) by the host or a teammate
        # afterwards. An accepted-but-not-yet-played request doesn't count.
        'joined_count': Rating.objects.filter(rated_user=request.user).values('match_id').distinct().count(),
        'average_rating': prof.average_rating(),
        'rating_count': prof.rating_count(),
        'reliability_pct': prof.reliability_pct(),
        'push_enabled': PushSubscription.objects.filter(user=request.user).exists(),
    }

    return render(request, 'core/profile.html', {'form': form, 'stats': stats, 'profile': prof})


# ---------------------------------------------------------------------------
# Notifications & Web Push
# ---------------------------------------------------------------------------

@login_required
def notification_list(request):
    notes = Notification.objects.filter(recipient=request.user).select_related('match', 'match__turf')
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return render(request, 'core/notifications.html', {'notifications': notes})


@login_required
@require_POST
def push_subscribe(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'error': 'Invalid payload.'}, status=400)

    endpoint = data.get('endpoint')
    keys = data.get('keys', {})
    p256dh = keys.get('p256dh')
    auth = keys.get('auth')

    if not (endpoint and p256dh and auth):
        return JsonResponse({'ok': False, 'error': 'Missing subscription fields.'}, status=400)

    PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            'user': request.user,
            'p256dh': p256dh,
            'auth': auth,
            'user_agent': request.META.get('HTTP_USER_AGENT', '')[:255],
        },
    )
    return JsonResponse({'ok': True})


@login_required
@require_POST
def push_unsubscribe(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        data = {}
    endpoint = data.get('endpoint')
    if endpoint:
        PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
    return JsonResponse({'ok': True})


def live_status(request):
    """Polled every few seconds by live.js so the feed, notification badge
    and pending-request lists update without a manual page refresh — no
    websockets/Celery required, just a cheap signature comparison."""
    if not request.user.is_authenticated:
        return JsonResponse({'sig': '0', 'unread': 0})

    latest_match_id = Match.objects.order_by('-id').values_list('id', flat=True).first() or 0
    latest_notif_id = Notification.objects.filter(recipient=request.user).order_by('-id') \
        .values_list('id', flat=True).first() or 0
    latest_join_id = JoinRequest.objects.filter(
        Q(match__host=request.user) | Q(player=request.user)
    ).order_by('-id').values_list('id', flat=True).first() or 0
    unread = Notification.objects.filter(recipient=request.user, is_read=False).count()
    latest_verb = Notification.objects.filter(recipient=request.user) \
        .order_by('-id').values_list('verb', flat=True).first()

    sig = f"{latest_match_id}-{latest_notif_id}-{latest_join_id}"
    return JsonResponse({'sig': sig, 'unread': unread, 'latest_verb': latest_verb})


def vapid_public_key(request):
    """Small JSON endpoint so front-end JS can fetch the current VAPID
    public key without hardcoding it into a static file."""
    return JsonResponse({'publicKey': getattr(settings, 'VAPID_PUBLIC_KEY', '')})


def service_worker(request):
    """Serve the service worker from the site root so its scope covers
    the whole app (a SW served from /static/.../sw.js can only control
    /static/...  — push needs it at /sw.js)."""
    sw_path = Path(settings.BASE_DIR) / 'core' / 'static' / 'core' / 'js' / 'sw.js'
    content = sw_path.read_text(encoding='utf-8')
    response = HttpResponse(content, content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/'
    # Without this, some browsers/proxies cache sw.js for a while, so a
    # deployed fix (like this one) can take a long time to actually reach
    # a returning visitor's device.
    response['Cache-Control'] = 'no-cache'
    return response
