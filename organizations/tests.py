from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from .models import Organization, OrganizationMembership
from .permissions import get_authorized_organization, user_can_manage_org, user_can_edit_event


class OrganizationModelTests(TestCase):

    def test_slug_auto_generated(self):
        org = Organization.objects.create(name='Test Org')
        self.assertEqual(org.slug, 'test-org')

    def test_slug_unique(self):
        Organization.objects.create(name='Alpha', slug='alpha')
        with self.assertRaises(Exception):
            Organization.objects.create(name='Alpha Duplicate', slug='alpha')

    def test_str(self):
        org = Organization(name='My Org', slug='my-org')
        self.assertEqual(str(org), 'My Org')


class MembershipModelTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('alice', password='pass')
        self.org = Organization.objects.create(name='Org A', slug='org-a')

    def test_membership_creation(self):
        m = OrganizationMembership.objects.create(
            user=self.user, organization=self.org, role=OrganizationMembership.Role.ADMIN
        )
        self.assertEqual(m.role, OrganizationMembership.Role.ADMIN)

    def test_membership_unique_per_user_org(self):
        OrganizationMembership.objects.create(user=self.user, organization=self.org)
        with self.assertRaises(Exception):
            OrganizationMembership.objects.create(user=self.user, organization=self.org)

    def test_user_can_belong_to_multiple_orgs(self):
        org_b = Organization.objects.create(name='Org B', slug='org-b')
        OrganizationMembership.objects.create(user=self.user, organization=self.org, role='admin')
        OrganizationMembership.objects.create(user=self.user, organization=org_b, role='editor')
        self.assertEqual(self.user.organization_memberships.count(), 2)

    def test_is_admin_or_above(self):
        owner = OrganizationMembership(role=OrganizationMembership.Role.OWNER)
        admin = OrganizationMembership(role=OrganizationMembership.Role.ADMIN)
        editor = OrganizationMembership(role=OrganizationMembership.Role.EDITOR)
        self.assertTrue(owner.is_admin_or_above)
        self.assertTrue(admin.is_admin_or_above)
        self.assertFalse(editor.is_admin_or_above)


class PermissionsTests(TestCase):

    def setUp(self):
        self.user_a = User.objects.create_user('user_a', password='pass')
        self.user_b = User.objects.create_user('user_b', password='pass')
        self.org_a = Organization.objects.create(name='Org A', slug='org-a')
        self.org_b = Organization.objects.create(name='Org B', slug='org-b')
        OrganizationMembership.objects.create(
            user=self.user_a, organization=self.org_a, role=OrganizationMembership.Role.ADMIN
        )

    def test_admin_can_manage_own_org(self):
        self.assertTrue(user_can_manage_org(self.user_a, self.org_a))

    def test_user_cannot_manage_other_org(self):
        self.assertFalse(user_can_manage_org(self.user_a, self.org_b))

    def test_unauthenticated_cannot_manage(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertFalse(user_can_manage_org(AnonymousUser(), self.org_a))

    def test_superuser_can_manage_any_org(self):
        superuser = User.objects.create_superuser('super', password='pass')
        self.assertTrue(user_can_manage_org(superuser, self.org_b))

    def test_get_authorized_organization_no_membership_raises_404(self):
        from django.http import Http404
        with self.assertRaises(Http404):
            get_authorized_organization(self.user_b, 'org-a')

    def test_get_authorized_organization_returns_org(self):
        org = get_authorized_organization(self.user_a, 'org-a')
        self.assertEqual(org, self.org_a)


def _make_event(organization, slug='test-event'):
    from events.models import Event
    return Event.objects.create(
        organization=organization,
        slug=slug,
        name='Test Event',
        start=timezone.now(),
        end=timezone.now(),
        transfers_enabled_until=timezone.now(),
        header_image='',
        title='Test',
        description='Test',
    )


class CrossOrgIDORTests(TestCase):
    """Tests that admin of org A cannot access or edit resources of org B."""

    def setUp(self):
        self.admin_a = User.objects.create_user('admin_a', password='pass')
        self.admin_b = User.objects.create_user('admin_b', password='pass')
        self.org_a = Organization.objects.create(name='Org A', slug='org-a')
        self.org_b = Organization.objects.create(name='Org B', slug='org-b')
        OrganizationMembership.objects.create(
            user=self.admin_a, organization=self.org_a, role=OrganizationMembership.Role.ADMIN
        )
        OrganizationMembership.objects.create(
            user=self.admin_b, organization=self.org_b, role=OrganizationMembership.Role.ADMIN
        )
        self.event_a = _make_event(self.org_a, slug='event-a')
        self.event_b = _make_event(self.org_b, slug='event-b')

    def test_admin_a_can_edit_event_a(self):
        self.assertTrue(user_can_edit_event(self.admin_a, self.event_a))

    def test_admin_a_cannot_edit_event_b(self):
        self.assertFalse(user_can_edit_event(self.admin_a, self.event_b))

    def test_admin_b_cannot_edit_event_a(self):
        self.assertFalse(user_can_edit_event(self.admin_b, self.event_a))

    def test_get_authorized_organization_blocks_cross_org(self):
        from django.http import Http404
        # admin_a tries to get org_b context
        with self.assertRaises(Http404):
            get_authorized_organization(self.admin_a, 'org-b')

    def test_editor_cannot_edit_event(self):
        editor = User.objects.create_user('editor', password='pass')
        OrganizationMembership.objects.create(
            user=editor, organization=self.org_a, role=OrganizationMembership.Role.EDITOR
        )
        self.assertFalse(user_can_edit_event(editor, self.event_a))

    def test_unauthenticated_cannot_edit_any_event(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertFalse(user_can_edit_event(AnonymousUser(), self.event_a))
        self.assertFalse(user_can_edit_event(AnonymousUser(), self.event_b))


class PublicCatalogTests(TestCase):
    """Tests for public event visibility rules."""

    def setUp(self):
        self.org = Organization.objects.create(name='Org', slug='org', is_active=True)
        self.inactive_org = Organization.objects.create(name='Inactive Org', slug='inactive-org', is_active=False)

    def _make_event(self, org, slug, status, active=True):
        from events.models import Event
        return Event.objects.create(
            organization=org, slug=slug, name=slug,
            status=status, active=active,
            start=timezone.now(), end=timezone.now(),
            transfers_enabled_until=timezone.now(),
            header_image='', title='T', description='D',
        )

    def test_published_active_org_event_is_visible(self):
        from events.models import Event
        e = self._make_event(self.org, 'pub', Event.Status.PUBLISHED)
        self.assertIn(e, Event.get_active_events())

    def test_draft_event_is_not_visible(self):
        from events.models import Event
        e = self._make_event(self.org, 'draft', Event.Status.DRAFT)
        self.assertNotIn(e, Event.get_active_events())

    def test_published_inactive_org_event_is_not_visible(self):
        from events.models import Event
        e = self._make_event(self.inactive_org, 'pub-inactive', Event.Status.PUBLISHED)
        self.assertNotIn(e, Event.get_active_events())

    def test_get_by_slug_returns_published(self):
        from events.models import Event
        e = self._make_event(self.org, 'find-me', Event.Status.PUBLISHED)
        self.assertEqual(Event.get_by_slug('find-me'), e)

    def test_get_by_slug_draft_returns_none(self):
        from events.models import Event
        self._make_event(self.org, 'hidden', Event.Status.DRAFT)
        self.assertIsNone(Event.get_by_slug('hidden'))

