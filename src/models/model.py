from src import db
from datetime import datetime

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key = True, unique=True)
    fullname = db.Column(db.String(50))
    email = db.Column(db.String(70), unique = True)
    password = db.Column(db.String(250))
    phone = db.Column(db.String(15))
    
class Plaid(db.Model):
    __tablename__ = 'plaid'
    id = db.Column(db.String(255), primary_key = True, unique=True)
    access_token = db.Column(db.String(255))
    client_id = db.Column(db.String(50))
    institution = db.Column(db.String(50))
    
class Account(db.Model):
    __tablename__ = 'accounts'
    id = db.Column(db.String(255), primary_key = True, unique=True)
    plaid_id = db.Column(db.String(255))
    name = db.Column(db.String(50))
    balance = db.Column(db.Float)
    subtype = db.Column(db.String(50))
    
    