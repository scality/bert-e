{% extends "message.md" %}

{% block title -%}
Waiting for approval
{% endblock %}

{% block message %}
The following approvals are missing before I can proceed with the merge:

{% if not author_approval %}
* the author
{% endif %}
{% if not peer_approval %}
* at least one peer
{% endif %}
{% if not tester_approval %}
* at least one tester
{% endif %}

*Please note*

The integration branches and associated pull requests have been created,
and now is a great time to review that the changesets match your expectations.
You may also cancel a changeset on a specific target version if required.

{% for pr in child_prs -%}
* child pull request #{{ pr['id'] }} will merge `{{ pr['source']['branch']['name'] }}`
 into `{{ pr['destination']['branch']['name'] }}`
{% endfor %}

The method to update the changeset is described in each child pull request. I will
re-analyse this pull request automatically after changes are pushed to the central
repository.
{% endblock %}
