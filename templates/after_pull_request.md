{% extends "message.md" %}

{% block title -%}
Waiting for Pull Request
{% endblock %}

{% block message %}
The current pull request is locked.

To unlock the pull request and proceed with the merge, the following actions are needed:

{% if opened_prs %}
Merge the opened pullrequests:
{% for pr in opened_prs %}
*  pull request #{{ pr['id'] }}
{% endfor %}
{% endif %}

{% if declined_prs %}
Remove the declined pullrequests:
{% for pr in declined_prs %}
*  pull request #{{ pr['id'] }}
{% endfor %}
{% endif %}

{% endblock %}