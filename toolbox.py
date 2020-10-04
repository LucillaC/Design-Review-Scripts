from enum import Enum


class UpdateType(Enum):
    SENIOR_REVIEWER_ASSIGNMENT = 'SENIOR REVIEWER ASSIGNMENT'
    IN_PERSON_DESIGN_REVIEW_SCHEDULER = 'IN PERSON DESIGN REVIEW SCHEDULER'


class Reviewer:
    PINTEREST_EMAIL_SUFFIX = '@pinterest.com'

    def __init__(self, email, is_available):
        self.email = email
        self.ldap = Reviewer.get_ldap_from_pinterest_email(email)
        self.is_available = is_available

    @staticmethod
    def get_ldap_from_pinterest_email(email):
        return email.split(Reviewer.PINTEREST_EMAIL_SUFFIX)[0]

    @staticmethod
    def get_pinterest_email_from_ldap(ldap):
        return ldap + Reviewer.PINTEREST_EMAIL_SUFFIX