from django.test import TestCase


class UIAssetTests(TestCase):
    def test_bundled_assets_are_available_without_login(self):
        for filename, content_type in (
            ('app.css', 'text/css'), ('branding.css', 'text/css'),
            ('app.js', 'text/javascript'), ('catalog.js', 'text/javascript'),
        ):
            response = self.client.get('/assets/ui/' + filename)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response['Content-Type'].startswith(content_type))
            self.assertGreater(len(b''.join(response.streaming_content)), 0)
            response.close()

    def test_unknown_assets_and_mutations_are_rejected(self):
        self.assertEqual(self.client.get('/assets/ui/secrets.json').status_code, 404)
        self.assertEqual(self.client.post('/assets/ui/app.js').status_code, 405)
