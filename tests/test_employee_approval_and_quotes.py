import unittest

from backend.app import create_app
from backend.models.payroll import db
from backend.routes.auth import UserAccount
from backend.routes.portal import ShipmentFinance
from backend.routes.shipments import Shipment


class EmployeeApprovalAndQuoteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SECRET_KEY': 'local-test-secret-key-for-jwt-signing',
            'JWT_SECRET_KEY': 'local-test-secret-key-for-jwt-signing',
        })
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()
        self.hr = self.create_user('hr@example.test', 'hr', 'Human Resources')
        self.client_user = self.create_user('client@example.test', 'client', 'Example Client')
        self.accountant = self.create_user('accounts@example.test', 'accountant', 'Accounts')

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.app_context.pop()

    def create_user(self, email, role, display_name):
        user = UserAccount(
            company_name='Difan Logistics' if role != 'client' else 'Example Client Ltd',
            email=email,
            role=role,
            display_name=display_name,
            account_status='active',
        )
        user.set_password('LongTestPassword123')
        db.session.add(user)
        db.session.commit()
        return user

    def login_headers(self, email, role):
        response = self.client.post('/api/auth/login', json={
            'email': email,
            'password': 'LongTestPassword123',
            'role': role,
        })
        self.assertEqual(response.status_code, 200)
        return {'Authorization': f"Bearer {response.json['token']}"}

    def test_privileged_employee_roles_require_hr_approval(self):
        headers = self.login_headers('hr@example.test', 'hr')
        for role in ('admin', 'accountant', 'hr'):
            with self.subTest(role=role):
                email = f'{role}-employee@example.test'
                response = self.client.post('/api/auth/register/employee', json={
                    'display_name': f'{role.title()} Employee',
                    'email': email,
                    'password': 'LongEmployeePassword123',
                    'role': role,
                })
                self.assertEqual(response.status_code, 201)

                login = self.client.post('/api/auth/login', json={
                    'email': email,
                    'password': 'LongEmployeePassword123',
                    'role': role,
                })
                self.assertEqual(login.status_code, 403)
                self.assertIn('awaiting HR approval', login.json['message'])

                registrations = self.client.get(
                    '/api/auth/employee-registrations',
                    headers=headers,
                )
                pending = next(
                    row for row in registrations.json['registrations']
                    if row['email'] == email
                )
                approved = self.client.patch(
                    f"/api/auth/employee-registrations/{pending['id']}/approve",
                    headers=headers,
                )
                self.assertEqual(approved.status_code, 200)
                self.assertEqual(approved.json['user']['role'], role)

                active_login = self.client.post('/api/auth/login', json={
                    'email': email,
                    'password': 'LongEmployeePassword123',
                    'role': role,
                })
                self.assertEqual(active_login.status_code, 200)

    def test_employee_registration_requires_hr_approval_before_login(self):
        response = self.client.post('/api/auth/register/employee', json={
            'display_name': 'Alex Driver',
            'email': 'alex@example.test',
            'password': 'LongEmployeePassword123',
            'role': 'driver',
        })
        self.assertEqual(response.status_code, 201)

        pending_login = self.client.post('/api/auth/login', json={
            'email': 'alex@example.test',
            'password': 'LongEmployeePassword123',
            'role': 'driver',
        })
        self.assertEqual(pending_login.status_code, 403)
        self.assertIn('awaiting HR approval', pending_login.json['message'])

        headers = self.login_headers('hr@example.test', 'hr')
        client_headers = self.login_headers('client@example.test', 'client')
        self.assertEqual(
            self.client.get('/api/auth/employee-registrations', headers=client_headers).status_code,
            403,
        )
        registrations = self.client.get('/api/auth/employee-registrations', headers=headers)
        self.assertEqual(registrations.status_code, 200)
        pending = registrations.json['registrations']
        self.assertEqual([row['email'] for row in pending], ['alex@example.test'])

        approved = self.client.patch(
            f"/api/auth/employee-registrations/{pending[0]['id']}/approve",
            headers=headers,
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json['user']['account_status'], 'active')
        employee_login = self.client.post('/api/auth/login', json={
            'email': 'alex@example.test',
            'password': 'LongEmployeePassword123',
            'role': 'driver',
        })
        self.assertEqual(employee_login.status_code, 200)

    def test_hr_has_admin_shipment_visibility_but_clients_remain_scoped(self):
        hr_headers = self.login_headers('hr@example.test', 'hr')
        client_headers = self.login_headers('client@example.test', 'client')

        hr_shipments = self.client.get('/api/shipments', headers=hr_headers)
        client_shipments = self.client.get('/api/shipments', headers=client_headers)

        self.assertEqual(hr_shipments.status_code, 200)
        self.assertIn('DL-8801', [row['tracking_number'] for row in hr_shipments.json['shipments']])
        self.assertEqual(client_shipments.status_code, 200)
        self.assertEqual(client_shipments.json['shipments'], [])

    def test_container_quote_reports_exclusive_vat_and_inclusive_total(self):
        hr_headers = self.login_headers('hr@example.test', 'hr')
        client_headers = self.login_headers('client@example.test', 'client')

        rates = self.client.put('/api/portal/container-rates', headers=hr_headers, json={
            'rates': {'20ft': 100, '40ft': 200},
        })
        self.assertEqual(rates.status_code, 200)

        quote = self.client.post('/api/portal/container-quote', headers=client_headers, json={
            'size': '20ft',
            'quantity': 2,
        })
        self.assertEqual(quote.status_code, 200)
        self.assertEqual(quote.json['quote']['total_kes'], 200)
        self.assertEqual(quote.json['quote']['vat_amount_kes'], 32)
        self.assertEqual(quote.json['quote']['total_including_vat_kes'], 232)

    def test_accountant_tracks_paid_and_outstanding_delivery_balances(self):
        accountant_headers = self.login_headers('accounts@example.test', 'accountant')
        client_headers = self.login_headers('client@example.test', 'client')
        self.create_user('driver@example.test', 'driver', 'Delivery Driver')
        driver_headers = self.login_headers('driver@example.test', 'driver')
        shipment = db.session.get(Shipment, 'DL-8801')
        shipment.company_name = 'Example Client Ltd'
        db.session.commit()

        finance = self.client.get('/api/portal/delivery-finance', headers=accountant_headers)
        self.assertEqual(finance.status_code, 200)
        self.assertTrue(finance.json['can_update'])
        self.assertEqual(finance.json['deliveries'][0]['payment_status'], 'not_invoiced')

        updated = self.client.patch(
            '/api/portal/delivery-finance/DL-8801',
            headers=accountant_headers,
            json={'invoice_amount_kes': 1500, 'paid_amount_kes': 500},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json['delivery']['payment_status'], 'partially_paid')
        self.assertEqual(updated.json['delivery']['balance_kes'], 1000)

        marked_paid = self.client.patch(
            '/api/portal/delivery-finance/DL-8801',
            headers=accountant_headers,
            json={'invoice_amount_kes': 1500, 'paid_amount_kes': 500, 'mark_paid': True},
        )
        self.assertEqual(marked_paid.status_code, 200)
        self.assertEqual(marked_paid.json['delivery']['payment_status'], 'paid')
        self.assertEqual(marked_paid.json['delivery']['paid_amount_kes'], 1500)
        self.assertEqual(marked_paid.json['delivery']['balance_kes'], 0)

        client_finance = self.client.get('/api/portal/delivery-finance', headers=client_headers)
        self.assertEqual(client_finance.status_code, 200)
        self.assertFalse(client_finance.json['can_update'])
        self.assertEqual(
            [row['tracking_number'] for row in client_finance.json['deliveries']],
            ['DL-8801'],
        )
        self.assertEqual(
            self.client.patch(
                '/api/portal/delivery-finance/DL-8801',
                headers=client_headers,
                json={'invoice_amount_kes': 1500, 'paid_amount_kes': 0},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get('/api/portal/delivery-finance', headers=driver_headers).status_code,
            403,
        )
        self.assertIsNotNone(
            db.session.get(ShipmentFinance, 'DL-8801').updated_by_id,
        )

    def test_delivery_finance_rejects_invalid_payment_amounts(self):
        accountant_headers = self.login_headers('accounts@example.test', 'accountant')
        for payload in (
            {'invoice_amount_kes': -1, 'paid_amount_kes': 0},
            {'invoice_amount_kes': 100, 'paid_amount_kes': 101},
            {'invoice_amount_kes': 'not money', 'paid_amount_kes': 0},
        ):
            with self.subTest(payload=payload):
                response = self.client.patch(
                    '/api/portal/delivery-finance/DL-8801',
                    headers=accountant_headers,
                    json=payload,
                )
                self.assertEqual(response.status_code, 400)

    def test_client_notices_are_published_by_staff_and_visible_to_clients_only(self):
        hr_headers = self.login_headers('hr@example.test', 'hr')
        client_headers = self.login_headers('client@example.test', 'client')
        self.create_user('driver@example.test', 'driver', 'Delivery Driver')
        driver_headers = self.login_headers('driver@example.test', 'driver')

        created = self.client.post('/api/portal/client-notices', headers=hr_headers, json={
            'title': 'Holiday service hours',
            'body': 'Our support desk will close early on Friday.',
        })
        self.assertEqual(created.status_code, 201)

        notices = self.client.get('/api/portal/client-notices', headers=client_headers)
        self.assertEqual(notices.status_code, 200)
        self.assertEqual(notices.json['notices'][0]['title'], 'Holiday service hours')
        self.assertEqual(
            self.client.get('/api/portal/client-notices', headers=driver_headers).status_code,
            403,
        )
        self.assertEqual(
            self.client.post('/api/portal/client-notices', headers=client_headers, json={
                'title': 'Unapproved post',
                'body': 'Clients cannot publish company-wide notices.',
            }).status_code,
            403,
        )

    def test_client_direct_messages_are_limited_to_admin_hr_accounts(self):
        admin = self.create_user('admin@example.test', 'admin', 'Operations Admin')
        other_client = self.create_user('another-client@example.test', 'client', 'Another Client')
        client_headers = self.login_headers('client@example.test', 'client')
        other_client_headers = self.login_headers('another-client@example.test', 'client')
        hr_headers = self.login_headers('hr@example.test', 'hr')
        admin_headers = self.login_headers('admin@example.test', 'admin')
        accountant_headers = self.login_headers('accounts@example.test', 'accountant')

        contacts = self.client.get('/api/portal/client-conversations', headers=client_headers)
        self.assertEqual(contacts.status_code, 200)
        self.assertEqual(
            {contact['role'] for contact in contacts.json['contacts']},
            {'admin', 'hr', 'accountant'},
        )

        driver = self.create_user('driver@example.test', 'driver', 'Delivery Driver')
        invalid_start = self.client.post('/api/portal/client-conversations', headers=client_headers, json={
            'staff_user_id': driver.id,
        })
        self.assertEqual(invalid_start.status_code, 400)

        started = self.client.post('/api/portal/client-conversations', headers=client_headers, json={
            'staff_user_id': self.hr.id,
        })
        self.assertEqual(started.status_code, 201)
        conversation_id = started.json['conversation']['id']

        sent = self.client.post(
            f'/api/portal/client-conversations/{conversation_id}/messages',
            headers=client_headers,
            json={'body': 'Please confirm the next delivery window.'},
        )
        self.assertEqual(sent.status_code, 201)

        inbox = self.client.get('/api/portal/client-conversations', headers=hr_headers)
        self.assertEqual(inbox.status_code, 200)
        self.assertEqual([row['id'] for row in inbox.json['conversations']], [conversation_id])
        reply = self.client.post(
            f'/api/portal/client-conversations/{conversation_id}/messages',
            headers=hr_headers,
            json={'body': 'The delivery window is confirmed.'},
        )
        self.assertEqual(reply.status_code, 201)

        thread = self.client.get(
            f'/api/portal/client-conversations/{conversation_id}/messages',
            headers=client_headers,
        )
        self.assertEqual(thread.status_code, 200)
        self.assertEqual(len(thread.json['messages']), 2)
        self.assertEqual(
            self.client.get(
                f'/api/portal/client-conversations/{conversation_id}/messages',
                headers=other_client_headers,
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                f'/api/portal/client-conversations/{conversation_id}/messages',
                headers=admin_headers,
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get('/api/portal/client-conversations', headers=accountant_headers).status_code,
            200,
        )


if __name__ == '__main__':
    unittest.main()
