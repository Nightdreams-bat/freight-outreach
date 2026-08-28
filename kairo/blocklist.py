def domain_of(email):
    return email.rsplit("@", 1)[-1].lower().strip()


def is_blocked(email, disallowed_emails=None, disallowed_domains=None):
    email = email.lower().strip()
    if disallowed_emails and email in {e.lower().strip() for e in disallowed_emails}:
        return True
    if disallowed_domains:
        domain = domain_of(email)
        for blocked in disallowed_domains:
            blocked = blocked.lower().strip()
            if domain == blocked or domain.endswith("." + blocked):
                return True
    return False
