{% extends "message.md" %}

{% block title -%}
Waiting for Pull Request
{% endblock %}

{% block message %}
The following pullrequests are missing an appropriate action before I can proceed with the merge:

{% if declined_prs %}
Opened pullrequests:
{% for pr in declined_prs %}
*  pull request #{{ pr['id'] }}
{% endfor %}
{% endif %}

{% if declined_prs %}
Declined pullrequests:
{% for pr in declined_prs %}
*  pull request #{{ pr['id'] }}
{% endfor %}
{% endif %}

{% endblock %}