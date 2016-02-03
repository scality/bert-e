{% extends "message.md" %}

{% block title -%}
Jira parent issue not found
{% endblock %}

{% block message %}
The parent Jira issue {{ parent_id }} of subtask {{ subtask.key }} was not found.
{% endblock %}
