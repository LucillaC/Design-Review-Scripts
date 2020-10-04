import json
from collections import deque

from toolbox import UpdateType, Reviewer


class InPersonDesignReviewSchedulingTool:
    UNSCHEDULED_DESIGN_REVIEW_PLACEHOLDER_TEXT = 'Review this week: [Not Yet Assigned]'
    COUNT_MEETINGS_TO_SCHEDULE_AHEAD = 4

    def __init__(self, google_api_client, jira_api_client):
        self.google_api_client = google_api_client
        self.jira_api_client = jira_api_client
        self.updated_events = []

    def __get_issue_queue(self):
        # dequeue guarantees O(1) perf
        return deque(self.jira_api_client.get_issues_requiring_in_person_review_scheduling())

    def __get_available_design_review_meetings(self):
        all_meetings = self.google_api_client.get_in_person_review_meetings(self.COUNT_MEETINGS_TO_SCHEDULE_AHEAD)
        # TODO This isn't really a good way to find out if a meeting has been assigned -- figure out something better
        return [meeting for meeting in all_meetings
                if self.UNSCHEDULED_DESIGN_REVIEW_PLACEHOLDER_TEXT in meeting.get('description')]

    def __update_description(self, meeting, issue):
        # Field gets overwritten so we need to keep the pieces that we don't want to modify
        original_description = meeting.get('description')
        description_pieces = original_description.split(self.UNSCHEDULED_DESIGN_REVIEW_PLACEHOLDER_TEXT)
        mdr_title = issue.fields.summary
        mdr_link = self.jira_api_client.get_jira_path(issue)
        linked_review = '<a href="{mdr_link}" __is_owner="true">{mdr_title}</a>'.format(mdr_title=mdr_title,
                                                                                        mdr_link=mdr_link)
        review_this_week = '\n\n\nReview this week: [{this_weeks_review}]'.format(this_weeks_review=linked_review)

        # strip any new lines from the first part of the original description in case review has been removed
        return description_pieces[0].strip() + review_this_week

    def __get_required_guests_emails_from_issue(self, issue):
        # This makes the assumption that previous guests were added based on a past ticket that may have been removed
        # this may not always be the case but seems like an OK assumption for now -- we can update to extend the list
        # rather than replace it later if this becomes a problem
        try:
            assignee = issue.fields.assignee.name
        except AttributeError:
            assignee = None
        try:
            reporter = issue.fields.reporter.name
        except AttributeError:
            reporter = None
        try:
            senior_reviewer = issue.fields.customfield_1841234.name
        except AttributeError:
            senior_reviewer = None
        try:
            approvers = [approver.name for approver in issue.fields.customfield_16501]
        except Exception:
            approvers = []
        try:
            points_of_contact = [poc.name for poc in issue.fields.customfield_16532]
        except Exception:
            points_of_contact = []

        deduped_guests = list(dict.fromkeys(
            [ldap for ldap in [assignee, reporter, senior_reviewer] + approvers + points_of_contact
             if ldap is not None]))

        return [{'email': Reviewer.get_pinterest_email_from_ldap(ldap)} for ldap in deduped_guests]

    def __assign_issue_to_meeting(self, issue, meeting):
        # Update gcal first as it is easier to recover from a partial failure where meeting is updated but issue is not
        meeting_fields_to_update = {
            'description': self.__update_description(meeting, issue),
            'attendees': self.__get_required_guests_emails_from_issue(issue),
        }
        updated_meeting = self.google_api_client.update_in_person_review_meeting_with_assigned_design_review(
            meeting.get('id'), meeting_fields_to_update)

        # update issue with meeting link
        issue.update(customfield_18402=meeting.get('htmlLink'))

        self.updated_events.append({'issue': issue.key, 'meeting': updated_meeting})

    def schedule_in_person_reviews(self):
        issues_to_schedule = self.__get_issue_queue()

        # If we have no issues to schedule may as well save the API call to get calendar events
        if len(issues_to_schedule) > 0:
            for in_person_review_meeting in self.__get_available_design_review_meetings():
                # If we have no more issues to schedule we're done!
                if len(issues_to_schedule) == 0:
                    break
                self.__assign_issue_to_meeting(issues_to_schedule.popleft(), in_person_review_meeting)

        if len(issues_to_schedule) > 0:
            # We were not able to assign all issues to an upcoming meeting -- this is a signal that we may not be
            # able to keep up with the current pace of reviews and manual intervention may be necessary
            # if this is happening consistently we should decide if we can schedule more in person review slots
            # potentially at overlapping times -- though this would increase complexity of scheduling as we would
            # need to make sure people are not scheduled for multiple meetings at the same time
            raise Exception("Not all issues could be scheduled. Issues left over are: " +
                            json.dumps([issue.key for issue in issues_to_schedule]))

        self.google_api_client.send_email_with_updates(self.updated_events, UpdateType.IN_PERSON_DESIGN_REVIEW_SCHEDULER)