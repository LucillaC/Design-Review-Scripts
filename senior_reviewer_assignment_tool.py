import pickle
from collections import deque

from toolbox import UpdateType, Reviewer


class SeniorReviewQueueTool:
    def __init__(self, sr_review_emails, availability, jira_api_client):
        self.sr_review_emails = sr_review_emails
        self.availability = availability
        self.jira_api_client = jira_api_client

    def __get_queue_at_last_update(self):
        with open('reviewer_queue_saved_state.data', 'rb') as filehandle:
            # read the data as binary data stream
            queue = pickle.load(filehandle)
        return queue

    def __generate_queue_by_count_issues_assigned(self):
        count_issues_assigned_by_email = {
            email:  len(self.jira_api_client.get_open_issues_by_senior_reviewer(
                Reviewer.get_ldap_from_pinterest_email(email)))
            for email in self.sr_review_emails
        }
        return sorted([email for email in self.sr_review_emails],
                      key=lambda email: count_issues_assigned_by_email.get(email))

    def get_or_generate_reviewer_queue(self):
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
    # TODO update calendar funcs to use business days and change this to 5
    REVIEW_SLA_IN_DAYS = 7
    MIN_DAYS_AVAILABLE_FOR_ASSIGNMENT = 4

    def __init__(self, google_api_client, jira_api_client):
        self.google_api_client = google_api_client
        self.jira_api_client = jira_api_client
        self.issues_to_assign = jira_api_client.get_issues_to_assign()

        sr_review_emails = google_api_client.get_sr_review_emails()
        availability = google_api_client.get_availability(sr_review_emails)
        self.reviewer_queue = SeniorReviewQueueTool(sr_review_emails, availability, jira_api_client).get_or_generate_reviewer_queue()

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
        self.google_api_client.send_email_with_updates(updates, UpdateType.SENIOR_REVIEWER_ASSIGNMENT)
