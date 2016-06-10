{% extends "message.md" %}

{% block title -%}
Waiting for approval
{% endblock %}

{% block message %}
The following approvals are missing before I can proceed with the merge:

{% if not author_approval %}
* the author
{% endif %}
{% if missing_peer_approvals == 1 %}
* at least one peer
{% elif missing_peer_approvals > 1 %}
* at least {missing_peer_approvals} peers
{% endif %}
{% if not tester_approval %}
* at least one tester
{% endif %}
{% if requires_unanimity %}
* all participants in this pull request (unanimity option is on)
{% endif %}

{% endblock %}
