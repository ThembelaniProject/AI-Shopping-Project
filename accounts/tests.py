from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from accounts.models import UserProfile
from preferences.models import Preference


class TermsAcceptanceFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="99999999@dut4life.ac.za",
            email="99999999@dut4life.ac.za",
            password="TestPassword123!",
            first_name="Jane",
            last_name="Doe"
        )
        self.profile = self.user.profile
        self.profile.terms_accepted = False
        self.profile.save()

    def test_first_time_user_redirected_to_preferences(self):
        self.client.login(username=self.user.username, password="TestPassword123!")
        response = self.client.get(reverse("home"), follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("preferences:edit"))

    def test_user_with_preferences_redirected_to_accept_terms(self):
        Preference.objects.create(
            user=self.user,
            styles=["Casual"],
            colours=["Black"],
            stores=["Mr Price"],
            hobbies=["Gaming"]
        )
        self.client.login(username=self.user.username, password="TestPassword123!")

        # Dashboard should redirect to accept-terms
        response = self.client.get(reverse("shopping:dashboard"), follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("accounts:accept_terms"))

    def test_accept_terms_validation_and_success(self):
        Preference.objects.create(
            user=self.user,
            styles=["Casual"],
            colours=["Black"],
            stores=["Mr Price"],
            hobbies=["Gaming"]
        )
        self.client.login(username=self.user.username, password="TestPassword123!")

        # Missing one checkbox should fail
        response = self.client.post(
            reverse("accounts:accept_terms"),
            {"agree_terms": "1"}
        )
        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.terms_accepted)

        # Checking both should succeed
        response = self.client.post(
            reverse("accounts:accept_terms"),
            {"agree_terms": "1", "agree_privacy": "1"},
            follow=False
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("shopping:dashboard"))

        self.profile.refresh_from_db()
        self.assertTrue(self.profile.terms_accepted)
        self.assertIsNotNone(self.profile.terms_accepted_at)

        # Dashboard now accessible
        dash_response = self.client.get(reverse("shopping:dashboard"))
        self.assertEqual(dash_response.status_code, 200)

