{% extends "message.md" %}

{% block title -%}
Incorrect Jira project
{% endblock %}

{% block message %}
The Jira issue `{{ issue }}`, extracted from the feature branch name,
does not belong to the project `{{ expected_project }}`.
{% endblock %}
