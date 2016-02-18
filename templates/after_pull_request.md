{% extends "message.md" %}

{% block title -%}
Waiting for other pull request(s)
{% endblock %}

{% block message %}
The current pull request is locked by the after_pull_request option.

In order for me to merge this pull request, run the following actions first:

{% if opened_prs %}
Merge the OPEN pull request{% if len(opened_prs) > 1 %}s{% endif %}:
{% for pr in opened_prs %}
* pull request #{{ pr['id'] }}
{% endfor %}
{% endif %}

{% if declined_prs %}
Remove the after_pull_request lock for the DECLINED pull request{% if len(opened_prs) > 1 %}s{% endif %}:
{% for pr in declined_prs %}
* pull request #{{ pr['id'] }}
{% endfor %}
{% endif %}

Alternatively, delete all the after_pull_request comments from this pull request.

{% endblock %}
