"""Tests for the home/flow restructure, QR tickets + scanner, and notifications."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from . import booking_logic as bl
from .models import Booking, Match, Notification, Turf, TurfManager
from .notifications import NOTIFICATION_TTL
from .tests_bookings import BookingBase, make_user
from . import views


def soon_booking(turf, user, minutes_from_now=30):
    now = timezone.now()
    return Booking.objects.create(
        turf=turf, user=user, start_at=now + timedelta(minutes=minutes_from_now),
        end_at=now + timedelta(minutes=minutes_from_now + 60), amount=Decimal(1000),
    )


class TicketTokens(BookingBase):
    def test_roundtrip_and_forgery(self):
        b = self.book('10:00')
        token = bl.ticket_token(b)
        self.assertEqual(bl.parse_ticket_token(token), b.reference)
        prefix, ref, sig = token.split('.')
        self.assertIsNone(bl.parse_ticket_token(f"{prefix}.{ref}.{'0' * len(sig)}"))
        self.assertIsNone(bl.parse_ticket_token(f"{prefix}.{ref}"))
        self.assertIsNone(bl.parse_ticket_token(b.reference))          # bare reference isn't a QR payload
        self.assertIsNone(bl.parse_ticket_token(''))
        self.assertIsNone(bl.parse_ticket_token(None))

    def test_ticket_page_has_qr_only_while_live(self):
        b = self.book('10:00')
        self.client.login(username='asha', password='pass12345')
        page = self.client.get(reverse('booking_detail', args=[b.reference]))
        self.assertContains(page, 'class="st-qr"')
        self.assertContains(page, '<svg')
        bl.cancel_booking(b, 'PLAYER')
        page = self.client.get(reverse('booking_detail', args=[b.reference]))
        self.assertNotContains(page, 'class="st-qr"')


class Scanner(BookingBase):
    def setUp(self):
        super().setUp()
        self.verify = reverse('manage_scan_api', args=['arena'])
        self.admit = reverse('manage_scan_admit', args=['arena'])

    def scan(self, booking, **extra):
        return self.client.post(self.verify, {'code': bl.ticket_token(booking), **extra}).json()

    def test_only_the_turf_manager_can_scan(self):
        b = soon_booking(self.turf, self.player)
        self.assertEqual(self.client.post(self.verify, {'code': bl.ticket_token(b)}).status_code, 302)
        self.client.login(username='ben', password='pass12345')
        self.assertEqual(self.client.post(self.verify, {'code': bl.ticket_token(b)}).status_code, 403)
        self.assertEqual(self.client.post(self.admit, {'ref': b.reference}).status_code, 403)
        self.assertEqual(self.client.get(reverse('manage_scan', args=['arena'])).status_code, 403)

    def test_scan_page_renders_for_manager(self):
        self.client.login(username='owner', password='pass12345')
        page = self.client.get(reverse('manage_scan', args=['arena']))
        self.assertContains(page, 'scan-video')
        self.assertContains(page, 'scan-cfg')

    def test_states(self):
        self.client.login(username='owner', password='pass12345')
        live = soon_booking(self.turf, self.player)
        res = self.scan(live)
        self.assertEqual(res['state'], 'ok')
        self.assertTrue(res['admit'])
        self.assertEqual(res['booking']['name'], 'Asha')

        early = self.book('10:00')                                    # three days away
        self.assertEqual(self.scan(early)['state'], 'early')
        self.assertFalse(self.scan(early)['admit'])

        ended = Booking.objects.create(
            turf=self.turf, user=self.player, start_at=timezone.now() - timedelta(hours=3),
            end_at=timezone.now() - timedelta(hours=2),
        )
        self.assertEqual(self.scan(ended)['state'], 'ended')

        cancelled = soon_booking(self.turf, self.player, 20)
        bl.cancel_booking(cancelled, 'PLAYER')
        self.assertEqual(self.scan(cancelled)['state'], 'cancelled')

        other = Turf.objects.create(name='Other', slug='other', location_name='X', booking_enabled=True)
        foreign = soon_booking(other, self.player)
        res = self.scan(foreign)
        self.assertEqual(res['state'], 'wrong_turf')
        self.assertNotIn('booking', res)                              # no details leak across turfs

        self.assertEqual(self.client.post(self.verify, {'code': 'nonsense'}).json()['state'], 'invalid')
        forged = f"SQT1.{live.reference}.deadbeef00"
        self.assertEqual(self.client.post(self.verify, {'code': forged}).json()['state'], 'invalid')

    def test_manual_entry_by_reference(self):
        self.client.login(username='owner', password='pass12345')
        b = soon_booking(self.turf, self.player)
        res = self.client.post(self.verify, {'code': b.reference.lower(), 'manual': '1'}).json()
        self.assertEqual(res['state'], 'ok')
        # a bare reference is NOT accepted from the camera path
        self.assertEqual(self.client.post(self.verify, {'code': b.reference}).json()['state'], 'invalid')

    def test_admit_once_and_collect_payment(self):
        self.client.login(username='owner', password='pass12345')
        b = soon_booking(self.turf, self.player)
        r = self.client.post(self.admit, {'ref': b.reference, 'collect': '1'})
        self.assertEqual(r.status_code, 200)
        b.refresh_from_db()
        self.assertTrue(b.is_scanned)
        self.assertEqual(b.payment_status, Booking.Payment.PAID)
        again = self.client.post(self.admit, {'ref': b.reference})
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.json()['state'], 'used')
        self.assertEqual(self.scan(b)['state'], 'used')

    def test_admit_without_payment_keeps_it_due(self):
        self.client.login(username='owner', password='pass12345')
        b = soon_booking(self.turf, self.player)
        self.client.post(self.admit, {'ref': b.reference, 'collect': '0'})
        b.refresh_from_db()
        self.assertTrue(b.is_scanned)
        self.assertEqual(b.payment_status, Booking.Payment.PENDING)

    def test_cannot_admit_a_booking_of_another_turf(self):
        self.client.login(username='owner', password='pass12345')
        other = Turf.objects.create(name='Other', slug='other', location_name='X', booking_enabled=True)
        foreign = soon_booking(other, self.player)
        self.assertEqual(self.client.post(self.admit, {'ref': foreign.reference}).status_code, 404)


class Notifications(BookingBase):
    def make(self, user, message='Hello', age=timedelta(0), read=False):
        n = Notification.objects.create(recipient=user, verb='NEW_MATCH', message=message, is_read=read)
        if age:
            Notification.objects.filter(pk=n.pk).update(created_at=timezone.now() - age)
        return n

    def test_new_items_show_as_unread_then_become_read(self):
        n = self.make(self.player)
        self.client.login(username='asha', password='pass12345')
        first = self.client.get(reverse('notification_list'))
        self.assertTrue(first.context['notifications'][0].was_unread)
        n.refresh_from_db()
        self.assertTrue(n.is_read)
        second = self.client.get(reverse('notification_list'))
        self.assertFalse(second.context['notifications'][0].was_unread)

    def test_expire_after_a_week(self):
        fresh = self.make(self.player, 'fresh', age=NOTIFICATION_TTL - timedelta(hours=1))
        stale = self.make(self.player, 'stale', age=NOTIFICATION_TTL + timedelta(hours=1))
        self.client.login(username='asha', password='pass12345')
        page = self.client.get(reverse('notification_list'))
        shown = [n.pk for n in page.context['notifications']]
        self.assertEqual(shown, [fresh.pk])
        self.assertFalse(Notification.objects.filter(pk=stale.pk).exists())   # removed for good

    def test_badge_and_live_count_ignore_expired(self):
        self.make(self.player, 'stale', age=NOTIFICATION_TTL + timedelta(days=1))
        self.make(self.player, 'fresh')
        self.client.login(username='asha', password='pass12345')
        self.assertEqual(self.client.get(reverse('live_status')).json()['unread'], 1)
        self.assertEqual(self.client.get(reverse('home')).context['unread_notification_count'], 1)

    def test_purge_command(self):
        self.make(self.player, 'stale', age=NOTIFICATION_TTL + timedelta(days=2))
        self.make(self.other, 'stale too', age=NOTIFICATION_TTL + timedelta(days=9))
        keep = self.make(self.player, 'fresh')
        call_command('purge_notifications')
        self.assertEqual(list(Notification.objects.values_list('pk', flat=True)), [keep.pk])

    def test_booking_notifications_link_to_ticket_and_console(self):
        b = self.book('19:00')
        bl.notify_booking_created(b)
        self.client.login(username='asha', password='pass12345')
        page = self.client.get(reverse('notification_list'))
        self.assertContains(page, reverse('booking_detail', args=[b.reference]))
        self.client.login(username='owner', password='pass12345')
        page = self.client.get(reverse('notification_list'))
        self.assertContains(page, 'New booking')

    def test_new_match_broadcast_skips_managers_and_host(self):
        manager = make_user('Mgr', '9000000009')                 # alerts on, but runs a turf
        TurfManager.objects.create(user=manager, turf=self.turf)
        match = Match.objects.create(
            host=self.player, turf=self.turf, match_type=Match.MatchType.URGENT, players_needed=3,
            match_time=timezone.now() + timedelta(hours=1),
        )
        views._broadcast_new_match(match)
        got = set(Notification.objects.filter(verb='NEW_MATCH').values_list('recipient__username', flat=True))
        self.assertEqual(got, {'ben'})


class Flow(BookingBase):
    def test_home_has_both_entry_points(self):
        page = self.client.get(reverse('home'))
        self.assertContains(page, reverse('book_directory'))
        self.assertContains(page, reverse('feed'))
        self.assertContains(page, 'Book a turf')
        self.assertContains(page, 'Find players')

    def test_home_shows_next_booking_for_players(self):
        b = self.book('10:00')
        self.client.login(username='asha', password='pass12345')
        self.assertContains(self.client.get(reverse('home')), reverse('booking_detail', args=[b.reference]))

    def test_managers_are_sent_to_their_console(self):
        self.client.login(username='owner', password='pass12345')
        for name in ('home', 'feed', 'my_hosted', 'my_joined', 'create_match'):
            r = self.client.get(reverse(name))
            self.assertRedirects(r, reverse('manage_home'), fetch_redirect_response=False, msg_prefix=name)

    def test_manager_profile_has_no_player_stats(self):
        self.client.login(username='owner', password='pass12345')
        page = self.client.get(reverse('profile'))
        self.assertNotContains(page, 'Play rating')
        self.assertNotContains(page, 'Showed up')
        self.client.login(username='asha', password='pass12345')
        self.assertContains(self.client.get(reverse('profile')), 'Play rating')

    def test_manager_nav_has_scan_and_no_player_tabs(self):
        self.client.login(username='owner', password='pass12345')
        page = self.client.get(reverse('manage_schedule', args=['arena']))
        self.assertContains(page, reverse('manage_scan', args=['arena']))
        self.assertNotContains(page, reverse('feed'))

    def test_book_tab_contains_my_bookings(self):
        self.client.login(username='asha', password='pass12345')
        page = self.client.get(reverse('book_directory'))
        self.assertContains(page, reverse('my_bookings'))
        self.assertContains(self.client.get(reverse('my_bookings')), reverse('book_directory'))

    def test_state_changing_endpoints_reject_get(self):
        match = Match.objects.create(
            host=self.other, turf=self.turf, match_type=Match.MatchType.SCHEDULED, players_needed=2,
            match_time=timezone.now() + timedelta(hours=5),
        )
        self.client.login(username='asha', password='pass12345')
        for name, args in [('join_match', [match.id]), ('cancel_join_request', [match.id]),
                           ('leave_match', [match.id]), ('cancel_match', [match.id]),
                           ('logout', [])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 405, name)
        self.assertEqual(self.client.post(reverse('join_match', args=[match.id])).status_code, 302)

    def test_logout_via_post(self):
        self.client.login(username='asha', password='pass12345')
        r = self.client.post(reverse('logout'))
        self.assertRedirects(r, reverse('login'), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('profile')).status_code, 302)

    def test_slots_api_supports_conditional_requests(self):
        url = reverse('book_slots_api', args=['arena']) + f'?date={self.day}'
        first = self.client.get(url)
        etag = first['ETag']
        self.assertTrue(etag)
        again = self.client.get(url, HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(again.status_code, 304)
        self.book('12:00')                                            # a change invalidates it
        self.assertEqual(self.client.get(url, HTTP_IF_NONE_MATCH=etag).status_code, 200)

    def test_batched_free_slots_match_the_single_turf_version(self):
        other = Turf.objects.create(
            name='Other', slug='other', location_name='X', booking_enabled=True, price_per_slot=500,
        )
        many = bl.free_slots_today_many([self.turf, other])
        self.assertEqual(many[self.turf.pk], bl.free_slots_today(self.turf))
        self.assertEqual(many[other.pk], bl.free_slots_today(other))


class HostFromBooking(BookingBase):
    """'Find players for this game' on a ticket opens the host form prefilled."""

    def local_booking(self, day_offset, hour, minute=0):
        local = timezone.localtime(timezone.now()).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        ) + timedelta(days=day_offset)
        return Booking.objects.create(
            turf=self.turf, user=self.player, start_at=local, end_at=local + timedelta(hours=1),
            amount=Decimal(1000),
        )

    def open_form(self, booking):
        self.client.login(username='asha', password='pass12345')
        return self.client.get(reverse('create_match'), {'booking': booking.reference})

    def test_ticket_link_carries_the_booking(self):
        b = self.book('10:00')
        self.client.login(username='asha', password='pass12345')
        page = self.client.get(reverse('booking_detail', args=[b.reference]))
        self.assertContains(page, f"{reverse('create_match')}?booking={b.reference}")

    def test_tomorrow_booking_prefills_turf_day_and_time(self):
        b = self.local_booking(1, 19, 0)
        form = self.open_form(b).context['form']
        self.assertEqual(form.initial['turf'], self.turf.pk)
        self.assertEqual(form.initial['match_type'], Match.MatchType.SCHEDULED)
        self.assertEqual(form.initial['match_date_choice'], 'TOMORROW')
        self.assertEqual(form.initial['match_time_slot'], '19:00')

    def test_prefilled_choices_are_selected_in_the_page(self):
        b = self.local_booking(1, 19, 0)
        page = self.open_form(b)
        self.assertContains(page, 'value="SCHEDULED" checked')
        self.assertContains(page, '<option value="19:00" selected>')
        self.assertContains(page, 'value="TOMORROW"')

    def test_start_time_is_rounded_down_to_the_half_hour(self):
        b = self.local_booking(1, 18, 45)
        self.assertEqual(self.open_form(b).context['form'].initial['match_time_slot'], '18:30')

    def test_booking_starting_soon_is_urgent(self):
        b = soon_booking(self.turf, self.player, 45)
        start = timezone.localtime(b.start_at)
        if start.date() != timezone.localdate():
            self.skipTest("booking crosses midnight")
        form = self.open_form(b).context['form']
        self.assertEqual(form.initial['match_type'], Match.MatchType.URGENT)
        self.assertEqual(form.initial['match_date_choice'], 'TODAY')
        self.assertEqual(form.initial['turf'], self.turf.pk)

    def test_far_future_booking_prefills_turf_only_and_explains(self):
        b = self.book('10:00')                                         # three days away
        page = self.open_form(b)
        form = page.context['form']
        self.assertEqual(form.initial['turf'], self.turf.pk)
        self.assertNotIn('match_time_slot', form.initial)
        self.assertContains(page, 'Games can be posted for today or tomorrow')

    def test_someone_elses_or_cancelled_booking_is_ignored(self):
        mine = self.local_booking(1, 19, 0)
        self.client.login(username='ben', password='pass12345')
        form = self.client.get(reverse('create_match'), {'booking': mine.reference}).context['form']
        self.assertNotIn('match_time_slot', form.initial)
        self.client.login(username='asha', password='pass12345')
        bl.cancel_booking(mine, 'PLAYER')
        form = self.client.get(reverse('create_match'), {'booking': mine.reference}).context['form']
        self.assertNotIn('match_time_slot', form.initial)


class ProfilePage(BookingBase):
    def test_account_without_a_profile_row_gets_the_page(self):
        bare = User.objects.create_user('bare', password='pass12345', first_name='Bare')
        self.client.login(username='bare', password='pass12345')
        self.assertEqual(self.client.get(reverse('profile')).status_code, 200)
        r = self.client.post(reverse('profile'), {'name': 'Renamed'})
        self.assertEqual(r.status_code, 302)
        bare.refresh_from_db()
        self.assertEqual(bare.first_name, 'Renamed')

    def test_superuser_and_linked_existing_user_get_the_page(self):
        User.objects.create_superuser('root', password='pass12345')
        self.client.login(username='root', password='pass12345')
        self.assertEqual(self.client.get(reverse('profile')).status_code, 200)
        linked = User.objects.create_user('linked', password='pass12345')
        TurfManager.objects.create(user=linked, turf=self.turf)       # no Profile created
        self.client.login(username='linked', password='pass12345')
        self.assertEqual(self.client.get(reverse('profile')).status_code, 200)
        self.assertEqual(self.client.get(reverse('manage_schedule', args=['arena'])).status_code, 200)

    def test_normal_player_profile_still_works(self):
        self.client.login(username='asha', password='pass12345')
        page = self.client.get(reverse('profile'))
        self.assertContains(page, self.player.profile.phone)
        r = self.client.post(reverse('profile'), {'name': 'Asha K'})
        self.assertEqual(r.status_code, 302)
        self.player.profile.refresh_from_db()
        self.assertFalse(self.player.profile.is_available_for_alerts)  # box left unticked
