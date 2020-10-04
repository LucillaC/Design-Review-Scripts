import traceback

from google_api_client import GoogleApiClient
from jira_api_client import JiraApiClient
from senior_reviewer_assignment_tool import SeniorReviewAssignmentTool
from toolbox import UpdateType

google_client = GoogleApiClient()
jira_client = JiraApiClient()


try:
    SeniorReviewAssignmentTool(google_client, jira_client).assign_sr_reviewers_to_open_tickets()
except Exception as ex:
    # This is not entirely safe as a failure while creating the google or jira client would throw errors not
    # caught -- however the cron email will catch these errors and its still worth sending a more descriptive
    # error here if possible
    google_client.send_pagerduty_email(ex, traceback.format_exc(), UpdateType.SENIOR_REVIEWER_ASSIGNMENT)