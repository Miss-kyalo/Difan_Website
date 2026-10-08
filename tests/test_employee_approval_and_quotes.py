import base64
import hashlib
import io
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from types import SimpleNamespace
from zipfile import ZipFile

from PIL import Image, ImageDraw
import pymupdf as fitz

from backend.app import create_app
from backend.models.payroll import db
from backend.routes.auth import UserAccount, ensure_main_accounts
from backend.routes.fleet import FleetVehicle, SparePart
from backend.routes.portal import PayrollSlip, ShipmentFinance
from backend.routes.shipments import Shipment, ShipmentProofOfDelivery
from backend.routes.workforce import WorkforceCase


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

    def test_self_registration_is_disabled_for_clients_and_employees(self):
        client_registration = self.client.post('/api/auth/register', json={
            'company_name': 'Example Client',
            'email': 'new-client@example.test',
            'password': 'LongEmployeePassword123',
        })
        employee_registration = self.client.post('/api/auth/register/employee', json={
            'display_name': 'New Employee',
            'email': 'new-employee@example.test',
            'password': 'LongEmployeePassword123',
            'role': 'driver',
        })
        self.assertEqual(client_registration.status_code, 403)
        self.assertEqual(employee_registration.status_code, 403)
        self.assertIsNone(UserAccount.query.filter_by(email='new-client@example.test').first())
        self.assertIsNone(UserAccount.query.filter_by(email='new-employee@example.test').first())

    def test_hr_onboarding_emails_temporary_password_and_requires_reset(self):
        headers = self.login_headers('hr@example.test', 'hr')
        self.app.config.update({
            'SENDGRID_API_KEY': 'test-sendgrid-key',
            'MAIL_FROM_EMAIL': 'no-reply@example.test',
        })
        with patch(
            'backend.routes.auth.httpx.post',
            return_value=SimpleNamespace(status_code=202),
        ) as send_email:
            response = self.client.post('/api/auth/users', headers=headers, json={
                'company_name': 'Example Client Ltd',
                'email': 'new-client@example.test',
                'role': 'client',
                'display_name': '',
            })

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json['user']['must_change_password'])
        self.assertNotIn('password', response.json)
        email_payload = send_email.call_args.kwargs['json']
        self.assertEqual(email_payload['personalizations'][0]['to'][0]['email'], 'new-client@example.test')
        temporary_password = email_payload['content'][0]['value'].split('Temporary password: ')[1].splitlines()[0]

        login = self.client.post('/api/auth/login', json={
            'email': 'new-client@example.test',
            'password': temporary_password,
            'role': 'client',
        })
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.json['user']['must_change_password'])
        temporary_headers = {'Authorization': f"Bearer {login.json['token']}"}
        self.assertEqual(self.client.get('/api/auth/me', headers=temporary_headers).status_code, 403)

        changed = self.client.post('/api/auth/change-password', headers=temporary_headers, json={
            'password': 'NewSecurePassword123!',
        })
        self.assertEqual(changed.status_code, 200)
        self.assertFalse(changed.json['user']['must_change_password'])
        self.assertEqual(self.client.get(
            '/api/auth/me',
            headers={'Authorization': f"Bearer {changed.json['token']}"},
        ).status_code, 200)

    def test_only_hr_and_boss_can_onboard_accounts(self):
        client_headers = self.login_headers('client@example.test', 'client')
        response = self.client.post('/api/auth/users', headers=client_headers, json={
            'company_name': 'Unauthorized Ltd',
            'email': 'unauthorized@example.test',
            'role': 'client',
        })
        self.assertEqual(response.status_code, 403)

    def test_only_boss_can_view_anonymous_reports_and_attachments(self):
        self.assertEqual(self.client.post(
            '/api/portal/anonymous-reports',
            data={'description': 'Confidential concern'},
        ).status_code, 201)

        self.create_user('boss@example.test', 'boss', 'Boss')
        hr_headers = self.login_headers('hr@example.test', 'hr')
        boss_headers = self.login_headers('boss@example.test', 'boss')

        hr_response = self.client.get('/api/portal/anonymous-reports', headers=hr_headers)
        self.assertEqual(hr_response.status_code, 403)
        self.assertIn('Only the Boss', hr_response.json['message'])
        hr_attachment_response = self.client.get(
            '/api/portal/anonymous-reports/1/attachments/not-an-attachment',
            headers=hr_headers,
        )
        self.assertEqual(hr_attachment_response.status_code, 403)

        boss_response = self.client.get('/api/portal/anonymous-reports', headers=boss_headers)
        self.assertEqual(boss_response.status_code, 200)
        self.assertEqual(len(boss_response.json['reports']), 1)
        self.assertEqual(boss_response.json['reports'][0]['description'], 'Confidential concern')
        boss_attachment_response = self.client.get(
            '/api/portal/anonymous-reports/1/attachments/not-an-attachment',
            headers=boss_headers,
        )
        self.assertEqual(boss_attachment_response.status_code, 404)

    def test_client_can_request_a_truck_with_destination_and_schedule_details(self):
        client_headers = self.login_headers('client@example.test', 'client')
        pickup_at = datetime.now(timezone.utc) + timedelta(days=2)
        response = self.client.post('/api/shipments/requests', headers=client_headers, json={
            'origin': 'Athi River Industrial Zone',
            'destination': 'Kisumu Central Warehouse',
            'truck_type': '15_TON',
            'cargo_type': 'Packaged goods',
            'tonnage': 12,
            'pickup_address': 'Manufacturer loading bay, Athi River',
            'pickup_at': pickup_at.isoformat(),
            'end_customer_name': 'Kisumu Market',
            'end_customer_phone': '+254700000000',
            'end_customer_address': 'Warehouse 5, Kisumu',
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json['shipment']['status'], 'REQUESTED')
        self.assertEqual(response.json['shipment']['company_name'], 'Example Client Ltd')
        self.assertEqual(response.json['shipment']['client_user_id'], self.client_user.id)
        self.assertEqual(response.json['shipment']['end_customer_name'], 'Kisumu Market')
        self.assertEqual(response.json['shipment']['truck_type'], '15_TON')
        self.assertGreater(response.json['quote']['total_kes'], 0)

    def test_driver_selects_load_client_and_client_sees_only_its_transit_goods(self):
        driver = self.create_user('driver@example.test', 'driver', 'Delivery Driver')
        other_client = self.create_user('other-client@example.test', 'client', 'Other Client')
        other_client.company_name = 'Other Client Ltd'
        db.session.commit()
        shipment = Shipment(
            tracking_number='DL-CLIENT-LOAD-01',
            status='AWAITING_DISPATCH',
            origin='Athi River Industrial Zone',
            destination='Kisumu Central Warehouse',
            cargo_type='Steel coils',
            tonnage=8,
            assigned_driver_id=driver.id,
        )
        other_shipment = Shipment(
            tracking_number='DL-CLIENT-LOAD-02',
            status='IN_TRANSIT',
            origin='Athi River Industrial Zone',
            destination='Mombasa Port Terminal',
            cargo_type='Cement',
            tonnage=10,
            company_name=other_client.company_name,
            client_user_id=other_client.id,
        )
        db.session.add_all([shipment, other_shipment])
        db.session.commit()

        driver_headers = self.login_headers('driver@example.test', 'driver')
        available_clients = self.client.get('/api/shipments/clients', headers=driver_headers)
        self.assertEqual(available_clients.status_code, 200)
        self.assertIn(self.client_user.id, [account['id'] for account in available_clients.json['clients']])

        started = self.client.patch(
            '/api/shipments/DL-CLIENT-LOAD-01/status',
            headers=driver_headers,
            json={'status': 'IN_TRANSIT', 'client_user_id': self.client_user.id},
        )
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.json['shipment']['client_user_id'], self.client_user.id)
        self.assertEqual(started.json['shipment']['company_name'], self.client_user.company_name)

        client_headers = self.login_headers('client@example.test', 'client')
        visible = self.client.get('/api/shipments', headers=client_headers)
        tracking_numbers = [row['tracking_number'] for row in visible.json['shipments']]
        self.assertIn('DL-CLIENT-LOAD-01', tracking_numbers)
        self.assertNotIn('DL-CLIENT-LOAD-02', tracking_numbers)

        other_headers = self.login_headers('other-client@example.test', 'client')
        other_visible = self.client.get('/api/shipments', headers=other_headers)
        self.assertEqual(
            [row['tracking_number'] for row in other_visible.json['shipments']],
            ['DL-CLIENT-LOAD-02'],
        )

    def test_destination_rate_import_is_reviewed_and_used_for_quotes(self):
        hr_headers = self.login_headers('hr@example.test', 'hr')
        client_headers = self.login_headers('client@example.test', 'client')
        workbook = io.BytesIO()
        with ZipFile(workbook, 'w') as archive:
            archive.writestr(
                'xl/workbook.xml',
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="Rates" sheetId="1" r:id="rId1"/></sheets></workbook>',
            )
            archive.writestr(
                'xl/_rels/workbook.xml.rels',
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Target="worksheets/sheet1.xml" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>'
                '</Relationships>',
            )
            cells = [
                ('A1', 'origin'), ('B1', 'destination'), ('C1', 'truck_type'), ('D1', 'flat_rate_kes'),
                ('A2', 'Athi River Industrial Zone'), ('B2', 'Mombasa Port Terminal'),
                ('C2', '15_TON'), ('D2', '54000'),
            ]
            cell_xml = []
            for reference, value in cells:
                if reference == 'D2':
                    cell_xml.append(f'<c r="{reference}"><v>{value}</v></c>')
                else:
                    cell_xml.append(
                        f'<c r="{reference}" t="inlineStr"><is><t>{value}</t></is></c>'
                    )
            archive.writestr(
                'xl/worksheets/sheet1.xml',
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'<sheetData><row r="1">{"".join(cell_xml[:4])}</row>'
                f'<row r="2">{"".join(cell_xml[4:])}</row></sheetData></worksheet>',
            )
        preview = self.client.post(
            '/api/shipments/rates/preview',
            headers=hr_headers,
            data={'file': (io.BytesIO(workbook.getvalue()), 'client-rates.xlsx')},
            content_type='multipart/form-data',
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json['valid_rows'], 1)
        self.assertEqual(preview.json['rows'][0]['flat_rate_kes'], 54000)

        imported = self.client.post('/api/shipments/rates', headers=hr_headers, json={
            'source_filename': 'client-rates.xlsx',
            'rows': [{
                'origin': 'Athi River Industrial Zone',
                'destination': 'Mombasa Port Terminal',
                'truck_type': '15_TON',
                'flat_rate_kes': 54000,
                'valid': True,
                'errors': [],
            }],
        })
        self.assertEqual(imported.status_code, 201)
        self.assertEqual(imported.json['rates'][0]['flat_rate_kes'], 54000)

        quote = self.client.post('/api/shipments/quote', headers=client_headers, json={
            'origin': 'Athi River Industrial Zone',
            'destination': 'Mombasa Port Terminal',
            'truck_type': '15_TON',
            'tonnage': 10,
        })
        self.assertEqual(quote.status_code, 200)
        self.assertEqual(quote.json['quote']['subtotal_kes'], 54000)
        self.assertEqual(quote.json['quote']['pricing_source'], 'uploaded_destination_rate')
        self.assertEqual(quote.json['quote']['total_kes'], 62640)

        invalid = self.client.post('/api/shipments/rates', headers=hr_headers, json={
            'source_filename': 'invalid.xlsx',
            'rows': [{
                'origin': 'Unknown',
                'destination': 'Mombasa Port Terminal',
                'truck_type': '15_TON',
                'flat_rate_kes': 54000,
            }],
        })
        self.assertEqual(invalid.status_code, 400)

    def test_fleet_incident_and_spare_usage_capture_stock_and_service_due(self):
        hr_headers = self.login_headers('hr@example.test', 'hr')
        vehicle_response = self.client.post('/api/fleet/vehicles', headers=hr_headers, json={
            'registration': 'KDA 482P',
            'truck_type': '15_TON',
            'current_odometer_km': 50000,
        })
        self.assertEqual(vehicle_response.status_code, 201)
        vehicle = vehicle_response.json['vehicle']

        spare_response = self.client.post('/api/fleet/spares', headers=hr_headers, json={
            'part_number': 'FILTER-001',
            'name': 'Engine oil filter',
            'service_interval_km': 10000,
            'stock_quantity': 2,
            'reorder_level': 1,
        })
        self.assertEqual(spare_response.status_code, 201)
        spare_id = spare_response.json['spare']['id']
        usage = self.client.post(
            f"/api/fleet/vehicles/{vehicle['registration']}/spare-changes",
            headers=hr_headers,
            json={
                'spare_part_id': spare_id,
                'quantity': 1,
                'changed_at_odometer': 50000,
                'replaced_by': 'Workshop mechanic',
                'notes': 'Routine service',
            },
        )
        self.assertEqual(usage.status_code, 201)
        self.assertEqual(usage.json['vehicle']['parts_due'][0]['status'], 'OK')
        self.assertEqual(db.session.get(SparePart, spare_id).stock_quantity, 1)

        incident = self.client.post(
            '/api/fleet/vehicles/KDA%20482P/breakdowns',
            headers=hr_headers,
            json={
                'incident_date': datetime.now(timezone.utc).date().isoformat(),
                'severity': 'HIGH',
                'location': 'Athi River',
                'odometer_km': 51000,
                'symptoms': 'Engine overheating',
                'findings': 'Coolant leak at hose',
                'action_taken': 'Vehicle stopped for repair',
                'parts_used': 'Coolant hose',
            },
        )
        self.assertEqual(incident.status_code, 201)
        self.assertEqual(incident.json['breakdown']['symptoms'], 'Engine overheating')
        self.assertEqual(incident.json['breakdown']['odometer_km'], 51000)
        saved_vehicle = db.session.get(FleetVehicle, vehicle['id'])
        self.assertEqual(saved_vehicle.to_dict()['breakdowns_last_12_months'], 1)

    def test_p9_download_requires_complete_explicit_monthly_tax_values(self):
        employee = self.create_user('driver@example.test', 'driver', 'Delivery Driver')
        employee_headers = self.login_headers('driver@example.test', 'driver')
        now = datetime.now(timezone.utc)
        months = list(range(1, now.month + 1))

        def create_slip(month):
            db.session.add(PayrollSlip(
                employee_id=employee.id,
                pay_period=f'{now.year}-{month:02}',
                basic_pay=50000,
                allowances=5000,
                bonus=0,
                deductions=10000,
                salary_advance=0,
                nssf_deduction=3000,
                shif_deduction=1500,
                housing_levy_deduction=750,
                taxable_pay=52000,
                tax_charged=7800,
                personal_relief=2400,
                other_reliefs=0,
                paye_tax=5400,
                gross_pay=55000,
                net_pay=45000,
                status='APPROVED',
                created_by_id=self.hr.id,
            ))
            db.session.commit()

        for month in months[:-1]:
            create_slip(month)
        incomplete = self.client.get(
            f'/api/portal/payroll/p9/{now.year}',
            headers=employee_headers,
        )
        self.assertEqual(incomplete.status_code, 409)
        self.assertIn('missing', incomplete.json['message'].lower())

        create_slip(months[-1])
        history = self.client.get(
            f'/api/portal/payroll?year={now.year}',
            headers=employee_headers,
        )
        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.json['slips']), now.month)
        p9 = self.client.get(
            f'/api/portal/payroll/p9/{now.year}',
            headers=employee_headers,
        )
        self.assertEqual(p9.status_code, 200)
        self.assertTrue(p9.data.startswith(b'%PDF-'))
        pdf = fitz.open(stream=p9.data, filetype='pdf')
        self.assertIn('P9 ANNUAL TAX SUMMARY', pdf[0].get_text())
        self.assertIn('no tax values were estimated', pdf[0].get_text().lower())

    def test_dispatch_delivery_signature_generates_signed_pod_and_invoice(self):
        boss = self.create_user('boss@example.test', 'boss', 'Difan Boss')
        driver = self.create_user('driver@example.test', 'driver', 'Delivery Driver')
        client_headers = self.login_headers('client@example.test', 'client')
        driver_headers = self.login_headers('driver@example.test', 'driver')
        boss_headers = self.login_headers('boss@example.test', 'boss')
        shipment = Shipment(
            tracking_number='DL-E2E-001',
            status='REQUESTED',
            origin='Athi River Industrial Zone',
            destination='Kisumu Central Warehouse',
            cargo_type='Packaged goods',
            tonnage=10,
            company_name='Example Client Ltd',
            truck_type='15_TON',
            quoted_amount_kes=25000,
        )
        db.session.add(shipment)
        db.session.commit()

        assigned = self.client.patch(
            '/api/shipments/DL-E2E-001/assignment',
            headers=boss_headers,
            json={
                'company_name': 'Example Client Ltd',
                'driver_user_id': driver.id,
                'destination': 'Kisumu Central Warehouse',
            },
        )
        self.assertEqual(assigned.status_code, 200)
        self.assertEqual(assigned.json['shipment']['status'], 'AWAITING_DISPATCH')
        not_arrived = self.client.post(
            '/api/shipments/DL-E2E-001/proof-of-delivery/sign',
            headers=client_headers,
            json={'signer_name': 'Receiving Customer', 'signature_png': 'data:image/png;base64,AA=='},
        )
        self.assertEqual(not_arrived.status_code, 409)

        departed = self.client.patch(
            '/api/shipments/DL-E2E-001/status',
            headers=driver_headers,
            json={'status': 'IN_TRANSIT'},
        )
        self.assertEqual(departed.status_code, 200)
        self.assertIsNotNone(departed.json['shipment']['departed_at'])

        arrived = self.client.patch(
            '/api/shipments/DL-E2E-001/status',
            headers=driver_headers,
            json={'status': 'DELIVERED'},
        )
        self.assertEqual(arrived.status_code, 200)
        self.assertIsNotNone(arrived.json['shipment']['arrived_at'])

        signature = Image.new('RGB', (300, 100), 'white')
        ImageDraw.Draw(signature).line((20, 75, 80, 25, 150, 70, 225, 30, 280, 60), fill='#1b3b2b', width=5)
        signature_buffer = io.BytesIO()
        signature.save(signature_buffer, format='PNG')
        signature_payload = 'data:image/png;base64,' + base64.b64encode(
            signature_buffer.getvalue()
        ).decode('ascii')
        blank_signature_buffer = io.BytesIO()
        Image.new('RGB', (300, 100), 'white').save(blank_signature_buffer, format='PNG')
        blank_signature = 'data:image/png;base64,' + base64.b64encode(
            blank_signature_buffer.getvalue()
        ).decode('ascii')
        blank_sign = self.client.post(
            '/api/shipments/DL-E2E-001/proof-of-delivery/sign',
            headers=client_headers,
            json={'signer_name': 'Receiving Customer', 'signature_png': blank_signature},
        )
        self.assertEqual(blank_sign.status_code, 400)
        signed = self.client.post(
            '/api/shipments/DL-E2E-001/proof-of-delivery/sign',
            headers=client_headers,
            json={
                'signer_name': 'Receiving Customer',
                'signature_png': signature_payload,
            },
        )
        self.assertEqual(signed.status_code, 201)
        self.assertTrue(signed.json['invoice_created'])
        self.assertEqual(signed.json['shipment']['pod_signed_by'], 'Receiving Customer')
        self.assertEqual(
            self.client.post(
                '/api/shipments/DL-E2E-001/proof-of-delivery/sign',
                headers=client_headers,
                json={
                    'signer_name': 'Receiving Customer',
                    'signature_png': signature_payload,
                },
            ).status_code,
            409,
        )

        downloaded = self.client.get(
            '/api/shipments/DL-E2E-001/proof-of-delivery',
            headers=client_headers,
        )
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.mimetype, 'application/pdf')
        self.assertTrue(downloaded.data.startswith(b'%PDF-'))

        finance = self.client.get('/api/portal/delivery-finance', headers=client_headers)
        invoice = next(
            delivery for delivery in finance.json['deliveries']
            if delivery['tracking_number'] == 'DL-E2E-001'
        )
        self.assertEqual(invoice['invoice_amount_kes'], 25000)
        self.assertEqual(invoice['payment_status'], 'pending')

    def test_shipment_quote_rejects_over_capacity_and_destination_change_requires_acceptance(self):
        client_headers = self.login_headers('client@example.test', 'client')
        bad_quote = self.client.post('/api/shipments/quote', headers=client_headers, json={
            'origin': 'Athi River Industrial Zone',
            'destination': 'Mombasa Port Terminal',
            'truck_type': '3_TON',
            'tonnage': 5,
        })
        self.assertEqual(bad_quote.status_code, 400)

        pickup_at = datetime.now(timezone.utc) + timedelta(days=2)
        created = self.client.post('/api/shipments/requests', headers=client_headers, json={
            'origin': 'Athi River Industrial Zone',
            'destination': 'Kisumu Central Warehouse',
            'truck_type': '15_TON',
            'cargo_type': 'Packaged goods',
            'tonnage': 12,
            'pickup_address': 'Loading bay, Athi River',
            'pickup_at': pickup_at.isoformat(),
            'end_customer_name': 'Kisumu Market',
            'end_customer_phone': '+254700000000',
            'end_customer_address': 'Warehouse 5, Kisumu',
        })
        tracking_number = created.json['shipment']['tracking_number']
        original_rate = created.json['shipment']['quoted_amount_kes']
        change = self.client.post(
            f'/api/shipments/{tracking_number}/destination-change',
            headers=client_headers,
            json={
                'destination': 'Mombasa Port Terminal',
                'end_customer_address': 'Warehouse 2, Mombasa',
            },
        )
        self.assertEqual(change.status_code, 200)
        self.assertTrue(change.json['decision_required'])
        self.assertNotEqual(change.json['quote']['total_kes'], original_rate)

        rejected = self.client.post(
            f'/api/shipments/{tracking_number}/destination-change/decision',
            headers=client_headers,
            json={'accept': False},
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.json['shipment']['destination'], 'Kisumu Central Warehouse')
        self.assertEqual(rejected.json['shipment']['quoted_amount_kes'], original_rate)

        accepted_change = self.client.post(
            f'/api/shipments/{tracking_number}/destination-change',
            headers=client_headers,
            json={
                'destination': 'Mombasa Port Terminal',
                'end_customer_address': 'Warehouse 2, Mombasa',
            },
        )
        accepted = self.client.post(
            f'/api/shipments/{tracking_number}/destination-change/decision',
            headers=client_headers,
            json={'accept': True},
        )
        self.assertEqual(accepted_change.status_code, 200)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json['shipment']['destination'], 'Mombasa Port Terminal')
        self.assertEqual(
            accepted.json['shipment']['quoted_amount_kes'],
            accepted_change.json['quote']['total_kes'],
        )

    def test_main_accounts_are_created_with_usernames_and_emailed_credentials(self):
        self.app.config.update({
            'SENDGRID_API_KEY': 'test-sendgrid-key',
            'MAIL_FROM_EMAIL': 'no-reply@example.test',
            'MAIN_ACCOUNT_EMAIL': 'info@difan-logistics.com',
        })
        with patch(
            'backend.routes.auth.httpx.post',
            return_value=SimpleNamespace(status_code=202),
        ) as send_email:
            ensure_main_accounts()

        main_account = UserAccount.query.filter_by(username='DifanMain').one()
        hr_account = UserAccount.query.filter_by(username='DifanSecond').one()
        self.assertEqual(main_account.role, 'boss')
        self.assertEqual(hr_account.role, 'hr')
        self.assertEqual(send_email.call_count, 2)
        for call in send_email.call_args_list:
            payload = call.kwargs['json']
            self.assertEqual(
                payload['personalizations'][0]['to'][0]['email'],
                'info@difan-logistics.com',
            )
            username = payload['content'][0]['value'].split('Username: ')[1].splitlines()[0]
            temporary_password = payload['content'][0]['value'].split('Temporary password: ')[1].splitlines()[0]
            login = self.client.post('/api/auth/login', json={
                'username': username,
                'password': temporary_password,
            })
            self.assertEqual(login.status_code, 200)
            self.assertTrue(login.json['user']['must_change_password'])

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
        self.create_user('boss@example.test', 'boss', 'Difan Boss')
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
            {'admin', 'hr', 'boss', 'accountant'},
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


    def test_paystub_advance_requires_separate_signature_and_locks_nonessential_api(self):
        hr_headers = self.login_headers('hr@example.test', 'hr')
        created = self.client.post('/api/portal/payroll', headers=hr_headers, json={
            'employee_id': self.hr.id,
            'pay_period': 'October 2026',
            'basic_pay': 10000,
            'allowances': 500,
            'bonus': 0,
            'deductions': 400,
            'salary_advance': 600,
        })
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json['slip']['salary_advance'], 600)
        self.assertEqual(created.json['slip']['net_pay'], 9500)
        slip_id = created.json['slip']['id']
        self.app.config['TESTING'] = False
        unconfigured_storage = self.client.patch(
            f'/api/portal/payroll/{slip_id}/approve',
            headers=hr_headers,
        )
        self.app.config['TESTING'] = True
        self.assertEqual(unconfigured_storage.status_code, 503)
        approved = self.client.patch(
            f'/api/portal/payroll/{slip_id}/approve',
            headers=hr_headers,
        )
        self.assertEqual(approved.status_code, 200)
        pending = self.client.get('/api/portal/workforce/pending', headers=hr_headers)
        self.assertEqual(pending.status_code, 200)
        self.assertTrue(pending.json['must_acknowledge'])
        self.assertEqual(pending.json['pending_slips'][0]['salary_advance'], 600)
        self.assertEqual(self.client.get('/api/shipments', headers=hr_headers).status_code, 423)

        emergency = self.client.post('/api/portal/workforce/emergency', headers=hr_headers, json={
            'report_type': 'ACTIVE_ACCIDENT',
            'location': 'A109 near Salama',
            'description': 'Collision reported; requesting emergency response.',
        })
        self.assertEqual(emergency.status_code, 201)

        signature = Image.new('RGB', (320, 120), 'white')
        ImageDraw.Draw(signature).line((20, 85, 100, 25, 185, 80, 290, 30), fill='black', width=6)
        signature_buffer = io.BytesIO()
        signature.save(signature_buffer, format='PNG')
        signature_payload = 'data:image/png;base64,' + base64.b64encode(
            signature_buffer.getvalue()
        ).decode('ascii')
        missing_advance = self.client.post(
            f'/api/portal/payroll/{slip_id}/sign',
            headers=hr_headers,
            json={
                'receipt_confirmed': True,
                'paystub_confirmed': True,
                'advance_confirmed': False,
                'signature_png': signature_payload,
                'device_id': 'browser-device-test',
                'latitude': -1.29,
                'longitude': 36.82,
            },
        )
        self.assertEqual(missing_advance.status_code, 400)

        with patch(
            'backend.routes.workforce.upload_immutable_pdf',
            return_value=('payroll-signed/test.pdf', 'version-1', 'a' * 64),
        ) as upload:
            signed = self.client.post(
                f'/api/portal/payroll/{slip_id}/sign',
                headers=hr_headers,
                json={
                    'receipt_confirmed': True,
                    'paystub_confirmed': True,
                    'advance_confirmed': True,
                    'signature_png': signature_payload,
                    'device_id': 'browser-device-test',
                    'latitude': -1.29,
                    'longitude': 36.82,
                },
            )
        self.assertEqual(signed.status_code, 200)
        self.assertEqual(len(signed.json['sha256']), 64)
        self.assertEqual(upload.call_count, 1)
        signed_pdf = upload.call_args.args[0]
        self.assertTrue(signed_pdf.startswith(b'%PDF-'))
        with fitz.open(stream=signed_pdf, filetype='pdf') as document:
            pdf_text = '\n'.join(page.get_text() for page in document)
        self.assertIn('Salary Advance / Early Cashout', pdf_text)
        self.assertIn('600.00', pdf_text)
        self.assertIn('browser-device-test', pdf_text)
        self.assertIn('GPS: -1.29, 36.82', pdf_text)
        slip = db.session.get(PayrollSlip, slip_id)
        self.assertEqual(slip.signature_device_id, 'browser-device-test')
        self.assertIsNotNone(slip.signature_ip_address)
        self.assertEqual(slip.signature_latitude, -1.29)
        self.assertIsNotNone(slip.advance_signed_at)
        self.assertEqual(self.client.get('/api/shipments', headers=hr_headers).status_code, 200)
        with patch(
            'backend.routes.workforce.download_verified_pdf',
            return_value=b'%PDF-verified',
        ):
            download = self.client.get(
                f'/api/portal/payroll/{slip_id}/signed-document',
                headers=hr_headers,
            )
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.data, b'%PDF-verified')

    def test_signed_pdf_storage_requires_object_lock_kms_and_hash_integrity(self):
        from backend.routes.workforce import download_verified_pdf, upload_immutable_pdf

        self.app.config.update({
            'PAYROLL_DOCUMENTS_BUCKET': 'signed-records-test',
            'PAYROLL_DOCUMENT_KMS_KEY_ID': 'kms-key-test',
            'AWS_REGION': 'eu-west-1',
            'PAYROLL_DOCUMENT_RETENTION_DAYS': '3650',
        })
        s3_client = Mock()
        s3_client.get_object_lock_configuration.return_value = {
            'ObjectLockConfiguration': {'ObjectLockEnabled': 'Enabled'},
        }
        s3_client.get_bucket_versioning.return_value = {'Status': 'Enabled'}
        s3_client.put_object.return_value = {'VersionId': 'version-12'}
        contents = b'%PDF-immutable-test'
        with patch('boto3.client', return_value=s3_client) as create_client:
            object_key, version_id, digest = upload_immutable_pdf(contents)
        self.assertTrue(object_key.startswith('payroll-signed/'))
        self.assertEqual(version_id, 'version-12')
        self.assertEqual(digest, hashlib.sha256(contents).hexdigest())
        put_args = s3_client.put_object.call_args.kwargs
        self.assertEqual(put_args['ServerSideEncryption'], 'aws:kms')
        self.assertEqual(put_args['ObjectLockMode'], 'COMPLIANCE')
        self.assertIn('ObjectLockRetainUntilDate', put_args)
        create_client.assert_called_with('s3', region_name='eu-west-1')

        retrieval_client = SimpleNamespace(get_object=lambda **kwargs: {'Body': io.BytesIO(contents)})
        with patch('boto3.client', return_value=retrieval_client):
            self.assertEqual(download_verified_pdf(object_key, version_id, digest), contents)
            with self.assertRaisesRegex(RuntimeError, 'SHA-256'):
                download_verified_pdf(object_key, version_id, '0' * 64)

        missing_lock_client = SimpleNamespace(
            get_object_lock_configuration=lambda **kwargs: {
                'ObjectLockConfiguration': {'ObjectLockEnabled': 'Disabled'},
            },
            get_bucket_versioning=lambda **kwargs: {'Status': 'Enabled'},
            put_object=lambda **kwargs: {'VersionId': 'unused'},
        )
        with patch('boto3.client', return_value=missing_lock_client):
            with self.assertRaisesRegex(RuntimeError, 'Object Lock enabled'):
                upload_immutable_pdf(contents)

    def test_published_terms_notice_locks_navigation_until_signed(self):
        hr_headers = self.login_headers('hr@example.test', 'hr')
        notice = self.client.post('/api/portal/workforce/notices', headers=hr_headers, json={
            'notice_type': 'TERMS_UPDATE',
            'title': 'Updated driver terms',
            'version': '2026.10',
            'body': 'Review the updated terms before continuing.',
        })
        self.assertEqual(notice.status_code, 201)
        notice_id = notice.json['notice']['id']
        self.assertEqual(self.client.get('/api/shipments', headers=hr_headers).status_code, 423)

        signature = Image.new('RGB', (320, 120), 'white')
        ImageDraw.Draw(signature).line((20, 85, 100, 25, 185, 80, 290, 30), fill='black', width=6)
        signature_buffer = io.BytesIO()
        signature.save(signature_buffer, format='PNG')
        signature_payload = 'data:image/png;base64,' + base64.b64encode(
            signature_buffer.getvalue()
        ).decode('ascii')
        with patch(
            'backend.routes.workforce.upload_immutable_pdf',
            return_value=('notices-signed/test.pdf', 'version-1', 'b' * 64),
        ):
            signed = self.client.post(
                f'/api/portal/workforce/notices/{notice_id}/acknowledge',
                headers=hr_headers,
                json={
                    'acknowledged': True,
                    'signature_png': signature_payload,
                    'device_id': 'browser-device-test',
                    'latitude': None,
                    'longitude': None,
                },
            )
        self.assertEqual(signed.status_code, 201)
        self.assertFalse(
            self.client.get('/api/portal/workforce/pending', headers=hr_headers).json['must_acknowledge']
        )
        self.assertEqual(self.client.get('/api/shipments', headers=hr_headers).status_code, 200)
        listed = self.client.get('/api/portal/workforce/notices', headers=hr_headers)
        self.assertEqual(listed.status_code, 200)
        self.assertIsNotNone(listed.json['notices'][0]['signed_document_url'])

    def test_driver_disputes_hr_case_before_penalty_and_submits_evidence(self):
        hr_headers = self.login_headers('hr@example.test', 'hr')
        driver = self.create_user('driver@example.test', 'driver', 'Delivery Driver')
        evidence = io.BytesIO(b'%PDF-1.4\nEvidence')
        issued = self.client.post('/api/portal/workforce/cases', headers=hr_headers, data={
            'employee_id': str(driver.id),
            'case_type': 'MINOR_INFRACTION',
            'severity': 'CARGO_MISMANAGEMENT',
            'details': 'Cargo count did not match the manifest.',
            'evidence': (evidence, 'manifest-evidence.pdf', 'application/pdf'),
        })
        self.assertEqual(issued.status_code, 201)
        case_id = issued.json['case']['id']
        self.assertEqual(issued.json['case']['status'], 'DISPUTE_OPEN')
        self.assertEqual(len(issued.json['case']['evidence']), 1)
        driver_headers = self.login_headers('driver@example.test', 'driver')
        rebuttal = self.client.post(
            f'/api/portal/workforce/cases/{case_id}/dispute',
            headers=driver_headers,
            data={'details': 'The recorded cargo count was verified at both handover points.'},
        )
        self.assertEqual(rebuttal.status_code, 201)
        self.assertEqual(rebuttal.json['case']['status'], 'DISPUTED')
        score = self.client.get('/api/portal/workforce/score', headers=driver_headers)
        self.assertEqual(score.status_code, 200)
        self.assertEqual(score.json['score']['hr_infraction_penalty'], 0)

        resolved = self.client.patch(
            f'/api/portal/workforce/cases/{case_id}/resolve',
            headers=hr_headers,
            json={'upheld': True, 'resolution_note': 'Evidence reviewed.'},
        )
        self.assertEqual(resolved.status_code, 200)
        score_after_review = self.client.get('/api/portal/workforce/score', headers=driver_headers)
        self.assertEqual(score_after_review.json['score']['hr_infraction_penalty'], 5)
        evidence_download = self.client.get(
            issued.json['case']['evidence'][0]['download_url'],
            headers=hr_headers,
        )
        self.assertEqual(evidence_download.status_code, 200)
        self.assertEqual(evidence_download.data, b'%PDF-1.4\nEvidence')
        case = db.session.get(WorkforceCase, case_id)
        self.assertEqual(case.status, 'UPHELD')
        case.created_at = datetime.now(timezone.utc) - timedelta(days=45)
        db.session.commit()
        decayed_score = self.client.get('/api/portal/workforce/score', headers=driver_headers)
        self.assertEqual(decayed_score.json['score']['hr_infraction_penalty'], 2.5)
        case.created_at = datetime.now(timezone.utc) - timedelta(days=91)
        db.session.commit()
        expired_score = self.client.get('/api/portal/workforce/score', headers=driver_headers)
        self.assertEqual(expired_score.json['score']['hr_infraction_penalty'], 0)

    def test_driver_can_use_72_hour_rebuttal_right_during_paystub_lockout(self):
        hr_headers = self.login_headers('hr@example.test', 'hr')
        driver = self.create_user('driver@example.test', 'driver', 'Delivery Driver')
        issued = self.client.post('/api/portal/workforce/cases', headers=hr_headers, data={
            'employee_id': str(driver.id),
            'case_type': 'MINOR_INFRACTION',
            'severity': 'MINOR_LATE_ARRIVAL',
            'details': 'Reported late to the pickup yard.',
        })
        self.assertEqual(issued.status_code, 201)
        slip = self.client.post('/api/portal/payroll', headers=hr_headers, json={
            'employee_id': driver.id,
            'pay_period': 'October 2026',
            'basic_pay': 10000,
            'deductions': 0,
            'salary_advance': 0,
        })
        self.assertEqual(slip.status_code, 201)
        approved = self.client.patch(
            f"/api/portal/payroll/{slip.json['slip']['id']}/approve",
            headers=hr_headers,
        )
        self.assertEqual(approved.status_code, 200)

        driver_headers = self.login_headers('driver@example.test', 'driver')
        self.assertTrue(
            self.client.get('/api/portal/workforce/pending', headers=driver_headers).json['must_acknowledge']
        )
        self.assertEqual(self.client.get('/api/shipments', headers=driver_headers).status_code, 423)
        driver_cases = self.client.get('/api/portal/workforce/cases', headers=driver_headers)
        self.assertEqual(driver_cases.status_code, 200)
        self.assertEqual([item['id'] for item in driver_cases.json['cases']], [issued.json['case']['id']])
        rebuttal = self.client.post(
            f"/api/portal/workforce/cases/{issued.json['case']['id']}/dispute",
            headers=driver_headers,
            data={'details': 'The pickup instructions were changed after my scheduled arrival.'},
        )
        self.assertEqual(rebuttal.status_code, 201)

    def test_driver_availability_blocks_dispatch_and_post_delivery_rating_updates_score(self):
        hr_headers = self.login_headers('hr@example.test', 'hr')
        driver = self.create_user('driver@example.test', 'driver', 'Delivery Driver')
        status = self.client.patch(
            f'/api/portal/workforce/drivers/{driver.id}/status',
            headers=hr_headers,
            json={'status': 'ON_LEAVE', 'leave_type': 'VACATION', 'note': 'Approved leave.'},
        )
        self.assertEqual(status.status_code, 200)

        shipment = Shipment(
            tracking_number='DL-WORKFORCE-001',
            status='REQUESTED',
            origin='Athi River Industrial Zone',
            destination='Kisumu Central Warehouse',
            cargo_type='Packaged goods',
            tonnage=5,
            company_name='Example Client Ltd',
            delivery_due_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db.session.add(shipment)
        db.session.commit()
        assignment = self.client.patch(
            '/api/shipments/DL-WORKFORCE-001/assignment',
            headers=hr_headers,
            json={
                'company_name': 'Example Client Ltd',
                'driver_user_id': driver.id,
                'destination': 'Kisumu Central Warehouse',
            },
        )
        self.assertEqual(assignment.status_code, 400)

        self.client.patch(
            f'/api/portal/workforce/drivers/{driver.id}/status',
            headers=hr_headers,
            json={'status': 'ACTIVE', 'leave_type': None, 'note': ''},
        )
        assignment = self.client.patch(
            '/api/shipments/DL-WORKFORCE-001/assignment',
            headers=hr_headers,
            json={
                'company_name': 'Example Client Ltd',
                'driver_user_id': driver.id,
                'destination': 'Kisumu Central Warehouse',
            },
        )
        self.assertEqual(assignment.status_code, 200)

        shipment.status = 'DELIVERED'
        shipment.arrived_at = datetime.now(timezone.utc)
        db.session.add(ShipmentProofOfDelivery(
            shipment_tracking_number=shipment.tracking_number,
            signer_user_id=self.client_user.id,
            signer_name='Receiving Customer',
            signature_png=b'png',
            signed_at=datetime.now(timezone.utc),
        ))
        db.session.commit()
        client_headers = self.login_headers('client@example.test', 'client')
        rating = self.client.post(
            '/api/portal/workforce/shipments/DL-WORKFORCE-001/rating',
            headers=client_headers,
            json={'stars': 4, 'feedback': 'Polite and careful driver.'},
        )
        self.assertEqual(rating.status_code, 201)
        self.assertEqual(rating.json['score']['customer_rating_average'], 4)
        self.assertEqual(rating.json['score']['on_time_score'], 0)
        duplicate = self.client.post(
            '/api/portal/workforce/shipments/DL-WORKFORCE-001/rating',
            headers=client_headers,
            json={'stars': 5, 'feedback': ''},
        )
        self.assertEqual(duplicate.status_code, 409)
        driver_headers = self.login_headers('driver@example.test', 'driver')
        opt_in = self.client.patch(
            '/api/portal/workforce/leaderboard-opt-in',
            headers=driver_headers,
            json={'opt_in': True, 'handle': 'CarefulDriver'},
        )
        self.assertEqual(opt_in.status_code, 200)
        leaderboard = self.client.get('/api/portal/workforce/leaderboard')
        self.assertEqual(leaderboard.status_code, 200)
        self.assertEqual(leaderboard.json['drivers'][0]['handle'], 'CarefulDriver')


if __name__ == '__main__':
    unittest.main()
