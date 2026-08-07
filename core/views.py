from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import LoginForm, MatchForm, SignupForm
from .models import JoinRequest, Match, Profile, Rating, Turf

FEED_LOOKBACK = timedelta(hours=1)
NOTIF_LOOKBACK = timedelta(hours=2)
PAST_CUTOFF = timedelta(hours=1)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def signup(request):
    if request.user.is_authenticated:
        return redirect('feed')

    form = SignupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        name = form.cleaned_data['name']
        phone = form.cleaned_data['phone']

        if Profile.objects.filter(phone=phone).exists():
            messages.error(request, "That mobile number is already registered. Please log in instead.")
            return redirect('login')

        base_username = name.lower().replace(' ', '_')
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}_{counter}"
            counter += 1

        user = User.objects.create_user(username=username, first_name=name)
        Profile.objects.create(user=user, phone=phone)

        login(request, user)
        messages.success(request, f"Welcome to SquadTurf, {name}! 🎉")
        return redirect('feed')

    return render(request, 'core/signup.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('feed')

    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        phone = form.cleaned_data['phone']
        try:
            profile = Profile.objects.select_related('user').get(phone=phone)
        except Profile.DoesNotExist:
            messages.error(request, "No account found with that number. Please sign up first.")
            return redirect('signup')

        login(request, profile.user)
        messages.success(request, f"Welcome back, {profile.display_name}! 👋")
        return redirect('feed')

    return render(request, 'core/login.html', {'form': form})


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
    start_cutoff = now - FEED_LOOKBACK
    end_cutoff = now - NOTIF_LOOKBACK

    base_qs = Match.objects.filter(status=Match.Status.OPEN, match_time__gte=start_cutoff) \
        .select_related('turf', 'host')

    urgent_matches = list(base_qs.filter(match_type=Match.MatchType.URGENT).order_by('match_time'))
    scheduled_matches = list(base_qs.filter(match_type=Match.MatchType.SCHEDULED).order_by('match_time'))

    host_notifications = []
    joinee_notifications = []
    user_request_map = {}

    if request.user.is_authenticated:
        host_notifications = JoinRequest.objects.filter(
            match__host=request.user,
            status__in=[JoinRequest.Status.PENDING, JoinRequest.Status.ACCEPTED],
            match__match_time__gte=start_cutoff,
        ).select_related('player', 'player__profile', 'match', 'match__turf').order_by('-created_at')

        joinee_notifications = JoinRequest.objects.filter(
            player=request.user,
            status=JoinRequest.Status.ACCEPTED,
            match__match_time__gte=start_cutoff,
        ).select_related('match', 'match__turf', 'match__host', 'match__host__profile') | \
            JoinRequest.objects.filter(
                player=request.user,
                status=JoinRequest.Status.REJECTED,
                match__match_time__gte=end_cutoff,
            ).select_related('match', 'match__turf', 'match__host', 'match__host__profile')
        joinee_notifications = joinee_notifications.order_by('-created_at')

        user_request_map = dict(
            JoinRequest.objects.filter(player=request.user).values_list('match_id', 'status')
        )

    for match in urgent_matches + scheduled_matches:
        match.user_req_status = user_request_map.get(match.id)

    context = {
        'urgent_matches': urgent_matches,
        'scheduled_matches': scheduled_matches,
        'host_notifications': host_notifications,
        'joinee_notifications': joinee_notifications,
    }
    return render(request, 'core/feed.html', context)


def turf_landing(request, slug):
    turf = get_object_or_404(Turf, slug=slug, is_active=True)
    return redirect(f"/match/create/?turf={turf.id}")


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

            if match.match_type == Match.MatchType.URGENT:
                offset = int(form.cleaned_data.get('emergency_time_offset') or 15)
                match.match_time = timezone.now() + timedelta(minutes=offset)
            else:
                scheduled = form.cleaned_data.get('match_time_scheduled')
                match.match_time = scheduled or (timezone.now() + timedelta(hours=2))

            if match.cost_model == Match.CostModel.FREE:
                match.per_head_amount = 0

            match.save()
            messages.success(request, "Match request posted! Players nearby will see it now.")
            return redirect('feed')
    else:
        initial = {}
        if preselected_turf_id:
            try:
                initial['turf'] = int(preselected_turf_id)
            except ValueError:
                pass
        form = MatchForm(initial=initial)

    context = {
        'form': form,
        'now_iso': timezone.now().strftime('%Y-%m-%dT%H:%M'),
    }
    return render(request, 'core/create_match.html', context)


def match_detail(request, match_id):
    match = get_object_or_404(Match.objects.select_related('turf', 'host', 'host__profile'), id=match_id)
    is_host = request.user.is_authenticated and request.user == match.host
    is_past = match.match_time < (timezone.now() - PAST_CUTOFF)

    join_requests = None
    user_request = None
    existing_rating = None

    if is_host:
        join_requests = match.requests.select_related('player', 'player__profile').order_by('-created_at')
    elif request.user.is_authenticated:
        user_request = JoinRequest.objects.filter(match=match, player=request.user).first()

    if request.user.is_authenticated and is_past:
        existing_rating = Rating.objects.filter(match=match, rater=request.user).first()

    context = {
        'match': match,
        'is_host': is_host,
        'join_requests': join_requests,
        'user_request': user_request,
        'is_past': is_past,
        'existing_rating': existing_rating,
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
    elif join_req.status == JoinRequest.Status.CANCELLED:
        join_req.status = JoinRequest.Status.PENDING
        join_req.save(update_fields=['status'])
        messages.success(request, "Your request to join has been re-submitted.")
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
    return redirect('match_detail', match_id=match_id)


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

    elif action == 'reject':
        if join_req.status == JoinRequest.Status.ACCEPTED:
            match.players_needed += 1
            if match.status == Match.Status.FILLED:
                match.status = Match.Status.OPEN
            match.save(update_fields=['players_needed', 'status'])

        join_req.status = JoinRequest.Status.REJECTED
        join_req.save(update_fields=['status'])
        messages.info(request, f"Declined request from {player_name}.")

    return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required
def submit_rating(request, match_id):
    match = get_object_or_404(Match, id=match_id)

    if request.method == 'POST':
        stars = int(request.POST.get('stars', 5))
        showed_up = request.POST.get('showed_up') == 'on'

        rated_user = None
        if request.user.id != match.host_id:
            rated_user = match.host
        else:
            accepted = match.requests.filter(status=JoinRequest.Status.ACCEPTED).first()
            if accepted:
                rated_user = accepted.player

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
# Dashboards
# ---------------------------------------------------------------------------

@login_required
def my_hosted(request):
    now_cutoff = timezone.now() - PAST_CUTOFF
    hosted = Match.objects.filter(host=request.user).select_related('turf') \
        .prefetch_related('requests__player__profile').order_by('-match_time')

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
