import base64
import json
from datetime import datetime, timedelta, date
from email.mime.text import MIMEText

import googleapiclient.discovery
import holidays
from google.oauth2 import service_account
from knox import AutoKnox

from senior_reviewer_assignment_tool import SeniorReviewAssignmentTool


class GoogleApiClient:
    KNOX_CREDENTIALS = 'm10n_google_api_access:credentials'
    SCOPES = [
        'https://www.googleapis.com/auth/gmail.compose',
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/admin.directory.group',
        'https://www.googleapis.com/auth/calendar'
    ]
    SERVICE_ACCOUNT_EMAIL = 'svc-m10design@pinterest.com'
    SENIOR_REVIEW_GROUP = 'm10n-senior-design-review-board@pinterest.com'
    M10N_ADMIN_EMAIL = 'm10n-design-review-admin@pinterest.com'
    PAGERDUTY_EMAIL = 'mdr-admin@pinterest.pagerduty.com'
    US_HOLIDAYS = holidays.US()
    GOOGLE_DATE_FORMAT = '%Y-%m-%dT%H:%M:%SZ'

    def __init__(self):
        credentials_from_knox = json.loads(AutoKnox(self.KNOX_CREDENTIALS).get_primary().strip())
        svc_acct_credentials = service_account.Credentials.from_service_account_info(
            credentials_from_knox, scopes=self.SCOPES)
        delegated = svc_acct_credentials.with_subject(self.SERVICE_ACCOUNT_EMAIL)
        self.groups_service = googleapiclient.discovery.build('admin', 'directory_v1', credentials=delegated)
        self.mail_service = googleapiclient.discovery.build('gmail', 'v1', credentials=delegated)
        self.calendar_service = googleapiclient.discovery.build('calendar', 'v3', credentials=delegated)

    def __create_message(self, message_text, subject, to=M10N_ADMIN_EMAIL):
        message = MIMEText(message_text)
        message['to'] = to
        message['subject'] = subject
        return {'raw': base64.urlsafe_b64encode(message.as_string())}

    def __is_business_day(self, date):
        return date.weekday() not in holidays.WEEKEND and date not in self.US_HOLIDAYS

    # get the date x business days from the start date (specified by count)
    def __get_x_business_days_from(self, start, count=0):
        one_day = timedelta(days=1)
        next_day = start + one_day
        for d in range(0, count):
            while not self.__is_business_day(next_day):
                next_day += one_day
        return next_day

    def __get_events(self, calendar_id, start_date=None, end_date=None,
                     max_results=100, order_by=None, q=None, single_events=False):
        events = []
        page_token = None

        if start_date is not None:
            start = start_date.strftime(self.GOOGLE_DATE_FORMAT)
        else:
            start = None

        if end_date is not None:
            end = end_date.strftime(self.GOOGLE_DATE_FORMAT)
        else:
            end = None

        while True:
            events_results_page = self.calendar_service.events().list(
                calendarId=calendar_id, timeMin=start, timeMax=end,
                maxResults=max_results, orderBy=order_by,
                pageToken=page_token, singleEvents=single_events, q=q).execute()
            events += events_results_page.get('items', [])
            page_token = events_results_page.get('nextPageToken')
            if not page_token:
                break
        return events

    def __is_available(self, email, start_date, end_date):
        # For now we are just checking the number of OOO events in the next 7 days
        # Already added some utilities to help compute business days but in this case
        # We need to worry about time zones so leaving as simple for now -- can improve later
        # also note that we are deduplicating by start time in case people have the same OOO
        # marked on multiple calendars
        days_ooo = len({
            event.get('start').get('dateTime'): event
            for event in self.__get_events(email, start_date, end_date, q='Out of office')
        }.values())
        days_available_to_review = SeniorReviewAssignmentTool.REVIEW_SLA_IN_DAYS - days_ooo
        return days_available_to_review >= SeniorReviewAssignmentTool.MIN_DAYS_AVAILABLE_FOR_ASSIGNMENT

    def get_sr_review_emails(self):
        # This assumes members with MANAGER role to be senior reviewers while members with OWNER role are admins
        group = self.groups_service.members().list(groupKey=self.SENIOR_REVIEW_GROUP, roles='MANAGER').execute()
        emails = [member['email'] for member in group['members']]
        # TODO remove this and return emails instead once we're ready to assign to actual people
        return ["lucilla@pinterest.com", "vbannister@pinterest.com"]

    def get_availability(self, sr_review_emails):
        now = date.today()
        review_due_date = self.__get_x_business_days_from(now, SeniorReviewAssignmentTool.REVIEW_SLA_IN_DAYS)

        map = {email: self.__is_available(email, now, review_due_date) for email in sr_review_emails}
        return map

    def get_in_person_review_meetings(self, max_results):
        now = datetime.utcnow()
        # TODO: REPLACE THIS -- this is a hack because I was not able to access the m10n-design-review calendar
        #  we should have a separate calendar where these events are stored
        return self.__get_events('lucilla@pinterest.com', start_date=now, max_results=max_results,
                                 q='m10n in person design review', single_events=True, order_by='startTime')

    # TODO replace calanderId once we are able to access m10n-design-review calendar -- note that to make updates
    #  service account needs to be added to calander with update permissions
    def update_in_person_review_meeting_with_assigned_design_review(self, event_id, fields_to_update):
        # Using events.patch rather than events.update here so that we only have to pass back the fields to update
        # this protects against unintentional updates if event data gets corrupted
        return self.calendar_service.events().patch(calendarId='lucilla@pinterest.com',
                                                    eventId=event_id,
                                                    body=fields_to_update).execute()

    def send_email_with_updates(self, updates, update_type):
        message_text = "The following updates have been made:\n\t" \
                       + "\n\t".join([json.dumps(update) for update in updates])
        subject = "MDR Cron Updates: " + update_type.value
        message = self.__create_message(message_text, subject)

        return self.mail_service.users().messages().send(userId='me', body=message).execute()

    def send_pagerduty_email(self, error, stacktrace, update_type):
        message_text = '{error}\n\nStacktrace:\n{stacktrace}'.format(error=error, stacktrace=stacktrace)
        subject = "Exception while making updates: " + update_type.value
        message = self.__create_message(message_text, subject, self.PAGERDUTY_EMAIL)
        return self.mail_service.users().messages().send(userId='me', body=message).execute()