import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
import json
from app import app
from flask import session

class TestRouteProtection(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True
        app.config['SECRET_KEY'] = 'test_secret_key'

    def test_index_redirect_without_login(self):
        # Access index without session -> should redirect to login
        response = self.app.get('/', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        # Check for login form ID which is stable
        self.assertIn(b'id="loginForm"', response.data)

    def test_login_and_access_index(self):
        # Login first
        with self.app as c:
            response_login = c.post('/api/login', 
                                    data=json.dumps({"username": "admin", "password": "admin"}),
                                    content_type='application/json')
            self.assertEqual(response_login.status_code, 200)
            
            # Now access index -> should be 200 and show index.html content
            response_index = c.get('/')
            self.assertEqual(response_index.status_code, 200)
            # Check for logout link we just added
            self.assertIn(b'/logout', response_index.data)

    def test_login_page_redirect_if_logged_in(self):
        # Login first
        with self.app as c:
            c.post('/api/login', 
                   data=json.dumps({"username": "admin", "password": "admin"}),
                   content_type='application/json')
            
            # Access /login -> should redirect to /
            response = c.get('/login', follow_redirects=False)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.location.endswith('/'))

if __name__ == '__main__':
    unittest.main()
