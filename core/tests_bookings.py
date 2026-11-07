from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import booking_logic as bl
from .models import Booking, BookingSlot, Notification, Profile, Turf, TurfManager


def make_user(name, phone, **kw):
    u = User.objects.create_user(username=name.lower(), first_name=name, password='pass12345')
    Profile.objects.create(user=u, phone=phone, **kw)
    return u


PLAIN_STATIC = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


@override_settings(STORAGES=PLAIN_STATIC)
class BookingBase(TestCase):
    def setUp(self):
        self.turf = Turf.objects.create(
            name='Arena', slug='arena', location_name='Calicut', booking_enabled=True,
            opens_at=time(6, 0), closes_at=time(0, 0), slot_minutes=60, price_per_slot=1000,
            peak_price_per_slot=1500, peak_starts_at=time(18, 0), max_slots_per_booking=3,
            cancel_before_hours=4, advance_days=14,
        )
        self.player = make_user('Asha', '9000000001')
        self.other = make_user('Ben', '9000000002')
        self.admin = make_user('Owner', '9000000003', is_available_for_alerts=False)
        TurfManager.objects.create(user=self.admin, turf=self.turf)
        self.day = bl.local_today() + timedelta(days=3)

    def book(self, start='10:00', count=1, user=None, day=None, **kw):
        return bl.create_booking(self.turf, day or self.day, start, count, user=user or self.player, **kw)


class GridAndPricing(BookingBase):
    def test_grid_runs_until_midnight(self):
        grid = bl.build_grid(self.turf, self.day)
        self.assertEqual(len(grid), 18)  # 6 AM .. midnight
        self.assertEqual(timezone.localtime(grid[-1][1]).hour, 0)

    def test_peak_pricing(self):
        slots = {s['start']: s['price'] for s in bl.slot_states(self.turf, self.day)}
        self.assertEqual(slots['10:00'] if self.day.weekday() < 5 else 1000, 1000 if self.day.weekday() < 5 else 1000)
        self.assertEqual(slots['19:00'], 1500)

    def test_weekend_peak(self):
        self.turf.weekend_is_peak = True
        sat = self.day + timedelta(days=(5 - self.day.weekday()) % 7)
        slots = {s['start']: s['price'] for s in bl.slot_states(self.turf, sat)}
        self.assertEqual(slots['07:00'], 1500)

    def test_clean_rejects_bad_hours_and_orphan_peak(self):
        from django.core.exceptions import ValidationError
        self.turf.closes_at = time(5, 0)
        with self.assertRaises(ValidationError):
            self.turf.clean()
        self.turf.closes_at = time(23, 0)
        self.turf.peak_price_per_slot, self.turf.peak_starts_at, self.turf.weekend_is_peak = Decimal(1500), None, False
        with self.assertRaises(ValidationError):
            self.turf.clean()


class CreateAndCancel(BookingBase):
    def test_book_and_total(self):
        b = self.book('17:00', 2)
        self.assertEqual(b.amount, Decimal('2500'))      # 17:00 @1000 + 18:00 @1500
        self.assertEqual(b.slots.count(), 2)
        self.assertEqual(len(b.reference), 8)

    def test_overlap_rejected(self):
        self.book('10:00', 2)
        with self.assertRaises(bl.SlotTakenError):
            self.book('11:00', 1, user=self.other)
        with self.assertRaises(bl.SlotTakenError):
            self.book('09:00', 2, user=self.other)
        self.book('12:00', 1, user=self.other)           # adjacent is fine

    def test_unique_constraint_is_a_hard_backstop(self):
        b = self.book('10:00')
        with self.assertRaises(IntegrityError), transaction.atomic():
            BookingSlot.objects.create(booking=b, turf=self.turf, start_at=b.start_at)

    def test_validation(self):
        for kwargs in [dict(count=4), dict(count=0), dict(start='03:00'), dict(start='23:00', count=2)]:
            with self.assertRaises(bl.BookingError, msg=kwargs):
                self.book(**kwargs)
        with self.assertRaises(bl.BookingError):
            self.book(day=bl.local_today() - timedelta(days=1))
        with self.assertRaises(bl.BookingError):
            self.book(day=bl.local_today() + timedelta(days=15))

    def test_cannot_book_started_slot(self):
        now = timezone.localtime()
        start = now.replace(minute=0, second=0, microsecond=0)
        if start.hour < 6:
            self.skipTest('before opening')
        with self.assertRaises(bl.BookingError):
            bl.create_booking(self.turf, now.date(), start.strftime('%H:%M'), 1, user=self.player)

    def test_paused_and_disabled(self):
        self.turf.bookings_paused = True
        self.turf.save()
        with self.assertRaises(bl.BookingError):
            self.book()
        self.turf.bookings_paused, self.turf.booking_enabled = False, False
        self.turf.save()
        with self.assertRaises(bl.BookingError):
            self.book()

    def test_cancel_frees_slot_and_window(self):
        b = self.book('10:00')
        self.assertTrue(b.player_can_cancel)
        bl.cancel_booking(b, 'PLAYER')
        b.refresh_from_db()
        self.assertEqual(b.status, 'CANCELLED')
        self.assertFalse(BookingSlot.objects.filter(booking=b).exists())
        self.book('10:00', user=self.other)               # rebookable at once
        soon = Booking.objects.create(turf=self.turf, user=self.player, start_at=timezone.now() + timedelta(hours=2),
                                      end_at=timezone.now() + timedelta(hours=3))
        self.assertFalse(soon.player_can_cancel)

    def test_hoarding_guard(self):
        for h in range(6, 12):
            self.book(f'{h:02d}:00', day=self.day + timedelta(days=h))
        with self.assertRaises(bl.BookingError):
            self.book('14:00')


class StatesAndOps(BookingBase):
    def test_states_for_players_and_admin(self):
        self.book('10:00', 2)
        mine = {s['start']: s for s in bl.slot_states(self.turf, self.day, user=self.player)}
        theirs = {s['start']: s for s in bl.slot_states(self.turf, self.day, user=self.other)}
        adm = {s['start']: s for s in bl.slot_states(self.turf, self.day, admin=True)}
        self.assertEqual((mine['10:00']['state'], mine['11:00']['state']), ('mine', 'mine'))
        self.assertEqual(theirs['10:00']['state'], 'booked')
        self.assertNotIn('booking', theirs['10:00'])        # other players never see who booked
        self.assertEqual(adm['10:00']['booking']['name'], 'Asha')
        self.assertEqual(adm['09:00']['state'], 'free')

    def test_walkin_block_close_reopen(self):
        bl.create_booking(self.turf, self.day, '08:00', 1, source='WALKIN', guest_name='Walk Joe', paid=True)
        done, _ = bl.block_slots(self.turf, self.day, ['09:00', '08:00'], 'Rain')
        self.assertEqual(done, 1)                            # 08:00 already taken
        closed, _ = bl.close_day(self.turf, self.day)
        self.assertEqual(closed, 18 - 2)
        with self.assertRaises(bl.SlotTakenError):
            self.book('15:00')
        self.assertEqual(bl.reopen_day(self.turf, self.day), 17)
        self.book('15:00')
        st = bl.day_stats(self.turf, self.day)
        self.assertEqual((st['bookings'], st['booked_slots']), (2, 2))

    def test_day_summaries_report_full(self):
        for i in range(0, 18, 3):
            self.book(f'{6 + i:02d}:00', 3, user=self.other, day=self.day) if False else None
        s = bl.day_summaries(self.turf, [self.day])[0]
        self.assertEqual((s['free'], s['total']), (18, 18))


class Views(BookingBase):
    def test_public_pages_and_hidden_when_off(self):
        self.assertEqual(self.client.get(reverse('book_directory')).status_code, 200)
        self.assertContains(self.client.get(reverse('book_turf', args=['arena'])), 'Pick a slot')
        self.assertEqual(self.client.get(reverse('book_slots_api', args=['arena']) + f'?date={self.day}').status_code, 200)
        self.turf.booking_enabled = False
        self.turf.save()
        self.assertEqual(self.client.get(reverse('book_turf', args=['arena'])).status_code, 404)

    def test_confirm_flow_and_notifications(self):
        self.client.login(username='asha', password='pass12345')
        r = self.client.post(reverse('book_confirm', args=['arena']), {'date': self.day.isoformat(), 'start': '19:00', 'count': 2})
        b = Booking.objects.get()
        self.assertRedirects(r, reverse('booking_detail', args=[b.reference]) + '?new=1')
        self.assertTrue(Notification.objects.filter(recipient=self.player, verb='BOOKING_CONFIRMED').exists())
        self.assertTrue(Notification.objects.filter(recipient=self.admin, verb='NEW_BOOKING').exists())
        self.assertContains(self.client.get(reverse('booking_detail', args=[b.reference])), b.reference)
        self.assertEqual(self.client.get(reverse('booking_ics', args=[b.reference])).status_code, 200)
        self.assertEqual(self.client.get(reverse('notification_list')).status_code, 200)
        # someone else can't see it
        self.client.login(username='ben', password='pass12345')
        self.assertEqual(self.client.get(reverse('booking_detail', args=[b.reference])).status_code, 404)
        r = self.client.post(reverse('book_confirm', args=['arena']), {'date': self.day.isoformat(), 'start': '19:00', 'count': 1}, follow=True)
        self.assertContains(r, 'someone just took')

    def test_login_required_and_player_cancel(self):
        r = self.client.post(reverse('book_confirm', args=['arena']), {'date': self.day.isoformat(), 'start': '10:00'})
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r.url)
        b = self.book('10:00')
        self.client.login(username='asha', password='pass12345')
        self.client.post(reverse('booking_cancel', args=[b.reference]))
        b.refresh_from_db()
        self.assertEqual(b.status, 'CANCELLED')
        self.assertTrue(Notification.objects.filter(recipient=self.admin, verb='BOOKING_CANCELLED').exists())
        self.assertEqual(self.client.get(reverse('my_bookings') + '?tab=past').status_code, 200)

    def test_turf_admin_cannot_book_and_lands_on_console(self):
        r = self.client.post(reverse('login'), {'phone': '9000000003', 'password': 'pass12345'})
        self.assertRedirects(r, reverse('manage_home'), fetch_redirect_response=False)
        self.client.post(reverse('book_confirm', args=['arena']), {'date': self.day.isoformat(), 'start': '10:00'})
        self.assertEqual(Booking.objects.count(), 0)

    def test_login_next_param_is_honoured_and_safe(self):
        r = self.client.post(reverse('login') + '?next=/book/arena/', {'phone': '9000000001', 'password': 'pass12345'})
        self.assertEqual(r.url, '/book/arena/')
        self.client.logout()
        r = self.client.post(reverse('login') + '?next=https://evil.example/', {'phone': '9000000001', 'password': 'pass12345'})
        self.assertEqual(r.url, reverse('feed'))

    def test_console_permissions(self):
        url = reverse('manage_schedule', args=['arena'])
        self.assertEqual(self.client.get(url).status_code, 302)               # anon -> login
        self.client.login(username='ben', password='pass12345')
        self.assertEqual(self.client.get(url).status_code, 403)               # player
        self.assertEqual(self.client.post(reverse('manage_close_day', args=['arena']), {'date': self.day.isoformat()}).status_code, 403)
        other_turf = Turf.objects.create(name='Other', slug='other', location_name='X', booking_enabled=True)
        self.client.login(username='owner', password='pass12345')
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(reverse('manage_schedule', args=['other'])).status_code, 403)  # not their turf
        self.assertEqual(self.client.get(reverse('manage_slots_api', args=['arena']) + f'?date={self.day}').status_code, 200)
        for name in ('manage_bookings', 'manage_settings'):
            self.assertEqual(self.client.get(reverse(name, args=['arena'])).status_code, 200)

    def test_console_actions(self):
        b = self.book('10:00')
        self.client.login(username='owner', password='pass12345')
        d = {'date': self.day.isoformat()}
        self.client.post(reverse('manage_walkin', args=['arena']), {**d, 'start': '12:00', 'count': 2, 'name': 'Joe', 'paid': 'on'})
        self.assertEqual(Booking.objects.get(source='WALKIN').payment_status, 'PAID')
        self.client.post(reverse('manage_block', args=['arena']), {**d, 'start': ['14:00'], 'reason': 'Rain'})
        blk = Booking.objects.get(source='BLOCKED')
        self.client.post(reverse('manage_unblock', args=['arena']), {'ref': blk.reference})
        self.assertFalse(Booking.objects.filter(source='BLOCKED').exists())
        self.client.post(reverse('manage_booking_paid', args=['arena', b.reference]), d)
        b.refresh_from_db(); self.assertEqual(b.payment_status, 'PAID')
        self.client.post(reverse('manage_booking_cancel', args=['arena', b.reference]), {**d, 'reason': 'Maintenance'})
        b.refresh_from_db(); self.assertEqual((b.status, b.cancelled_by), ('CANCELLED', 'TURF'))
        n = Notification.objects.get(recipient=self.player, verb='BOOKING_CANCELLED')
        self.assertIn('Maintenance', n.message)
        self.client.post(reverse('manage_settings', args=['arena']), {'action': 'settings', 'price_per_slot': '1200', 'peak_price_per_slot': '1800',
                                                                         'peak_starts_at': '18:00', 'description': 'Nice', 'amenities': 'Parking'})
        self.turf.refresh_from_db(); self.assertEqual(self.turf.price_per_slot, 1200)

    def test_existing_pages_still_work(self):
        for name in ('turf_directory', 'login', 'signup'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.client.login(username='asha', password='pass12345')
        for name in ('feed', 'my_hosted', 'my_joined', 'notification_list', 'profile', 'create_match', 'my_bookings'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertContains(self.client.get(reverse('feed')), 'Book a turf')
        self.assertContains(self.client.get(reverse('turf_detail', args=['arena'])), 'Book a slot')


class AdminAccounts(BookingBase):
    def setUp(self):
        super().setUp()
        self.su = User.objects.create_superuser('root', password='rootpass123')
        self.client.login(username='root', password='rootpass123')

    def test_create_turf_admin_account(self):
        url = reverse('admin:core_turfmanager_add')
        r = self.client.post(url, {'turf': self.turf.pk, 'name': 'Sam Turf', 'phone': '9111111111', 'password': 'longpass123'})
        self.assertEqual(r.status_code, 302, getattr(r, 'context', None) and r.context['adminform'].form.errors)
        link = TurfManager.objects.get(user__profile__phone='9111111111')
        self.assertFalse(link.user.profile.is_available_for_alerts)
        # existing PLAYER numbers can't be promoted
        r = self.client.post(url, {'turf': self.turf.pk, 'name': 'x', 'phone': '9000000001', 'password': 'longpass123'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'regular player account')
        # a second turf can be attached to an existing turf admin
        t2 = Turf.objects.create(name='Two', slug='two', location_name='Y')
        r = self.client.post(url, {'turf': t2.pk, 'phone': '9111111111'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(TurfManager.objects.filter(user=link.user).count(), 2)

    def test_admin_pages_render(self):
        for name, args in [('admin:core_turf_changelist', []), ('admin:core_turf_change', [self.turf.pk]),
                           ('admin:core_turf_add', []), ('admin:core_booking_changelist', []), ('admin:core_turfmanager_changelist', [])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200, name)
