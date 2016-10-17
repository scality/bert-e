{% extends "message.md" %}

{% block title -%}
Waiting for approval
{% endblock %}

{% block message %}
The following approvals are needed before I can proceed with the merge:

* the author
{% if required_peer_approvals == 1 %}
* one peer
{% elif required_peer_approvals > 1 %}
* {{ required_peer_approvals }} peers
{% endif %}
{% if requires_tester_approval %}
* one tester
{% endif %}
{% if requires_unanimity %}
* all participants in this pull request (unanimity option is on).
{% endif %}

{% endblock %}
