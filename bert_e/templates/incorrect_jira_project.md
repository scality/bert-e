{% extends "message.md" %}

{% block title -%}
Incorrect Jira project
{% endblock %}

{% block message %}
The Jira issue {{ issue.key }} specified in the source
branch name, does not belong to project `{{ expected_project }}`.
{% endblock %}
