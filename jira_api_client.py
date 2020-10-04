from jira import JIRA
from knox import AutoKnox


class JiraApiClient:
    JIRA_DOMAIN = 'https://jira.pinadmin.com'
    JIRA_BROWSE_PATH = '{jira_domain}/browse/{issue_id}'
    KNOX_JIRA_ACCESS_TOKEN = 'jira_prod_api_access:access_token'
    KNOX_JIRA_ACCESS_TOKEN_SECRET = 'jira_prod_api_access:access_token_secret'
    KNOX_JIRA_CONSUMER_KEY = 'jira_prod_api_access:consumer_key'
    KNOX_JIRA_PRIVATE_KEY = 'jira_prod_api_access:key_cert'

    ISSUES_REQUIRING_SENIOR_REVIEWER_ASSIGNMENT_JQL = 'project = "Monetization Design Review" ' \
                                                      'AND status = "In Review" ' \
                                                      'AND "Senior Reviewer" = EMPTY ' \
                                                      'AND "Responsible Teams" = M10N-Senior-Review-Poo ' \
                                                      'AND Checklist is not EMPTY ' \
                                                      'AND Checklist != M10-Senior-Review-Poo'

    OPEN_ISSUES_BY_FOR_SR_REVIEWER_JQL = 'project = "Monetization Design Review"  ' \
                                         'AND "Senior Reviewer" = {ldap}  ' \
                                         'AND status = "In Review"'

    # Its important to apply an order to this query as issues should be assigned review slots in the order they
    # are created
    IN_PERSON_DESIGN_REVIEW_REQUESTED_JQL = 'project = "Monetization Design Review" ' \
                                            'AND labels = "In-Person-M10N-Design-Review-Requested" ' \
                                            'AND "google calendar meeting" is EMPTY ' \
                                            'AND status in ("In Review", "In Progress") ' \
                                            'ORDER BY created ASC'

    # Limit response to only fields we need so that we don't send/receive more data than necessary
    SENIOR_REVIEWER_FIELDS_FOR_UPDATE = ['customfield_18441']
    OPEN_ISSUES_FIELDS = ['id']
    IN_PERSON_DESIGN_REVIEW_FIELDS = ['summary', 'assignee', 'reporter',
                                      'customfield_1841234', 'customfield_16501', 'customfield_16532']

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
        return self.__search_issues(self.ISSUES_REQUIRING_SENIOR_REVIEWER_ASSIGNMENT_JQL,
                                    self.SENIOR_REVIEWER_FIELDS_FOR_UPDATE)

    def get_open_issues_by_senior_reviewer(self, ldap):
        return self.__search_issues(self.OPEN_ISSUES_BY_FOR_SR_REVIEWER_JQL.format(ldap=ldap), self.OPEN_ISSUES_FIELDS)

    def get_issues_requiring_in_person_review_scheduling(self):
        return self.__search_issues(self.IN_PERSON_DESIGN_REVIEW_REQUESTED_JQL,
                                    self.IN_PERSON_DESIGN_REVIEW_FIELDS)

    def get_jira_path(self, issue):
        return self.JIRA_BROWSE_PATH.format(jira_domain=self.JIRA_DOMAIN, issue_id=issue.key)