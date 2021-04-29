
def bypass_incompatible_branch(job):
    return (job.settings.bypass_incompatible_branch or
            job.author_bypass.get('bypass_incompatible_branch', False))


def bypass_peer_approval(job):
    return (job.settings.bypass_peer_approval or
            job.author_bypass.get('bypass_peer_approval', False))


def bypass_leader_approval(job):
    return (job.settings.bypass_leader_approval or
            job.author_bypass.get('bypass_leader_approval', False))


def bypass_author_approval(job):
    return (job.settings.bypass_author_approval or
            job.author_bypass.get('bypass_author_approval', False))


def bypass_build_status(job):
    return (job.settings.bypass_build_status or
            job.author_bypass.get('bypass_build_status', False))


def bypass_jira_check(job):
    return (job.settings.bypass_jira_check or
            job.author_bypass.get('bypass_jira_check', False))
