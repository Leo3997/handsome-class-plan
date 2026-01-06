import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
import json
from app import app
from flask import Flask

class TestLogin(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_login_page_load(self):
        response = self.app.get('/login')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<!DOCTYPE html>', response.data)

    def test_api_login_success(self):
        payload = {"username": "admin", "password": "admin"}
        response = self.app.post('/api/login', 
                                 data=json.dumps(payload),
                                 content_type='application/json')
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['status'], 'success')

    def test_api_login_failure(self):
        payload = {"username": "admin", "password": "wrongpassword"}
        response = self.app.post('/api/login', 
                                 data=json.dumps(payload),
                                 content_type='application/json')
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(data['status'], 'error')

if __name__ == '__main__':
    unittest.main()
