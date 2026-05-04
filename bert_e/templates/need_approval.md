{% extends "message.md" %}

{% block title -%}
Waiting for approval
{% endblock %}

{% block message %}
The following approvals are needed before I can proceed with the merge:

{% if requires_author_approval %}
* the author
{% endif %}
{% if requires_assignee_approval %}
{% if assignees|length == 0 %}
* an assignee (this pull request was opened by a bot account, so an
  assignee must be set on the pull request and `/approve` it)
{% elif assignees|length == 1 %}
* the assignee (@{{ assignees[0] }} must `/approve`; this pull request was
  opened by a bot account)
{% else %}
* an assignee (one of the following must `/approve`; this pull request was
  opened by a bot account):
{% for assignee in assignees %}
  * @{{ assignee }}
{% endfor %}
{% endif %}
Note: the assignee's approval will not count toward the peer approval
requirement; a different reviewer must still approve.
{% endif %}
{% if required_peer_approvals == 1 %}
* one peer
{% elif required_peer_approvals > 1 %}
* {{ required_peer_approvals }} peers
{% endif %}
{% if requires_unanimity %}
* all participants in this pull request (unanimity option is on).
{% endif %}

{% if required_leader_approvals > 0 %}
{% if leaders|length == 1 %}
Peer approvals *must* include a mandatory approval from @{{ leaders[0] }}.
{% elif leaders|length > 1 %}
Peer approvals *must* include at least {{ required_leader_approvals }} approval{% if required_leader_approvals > 1 %}s{% endif %} from the following list:
{% for leader in leaders %}
* @{{ leader }}
{% endfor %}
{% endif %}
{% endif %}

{% if change_requesters|length > 0 %}
The following reviewers are expecting changes from the author, or must review again:
{% for reviewer in change_requesters %}
* @{{ reviewer }}
{% endfor %}
{% endif %}

{% endblock %}
