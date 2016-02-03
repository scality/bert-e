{% extends "message.md" %}

{% block title -%}
Incorrect Jira project
{% endblock %}

{% block message %}
The Jira issue {{ issue.key }}{% if subtask %}, parent of the
sub-task {{ subtask.key }}{% endif %} specified in the source
branch name, does not belong to project `{{ expected_project }}`.
{% endblock %}
