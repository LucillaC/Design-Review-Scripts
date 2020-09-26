import base64
from collections import deque
import json
from email.mime.text import MIMEText
from enum import Enum

import googleapiclient.discovery
from google.oauth2 import service_account
from jira import JIRA
from knox import AutoKnox
import pickle


class UpdateType(Enum):
    SENIOR_REVIEWER_ASSIGNMENT = 'SENIOR REVIEWER ASSIGNMENT'


class Reviewer:
    def __init__(self, email, is_available):
        self.email = email
        self.ldap = email.split("@pinterest.com")[0]
        self.is_available = is_available


class JIRAHelper:
    JIRA_DOMAIN = 'https://jira.pinadmin.com'
    KNOX_JIRA_ACCESS_TOKEN = 'jira_prod_api_access:access_token'
    KNOX_JIRA_ACCESS_TOKEN_SECRET = 'jira_prod_api_access:access_token_secret'
    KNOX_JIRA_CONSUMER_KEY = 'jira_prod_api_access:consumer_key'
    KNOX_JIRA_PRIVATE_KEY = 'jira_prod_api_access:key_cert'

    SENIOR_REVIEWER_JQL = 'project = "Monetization Design Review" AND status = "In Review" ' \
                          'AND "Senior Reviewer" = EMPTY AND ' \
                          '"Responsible Teams" = M10N-Senior-Review-Poo AND Checklist is not EMPTY AND ' \
                          'Checklist != M10-Senior-Review-Poo'

    # Limit response to only fields we need so that we don't send/receive more data than necessary
    SENIOR_REVIEWER_FIELDS_FOR_UPDATE = ['customfield_18441']

    def __init__(self):
        self.jira = JIRA(self.JIRA_DOMAIN, oauth={
            'access_token': AutoKnox(self.KNOX_JIRA_ACCESS_TOKEN).get_primary().strip(),
            'access_token_secret': AutoKnox(self.KNOX_JIRA_ACCESS_TOKEN_SECRET).get_primary().strip(),
            'consumer_key': AutoKnox(self.KNOX_JIRA_CONSUMER_KEY).get_primary().strip(),
            'key_cert': AutoKnox(self.KNOX_JIRA_PRIVATE_KEY).get_primary().strip()
        })

    def __search_issues(self, jql, fields):
        issues = []
        chunk_size = 100
        while True:
            # Optimize by only pulling back fields that we need
            cur = self.jira.search_issues(jql, fields=", ".join(fields), startAt=0, maxResults=100)
            issues += cur.iterable
            if chunk_size > cur.total:
                break
        return issues

    def get_issues_to_assign(self):
        return self.__search_issues(self.SENIOR_REVIEWER_JQL, self.SENIOR_REVIEWER_FIELDS_FOR_UPDATE)


class GoogleHelper:
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


    def __init__(self):
        credentials_from_knox = json.loads(AutoKnox(self.KNOX_CREDENTIALS).get_primary().strip())
        svc_acct_credentials = service_account.Credentials.from_service_account_info(
            credentials_from_knox, scopes=self.SCOPES)
        delegated = svc_acct_credentials.with_subject(self.SERVICE_ACCOUNT_EMAIL)
        self.groups_service = googleapiclient.discovery.build('admin', 'directory_v1', credentials=delegated)
        self.mail_service = googleapiclient.discovery.build('gmail', 'v1', credentials=delegated)

    def __create_message(self, message_text, subject):
        message = MIMEText(message_text)
        message['to'] = self.M10N_ADMIN_EMAIL
        message['from'] = 'CRON'
        message['subject'] = subject
        return {'raw': base64.urlsafe_b64encode(message.as_string())}

    def get_sr_review_emails(self):
        # This assumes members with MANAGER role to be senior reviewers while members with OWNER role are admins
        group = self.groups_service.members().list(groupKey=self.SENIOR_REVIEW_GROUP, roles='MANAGER').execute()
        emails = [member['email'] for member in group['members']]
        # TODO remove this and return emails instead once we're ready to assign to actual people
        print("Got Emails:")
        print(emails)
        return ["lucilla@pinterest.com", "vbannister@pinterest.com"]

    def get_availability(self, sr_review_emails):
        # TODO need to pull OOO from G-CAL
        map = {email: True for email in sr_review_emails}
        # map["p3"] = False
        # map["p4"] = False
        return map

    def send_email_with_updates(self, updates, update_type):
        message_text = "The following updates have been made:\n\t" \
                       + "\n\t".join([json.dumps(update) for update in updates])
        subject = "MDR CRON UPDATES: " + update_type.value
        message = self.__create_message(message_text, subject)

        sent = (self.mail_service.users().messages().send(userId='me', body=message).execute())
        return sent


class SeniorReviewQueueTool:
    def __init__(self, sr_review_emails, availability):
        self.sr_review_emails = sr_review_emails
        self.availability = availability

    def __get_queue_at_last_update(self):
        return []

    def __generate_queue_by_count_issues_assigned(self):
        return []

    def get_or_generate_reviewer_queue(self):
        # todo need to actually store this in file and pull. If file is missing or unreadable for any reason we should
        #  regenerate based on min heap of assigned issues that are in 'review' status
        try:
            queue_at_last_update = self.__get_queue_at_last_update()
        except Exception:
            # If we cannot read previous state set queue to empty
            queue_at_last_update = []

        # If queue is empty either because we could not read previous state or because this is the first run
        # we should create a queue by count of issues assigned descending so that the people who have the least
        # issues currently assigned to them get assigned issues first
        if len(queue_at_last_update) == 0:
            try:
                queue_at_last_update = self.__generate_queue_by_count_issues_assigned()
            except Exception:
                #  If we cannot generate a queue by count issues assigned for any reason start with empty list
                queue_at_last_update = []

        missing_from_queue = [email for email in self.sr_review_emails if email not in queue_at_last_update]

        # return a queue of emails to assign -- note that we could use a list however dequeue guarantees O(1) perf
        return deque([Reviewer(email, self.availability[email])
                      for email in missing_from_queue + queue_at_last_update
                      if email in self.availability.keys()])


class SeniorReviewAssignmentTool:
    def __init__(self, google_helper, jira_helper):
        self.google_helper = google_helper
        self.jira_helper = jira_helper
        self.issues_to_assign = jira_helper.get_issues_to_assign()

        sr_review_emails = google_helper.get_sr_review_emails()
        availability = google_helper.get_availability(sr_review_emails)
        self.reviewer_queue = SeniorReviewQueueTool(sr_review_emails, availability).get_or_generate_reviewer_queue()

        self.skipped = []

    def __get_first_available_reviewer(self):
        reviewer = None
        while len(self.reviewer_queue) > 0 and (reviewer is None or not reviewer.is_available):
            reviewer = self.reviewer_queue.popleft()
            if reviewer.is_available:
                return reviewer
            else:
                self.skipped.append(reviewer)

        raise Exception("No Available Senior Reviewers")

    def __save_queue_to_file(self):
        # Saving state of the queue. All people who were skipped should be at top of queue next time
        queue = [reviewer.email for reviewer in self.skipped] + [reviewer.email for reviewer in self.reviewer_queue]
        with open('reviewer_queue_saved_state.data', 'wb') as filehandle:
            # store the data as binary data stream
            pickle.dump(queue, filehandle)

    def assign_sr_reviewers_to_open_tickets(self):
        updates = []
        for issue in self.issues_to_assign:
            reviewer = self.__get_first_available_reviewer()
            # customfield_18441 is senior reviewer
            issue.update(customfield_18441={'name': reviewer.ldap})
            updates.append({'issue': issue.key, 'field': 'SR_REVIEWER', 'value': reviewer.ldap})
            self.reviewer_queue.append(reviewer)
        self.__save_queue_to_file()
        self.google_helper.send_email_with_updates(updates, UpdateType.SENIOR_REVIEWER_ASSIGNMENT)
        # TODO should probably send some kind of email with all issues that were updated to the admin group

SeniorReviewAssignmentTool(GoogleHelper(), JIRAHelper()).assign_sr_reviewers_to_open_tickets()