import base64
import httplib2
import json
import os

from apiclient.discovery import build
from flask import (
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for
)
from flask_login import (
    current_user,
    login_required,
    login_user,
    logout_user,
)
from oauth2client.client import (
    HttpAccessTokenRefreshError,
    OAuth2WebServerFlow
)

from app import app, csrf, login_manager
from gm2pg.models import db, User, Message, Thread

login_manager.login_view = "login"

def get_flow():
    flow = OAuth2WebServerFlow(
        client_id=os.environ['GOOGLE_CLIENT_ID'],
        client_secret=os.environ['GOOGLE_CLIENT_SECRET'],
        scope='https://www.googleapis.com/auth/gmail.readonly',
        redirect_uri=os.environ['GOOGLE_REDIRECT_URI'],
        )
    flow.params['access_type'] = 'offline'
    flow.params['prompt'] = 'consent'
    return flow


@login_manager.user_loader
def load_user(user_id):
    user = User.query.get(user_id)
    if user and user.credentials and (user.credentials.refresh_token is None
        or user.credentials.access_token_expired):
        try:
            user.credentials.refresh(httplib2.Http())
            db.session.add(user)
            db.session.commit()
            return user
        except HttpAccessTokenRefreshError:
            user.credentials = None
            db.session.add(user)
            db.session.commit()
            return None
    return user


@app.route('/')
def index():
    if current_user.is_authenticated:
        return current_user.email
    return 'hi'


@app.route('/login')
def login():
    if (current_user.is_authenticated and current_user.credentials and
        (current_user.credentials.refresh_token or
        request.args.get('force') != 'True')):
        return redirect(request.args.get('next') or url_for('index'))
    return redirect(get_flow().step1_get_authorize_url())


@app.route('/auth/finish')
def auth_finish():
    credentials = get_flow().step2_exchange(request.args.get('code'))
    http = credentials.authorize(httplib2.Http())
    gmail = build('gmail', 'v1', http=http)
    profile = gmail.users().getProfile(userId='me').execute()

    user = User.query.filter_by(email=profile['emailAddress']).first()
    if user is None:
        user = User()
        user.email = profile['emailAddress']
        user.credentials_json = credentials.to_json()
        db.session.add(user)
        db.session.commit()
    elif user.credentials is None:
        user.credentials_json = credentials.to_json()
        db.session.add(user)
        db.session.commit()

    login_user(user, remember=True)
    return redirect(url_for('index'))


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/sync')
def sync():
    current_user.sync_inbox()
    return 'hi'
