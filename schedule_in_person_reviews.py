import traceback

from google_api_client import GoogleApiClient
from in_person_design_review_scheduler import InPersonDesignReviewSchedulingTool
from jira_api_client import JiraApiClient
from toolbox import UpdateType

google_client = GoogleApiClient()
jira_client = JiraApiClient()


try:
    InPersonDesignReviewSchedulingTool(google_client, jira_client).schedule_in_person_reviews()
except Exception as ex:
    # This is not entirely safe as a failure while creating the google or jira client would throw errors not
    # caught -- however the cron email will catch these errors and its still worth sending a more descriptive
    # error here if possible
    google_client.send_pagerduty_email(ex, traceback.format_exc(), UpdateType.IN_PERSON_DESIGN_REVIEW_SCHEDULER)