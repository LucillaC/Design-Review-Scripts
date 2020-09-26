from collections import deque
# from jira import JIRA
# from knox import AutoKnox


class Reviewer:
    def __init__(self, email, is_available):
        self.email = email
        self.is_available = is_available


# Delete this should come from JIRA
class Issue:
    def __init__(self, name):
        self.name = name
        self.reviewer = None

    def set_reviewer(self, reviewer):
        self.reviewer = reviewer


class JIRAHelper:
    # This should come from JIRA
    def get_issues_to_assign(self):
        # These need some differentiating factor so that sr review is not assigned to every ticket
        # for now lets say there is some review group sr_review_board
        return [Issue("a"), Issue("b"), Issue("c"), Issue("d"), Issue("e"), Issue("f")]


class GoogleHelper:
    # TODO need to pull this from Google Groups REMEMBER TO EXCLUDE OWNERS FROM GROUP
    def get_sr_review_emails(self):
        return ["p1", "p2", "p3", "p4", "p5"]
        # return [
        #     "cbuhler@pinterest.com",
        #     "clai@pinterest.com",
        #     "doprica@pinterest.com",
        #     "ekaragiannis@pinterest.com",
        #     "jlumarie@pinterest.com",
        #     "khjertberg@pinterest.com",
        #     "mrucker@pinterest.com",
        #     "narora@pinterest.com",
        #     "romanc@pinterest.com",
        #     "shawncao@pinterest.com",
        #     "tlu@pinterest.com",
        #     "twoodson@pinterest.com",
        #     "vmohan@pinterest.com",
        #     "xiaofang@pinterest.com"
        # ]

    def get_availability(self, sr_review_emails):
        # TODO need to pull OOO from G-CAL
        map = {email: True for email in sr_review_emails}
        map["p3"] = False
        map["p4"] = False
        return map


class SeniorReviewQueueTool:
    def __init__(self, sr_review_emails, availability):
        self.sr_review_emails = sr_review_emails
        self.availability = availability

    def __get_queue_at_last_update(self):
        return ["p2", "p4", "p1"]

    def __generate_queue_by_count_issues_assigned(self):
        return ["p2", "p4", "p1"]

    def get_or_generate_reviewer_queue(self):
        # todo need to actually store this in file and pull. If file is missing or unreadable for any reason we should
        # regenerate based on min heap of assigned issues that are in 'review' status
        try:
            queue_at_last_update = self.__get_queue_at_last_update()
        except Exception:
            queue_at_last_update = self.__generate_queue_by_count_issues_assigned()

        missing_from_queue = [email for email in self.sr_review_emails if email not in queue_at_last_update]
        return deque([Reviewer(email, self.availability[email])
                      for email in missing_from_queue + queue_at_last_update
                      if email in self.availability.keys()])


class SeniorReviewAssignmentTool:
    def __init__(self, google_helper, jira_helper):
        self.issues_to_assign = jira_helper.get_issues_to_assign()

        sr_review_emails = google_helper.get_sr_review_emails()
        availability = google_helper.get_availability(sr_review_emails)
        self.reviewer_queue = SeniorReviewQueueTool(sr_review_emails, availability).get_or_generate_reviewer_queue()

        self.skipped = []

    def __get_first_available_reviewer(self):
        reviewer = None
        while len(self.reviewer_queue) > 0 and (reviewer is None or not reviewer.is_available):
            reviewer = self.reviewer_queue.popleft()
            if (reviewer.is_available):
                return reviewer
            else:
                self.skipped.append(reviewer)

        raise Exception("No Available Senior Reviewers")

    def assign_sr_reviewers_to_open_tickets(self):
        for issue in self.issues_to_assign:
            reviewer = self.__get_first_available_reviewer()
            issue.set_reviewer(reviewer.email)
            self.reviewer_queue.append(reviewer)

        print("ISSUES TO ASSIGN")
        for issue in self.issues_to_assign:
            print(issue.name, issue.reviewer)

        print("STACK TO WRITE")
        print([reviewer.email for reviewer in self.skipped] + [reviewer.email for reviewer in self.reviewer_queue])


SeniorReviewAssignmentTool(GoogleHelper(), JIRAHelper()).assign_sr_reviewers_to_open_tickets()