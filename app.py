import pickle
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
import os
from datetime import datetime
from dotenv import load_dotenv

# Disable all logging
import logging
logging.disable(logging.CRITICAL)

load_dotenv()

# MongoDB connection
try:
    MONGODB_URI = os.getenv('MONGODB_URI')
    if not MONGODB_URI:
        raise ValueError("MONGODB_URI environment variable is not set")
    
    client = MongoClient(MONGODB_URI)
    # Test the connection
    client.admin.command('ping')
    db = client['predictive_maintenance']
    users_collection = db['users']
    print("✓ Connected to MongoDB")
except Exception as e:
    print(f"✗ MongoDB connection failed: {str(e)}")
    raise

# User model
class User(UserMixin):
    def __init__(self, username, email, password):
        self.id = username
        self.username = username
        self.email = email
        self.password_hash = generate_password_hash(password)
        self.created_at = datetime.utcnow()
        self._is_active = True

    @property
    def is_active(self):
        return self._is_active

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'username': self.username,
            'email': self.email,
            'password_hash': self.password_hash,
            'created_at': self.created_at,
            'is_active': self._is_active
        }

    @staticmethod
    def from_dict(data):
        user = User(data['username'], data['email'], '')
        user.password_hash = data['password_hash']
        user.created_at = data['created_at']
        user._is_active = data.get('is_active', True)
        return user

# Database functions
def get_user_by_username(username):
    return users_collection.find_one({'username': username})

def get_user_by_email(email):
    return users_collection.find_one({'email': email})

def create_user(user_data):
    return users_collection.insert_one(user_data)

# Flask app setup
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key')

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    user_data = get_user_by_username(user_id)
    if user_data:
        return User.from_dict(user_data)
    return None

# Routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user_data = get_user_by_username(username)
        if user_data:
            user = User.from_dict(user_data)
            if user.check_password(password):
                login_user(user)
                flash('Logged in successfully!', 'success')
                return redirect(url_for('index'))
        
        flash('Invalid username or password', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Passwords do not match', 'danger')
            return render_template('register.html')
        
        if get_user_by_username(username):
            flash('Username already exists', 'danger')
            return render_template('register.html')
        
        if get_user_by_email(email):
            flash('Email already registered', 'danger')
            return render_template('register.html')
        
        user = User(username, email, password)
        create_user(user.to_dict())
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

# Load the model and scaler
try:
    model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rf_model.pkl')
    scaler_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'st_scaler.pkl')
    
    print(f"Loading model from: {model_path}")
    print(f"Loading scaler from: {scaler_path}")
    
    model = pickle.load(open(model_path, 'rb'))
    scaler = pickle.load(open(scaler_path, 'rb'))
    
    print("✓ Model and scaler loaded successfully")
except Exception as e:
    print(f"✗ Error loading model or scaler: {str(e)}")
    model = None
    scaler = None

# Define feature names
feature_names = ['UDI', 'Air_Temp', 'Process_temperature', 'Ratational_speed', 'Torque', 'Tool_wear']

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/predict', methods=['POST'])
@login_required
def predict():
    if model is None or scaler is None:
        flash('Error: Model files not loaded properly. Please contact support.', 'error')
        return redirect(url_for('index'))
    
    try:
        # Get form data
        UDI = float(request.form.get('UDI'))
        Air_Temp = float(request.form.get('Air_Temp'))
        Process_temperature = float(request.form.get('Process_temperature'))
        Ratational_speed = float(request.form.get('Ratational_speed'))
        Torque = float(request.form.get('Torque'))
        Tool_wear = float(request.form.get('Tool_wear'))

        # Create feature array
        features = np.array([[UDI, Air_Temp, Process_temperature, Ratational_speed, Torque, Tool_wear]])
        
        # Scale features
        features_scaled = scaler.transform(features)
        
        # Make prediction
        result = model.predict(features_scaled)[0]
        
        # Determine maintenance message
        if result > 0.00 and result <= 0.25:
            text = "The Condition of Equipment is Best. Check after 10 days."
            status = "success"
        elif result > 0.25 and result <= 0.50:
            text = "The Condition of Equipment is good. Check after 5 days."
            status = "info"
        elif result > 0.50 and result <= 0.75:
            text = "The Condition of Equipment is not good. Maintenance needed soon."
            status = "warning"
        else:
            text = "The Condition of Equipment is critical. Immediate maintenance required."
            status = "danger"
        
        return render_template('index.html', result=result, text=text, status=status)
        
    except Exception as e:
        flash(f'Error making prediction: {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/about')
@login_required
def about():
    return render_template('about.html')

@app.route('/contact', methods=['GET', 'POST'])
@login_required
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        subject = request.form.get('subject')
        message = request.form.get('message')
        flash('Thank you for your message! We will get back to you soon.', 'success')
        return redirect(url_for('contact'))
    return render_template('contact.html')

@app.route('/view_one')
def view_one():
    title = 'Motor'
    return render_template('view.html', title=title)

@app.route('/view_two')
def view_two():
    title = 'Pump'
    return render_template('view2.html', title=title)

@app.route('/view_three')
def view_three():
    title = 'Turbine'
    return render_template('view3.html', title=title)

@app.route('/help')
@login_required
def help():
    return render_template('help.html')

@app.route('/feedback', methods=['GET', 'POST'])
@login_required
def feedback():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        feedback_text = request.form.get('feedback')
        flash('Thank you for your feedback!', 'success')
        return redirect(url_for('feedback'))
    return render_template('feedback.html')

if __name__ == "__main__":
    print("\n=== Predictive Maintenance System ===")
    print("✓ Server is starting...")
    print("✓ Open your browser and go to: http://127.0.0.1:5000")
    print("=====================================\n")
    app.run(debug=True)
