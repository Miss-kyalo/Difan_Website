# backend/app.py
from flask import Flask, request, jsonify #install missing dependancy
import random
import string

app = Flask(__name__)

def generate_random_password(length=8):
    characters = string.ascii_uppercase + string.digits
    return 'DF-' + ''.join(random.choice(characters) for _ in range(length))

@app.route('/api/provision-account', methods=['POST'])
def provision_account():
    data = request.get_json()
    company_name = data.get('company_name')
    email = data.get('email')

    if not company_name or not email:
        return jsonify({'error': 'Missing company or email'}), 400

    temp_password = generate_random_password()
    
    # Logic to send email via SMTP or SendGrid goes here
    
    return jsonify({
        'status': 'success',
        'message': f'Account created for {company_name}',
        'email': email,
        'temp_password': temp_password
    }), 201

if __name__ == '__main__':
    app.run(port=5000, debug=True)