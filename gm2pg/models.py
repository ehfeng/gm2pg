from datetime import datetime
import httplib2

from apiclient.discovery import build
from flask_login import UserMixin
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from oauth2client.client import OAuth2Credentials
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import ARRAY

from app import app

db = SQLAlchemy(app)
migrate = Migrate(app, db)

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.Text)
    history_id = db.Column(db.Integer)
    customer_label_id = db.Column(db.Text)
    credentials_json = db.Column(JSONB)

    threads = db.relationship('Thread', backref='user', lazy='dynamic')

    def __repr__(self):
        return '<User {}>'.format(self.email)

    @property
    def credentials(self):
        if self.credentials_json:
            return OAuth2Credentials.from_json(self.credentials_json)
        else:
            return None

    @credentials.setter
    def credentials(self, cred):
        if type(cred) is OAuth2Credentials:
            self.credentials_json = cred.to_json()
        else:
            self.credentials_json = cred

    @property
    def gmail(self):
        http = self.credentials.authorize(httplib2.Http())
        return build('gmail', 'v1', http=http)

    def sync_inbox(self):
        labels = self.gmail.users().labels().list(userId='me').execute()['labels']
        if len([label for label in labels if label['name'] == 'Growth']) == 0:
            raise Exception('No Growth label found')

        for label in labels:
            if label['name'] == 'Growth':
                self.customer_label_id = label['id']

        db.session.add(self)
        db.session.commit()

        next_page_token = None
        while True:
            thread_result = self.gmail.users().threads().list(userId='me', labelIds=self.customer_label_id, pageToken=next_page_token).execute()
            for thread in thread_result['threads']:

                for message in self.gmail.users().threads().get(userId='me', id=thread['id']).execute()['messages']:
                    data = self.gmail.users().messages().get(userId='me', id=message['id'], format='metadata').execute()

                    msg = Message(
                        gmail_id=data['id'],
                        internal_date=datetime.fromtimestamp(int(data['internalDate']) / 1e3),
                        snippet=data['snippet'],
                        subject=[x for x in data['payload']['headers'] if x['name'] == 'Subject'][0]['value'],
                        sender=[x for x in data['payload']['headers'] if x['name'] == 'From'][0]['value'],
                        recipient=[x for x in data['payload']['headers'] if x['name'] == 'To'][0]['value'],
                        )
                    thread = Thread.query.filter_by(gmail_id=data['threadId']).first()
                    if not thread:
                        thread = Thread(gmail_id=data['threadId'], user_id=self.id,)
                    msg.thread = thread
                    db.session.add(msg)
                    db.session.add(thread)

            if thread_result.get('nextPageToken'):
                next_page_token = thread_result['nextPageToken']
            else:
                db.session.commit()
                break

        # pull history_id
        # save latest
        # setup notifications


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    gmail_id = db.Column(db.Text)
    internal_date = db.Column(db.DateTime, nullable=False)
    snippet = db.Column(db.Text)

    sender = db.Column(db.Text)
    recipient = db.Column(db.Text)
    cc = db.Column(db.Text)
    bcc = db.Column(db.Text)
    subject = db.Column(db.Text)

    thread_id = db.Column(db.Integer, db.ForeignKey('thread.id'), nullable=False)


class Thread(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    gmail_id = db.Column(db.Text)
    snippet = db.Column(db.Text)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    messages = db.relationship('Message', backref='thread', lazy='dynamic')
