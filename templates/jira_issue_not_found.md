{% extends "message.md" %}

{% block title -%}
Issue not found
{% endblock %}

{% block message %}
Jira issue `{{ issue }}` was not found.
{% endblock %}
